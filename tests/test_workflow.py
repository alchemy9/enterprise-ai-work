"""Real HTTP integration checks with isolated SQLite databases and controlled worker."""
import concurrent.futures
import http.cookiejar
import json
import sqlite3
import tempfile
import threading
import unittest
import urllib.request
from datetime import date,timedelta
from pathlib import Path
from app.server import AppServer
from app.db import js, today, digest
from app.domain import compute_metrics


class Client:
    def __init__(self,base,username='manager'):
        self.base=base
        self.opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        status,body=self.call('/api/auth/login',{'username':username,'password':'EawDemo!2026'})
        assert status==200,body

    def call(self,path,data=None,headers=None):
        req=urllib.request.Request(self.base+path,data=json.dumps(data).encode() if data is not None else None,headers={'Content-Type':'application/json','X-EAW-Request':'1',**(headers or {})})
        try:
            response=self.opener.open(req,timeout=10)
        except urllib.error.HTTPError as e:
            response=e
        content=response.read().decode()
        return response.status,json.loads(content) if response.headers.get('Content-Type','').startswith('application/json') else content


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.path=Path(self.temp.name)/'test.sqlite3'
        self.start_server()
        self.manager=Client(self.base)
        self.owner=Client(self.base,'owner')
        self.reviewer=Client(self.base,'reviewer')
        self.outsider=Client(self.base,'outsider')

    def start_server(self):
        self.server=AppServer(('127.0.0.1',0),self.path,worker=False)
        self.base=f'http://127.0.0.1:{self.server.server_port}'
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def ok(self,client,path,data=None):
        code,body=client.call(path,data)
        self.assertIn(code,(200,202),body)
        return body

    def run_body(self,**values):
        return {'project_id':'p_demo','period_start':(today()-timedelta(days=6)).isoformat(),'period_end':today().isoformat(),'reviewer_id':'u_manager','acknowledge_gaps':True,'submission_key':'test-run',**values}

    def drain(self):
        for _ in range(50):
            if not self.server.service.process_next():
                return
        self.fail('worker did not settle')

    def report(self,**values):
        run=self.ok(self.manager,'/api/runs',self.run_body(**values))
        self.drain()
        r=self.ok(self.manager,'/api/runs/'+run['id'])
        self.assertEqual(r['state'],'WAITING_REVIEW',r)
        return self.ok(self.manager,'/api/reports/'+r['report']['id'])

    def decision(self,r,**values):
        return {'expected_version':r['approval']['version'],'report_version':r['current_version'],'content_hash':r['current']['content_hash'],'decision':'APPROVE','comment':'核对通过','event_key':'decision-1',**values}

    def published(self):
        r=self.report()
        self.ok(self.manager,'/api/approvals/'+r['approval']['id']+'/decision',self.decision(r))
        self.drain()
        return self.ok(self.manager,'/api/reports/'+r['id'])

    def fix_item(self,r,**values):
        risk=r['current']['data']['risks'][0]
        return {'risk_id':risk['risk_id'],'title':'补齐联调检查','description':risk['fact'],'owner_id':'u_owner','due_date':today().isoformat(),'acceptance':'提供联调检查记录，确认全部检查项通过','priority':'MEDIUM',**values}

    def confirmation(self,r,items=None):
        return self.ok(self.manager,'/api/reports/'+r['id']+'/confirmations',{'expected_version':r['current_version'],'items':items or [self.fix_item(r)]})

    def execute(self,cf):
        return self.ok(self.manager,'/api/confirmations/'+cf['id']+'/execute',{'confirmed':True,'params_hash':cf['params_hash']})

    def fix(self):
        r=self.published()
        return self.execute(self.confirmation(r))['results'][0]['id']

    def transition(self,client,fid,action,version,key,**values):
        return self.ok(client,'/api/rectifications/'+fid+'/transition',{'action':action,'expected_version':version,'event_key':key,'comment':'检查已按标准完成','evidence':'联调检查记录：10 项通过，负责人陈晓确认',**values})

    def test_fixed_metrics_and_frozen_snapshot(self):
        r=self.report()
        self.assertEqual((r['current']['data']['metrics']['completion_rate'],r['current']['data']['metrics']['overdue_count']),(40,2))
        self.assertEqual(r['current']['data']['mode'],'DEMO_RULES')
        with self.server.db.tx() as c:
            row=json.loads(c.execute("SELECT data FROM ledger WHERE task_id='T-005'").fetchone()[0])
            row['status']='DONE'
            c.execute("UPDATE ledger SET data=? WHERE task_id='T-005'",(js(row),))
            with self.assertRaises(sqlite3.IntegrityError):
                c.execute("UPDATE snapshots SET rows='[]'")
        newer=self.report(submission_key='new-snapshot')
        self.assertEqual(newer['current']['data']['metrics']['completion_rate'],50)
        old=self.ok(self.manager,'/api/reports/'+r['id'])
        self.assertEqual(old['current']['data']['metrics']['completion_rate'],40)

    def test_historical_missing_and_explicit_gaps(self):
        code,body=self.manager.call('/api/runs',self.run_body(period_end=(today()-timedelta(days=1)).isoformat()))
        self.assertEqual((code,body['error']),(409,'HISTORICAL_SNAPSHOT_MISSING'))
        self.assertEqual(self.manager.call('/api/runs',self.run_body(acknowledge_gaps=False))[0],400)

    def test_submission_idempotency_and_changed_params(self):
        a=self.ok(self.manager,'/api/runs',self.run_body())
        b=self.ok(self.manager,'/api/runs',self.run_body())
        self.assertEqual(a['id'],b['id'])
        self.assertEqual(self.manager.call('/api/runs',self.run_body(reviewer_id='u_reviewer'))[0],409)

    def test_permission_and_revocation_every_request(self):
        r=self.report()
        for client in (self.owner,self.outsider):
            self.assertEqual(client.call('/api/reports/'+r['id'])[0],403)
            self.assertEqual(client.call('/api/runs/'+r['run_id'])[0],403)
        self.assertEqual(self.outsider.call('/api/projects/p_demo')[0],403)
        self.assertEqual(self.owner.call('/api/runs',self.run_body())[0],403)
        with self.server.db.tx() as c:
            c.execute("DELETE FROM memberships WHERE user_id='u_manager'")
        self.assertEqual(self.manager.call('/api/reports/'+r['id'])[0],403)
        self.assertEqual(self.manager.call('/api/reports/'+r['id']+'/export.md')[0],403)

    def test_disabled_session(self):
        with self.server.db.tx() as c:
            c.execute("UPDATE users SET active=0 WHERE id='u_owner'")
        self.assertEqual(self.owner.call('/api/me')[0],401)

    def test_report_revision_old_approval_and_hash(self):
        r=self.report()
        old_approval=r['approval']['id']
        self.ok(self.manager,'/api/reports/'+r['id']+'/withdraw',{'expected_version':1,'reason':'补充说明'})
        self.ok(self.manager,'/api/reports/'+r['id']+'/edit',{'expected_version':1,'narrative':'人工补充：负责人需核查原因。','reason':'核实后补充'})
        self.assertEqual(self.manager.call('/api/approvals/'+old_approval+'/decision',self.decision(r))[0],409)
        self.ok(self.manager,'/api/reports/'+r['id']+'/submit',{'expected_version':2,'reviewer_id':'u_manager'})
        revised=self.ok(self.manager,'/api/reports/'+r['id'])
        self.assertEqual(len(revised['versions']),2)
        self.assertTrue(revised['current']['data']['human_supplement'])
        self.assertEqual(self.manager.call('/api/approvals/'+revised['approval']['id']+'/decision',self.decision(revised,content_hash='wrong'))[0],409)
        self.assertEqual(self.manager.call('/api/reports/'+r['id']+'/edit',{'expected_version':2,'narrative':'x','reason':'x'})[0],409)
        run=self.ok(self.manager,'/api/runs/'+r['run_id'])
        reviews=[x for x in run['attempts'] if x['node']=='HumanReview']
        self.assertEqual([x['status'] for x in reviews],['CANCELLED','WAITING'])
        self.assertIsNotNone(reviews[0]['ended_at'])
        self.assertIsNone(reviews[1]['ended_at'])

    def test_approval_concurrency_and_exact_replay(self):
        r=self.report()
        path='/api/approvals/'+r['approval']['id']+'/decision'
        other=Client(self.base)
        requests=[(self.manager,self.decision(r)),(other,self.decision(r,decision='REJECT',comment='证据不足',event_key='opposite'))]
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            results=list(pool.map(lambda x:x[0].call(path,x[1]),requests))
        self.assertEqual(sorted(x[0] for x in results),[200,409])
        winner=next(i for i,x in enumerate(results) if x[0]==200)
        self.assertEqual(requests[winner][0].call(path,requests[winner][1])[0],200)
        with self.server.db.tx() as c:
            self.assertEqual(c.execute("SELECT count(*) FROM events WHERE action IN ('REPORT_APPROVED','REPORT_REJECTED')").fetchone()[0],1)

    def test_assigned_reviewer_only(self):
        r=self.report(reviewer_id='u_reviewer')
        path='/api/approvals/'+r['approval']['id']+'/decision'
        self.assertEqual(self.manager.call(path,self.decision(r))[0],403)
        self.ok(self.reviewer,path,self.decision(r))

    def test_approve_does_not_create_fixes_and_publish_failure_recovers(self):
        r=self.report()
        self.server.service.fail_once.add('PublishReport')
        self.ok(self.manager,'/api/approvals/'+r['approval']['id']+'/decision',self.decision(r))
        self.drain()
        failed=self.ok(self.manager,'/api/runs/'+r['run_id'])
        self.assertEqual(failed['state'],'FAILED')
        approved=self.ok(self.manager,'/api/reports/'+r['id'])
        self.assertEqual(approved['status'],'APPROVED')
        self.ok(self.manager,'/api/runs/'+r['run_id']+'/resume',{'expected_version':failed['version']})
        self.drain()
        pub=self.ok(self.manager,'/api/reports/'+r['id'])
        self.assertEqual(pub['status'],'PUBLISHED')
        self.assertEqual(self.ok(self.manager,'/api/projects/p_demo')['rectifications'],[])
        self.assertEqual(sum(e['action']=='REPORT_PUBLISHED' for e in pub['events']),1)
        run=self.ok(self.manager,'/api/runs/'+r['run_id'])
        review=next(x for x in run['attempts'] if x['node']=='HumanReview')
        self.assertEqual(review['status'],'SUCCEEDED')
        self.assertIsNotNone(review['ended_at'])
        self.assertEqual(self.manager.call('/api/reports/'+r['id']+'/edit',{'expected_version':1,'narrative':'x','reason':'x'})[0],409)

    def test_confirm_required_immutable_and_idempotent(self):
        r=self.published()
        cf=self.confirmation(r)
        self.assertEqual(self.manager.call('/api/confirmations/'+cf['id']+'/execute',{'confirmed':True,'params_hash':'wrong'})[0],409)
        a,b=self.execute(cf),self.execute(cf)
        self.assertEqual(a['results'][0]['id'],b['results'][0]['id'])
        changed=self.confirmation(r,[self.fix_item(r,owner_id='u_manager')])
        self.assertEqual(self.execute(changed)['results'][0]['error'],'IDEMPOTENCY_CONFLICT')
        self.assertEqual(len(self.ok(self.manager,'/api/projects/p_demo')['rectifications']),1)

    def test_confirmation_expiry_and_changed_payload(self):
        r=self.published()
        cf=self.confirmation(r)
        with self.server.db.tx() as c:
            c.execute("UPDATE confirmations SET expires_at='2000-01-01' WHERE id=?",(cf['id'],))
        self.assertEqual(self.execute(cf)['results'][0]['error'],'CONFIRMATION_EXPIRED')
        code,_=self.manager.call('/api/confirmations/'+cf['id']+'/execute',{'confirmed':True,'params_hash':cf['params_hash'],'owner_id':'u_manager'})
        self.assertEqual(code,409)

    def test_batch_partial_failure_retry_stable(self):
        r=self.published()
        risk2=r['current']['data']['risks'][1]['risk_id']
        cf=self.confirmation(r,[self.fix_item(r),self.fix_item(r,risk_id=risk2,owner_id='u_reviewer')])
        with self.server.db.tx() as c:
            c.execute("UPDATE users SET active=0 WHERE id='u_reviewer'")
        a=self.execute(cf)
        self.assertEqual(a['results'][0]['state'],'CREATED')
        self.assertIn('error',a['results'][1])
        with self.server.db.tx() as c:
            c.execute("UPDATE users SET active=1 WHERE id='u_reviewer'")
        b=self.execute(cf)
        self.assertEqual(a['results'][0]['id'],b['results'][0]['id'])
        self.assertEqual(b['results'][1]['state'],'CREATED')

    def test_full_acceptance_loop_and_permissions(self):
        fid=self.fix()
        self.assertEqual(self.manager.call('/api/rectifications/'+fid+'/transition',{'action':'START','expected_version':1,'event_key':'bad'})[0],403)
        self.transition(self.owner,fid,'START',1,'start')
        submit=self.transition(self.owner,fid,'SUBMIT',2,'submit')
        replay=self.transition(self.owner,fid,'SUBMIT',2,'submit')
        self.assertEqual(submit,replay)
        self.assertEqual(self.owner.call('/api/rectifications/'+fid+'/transition',{'action':'ACCEPT','expected_version':3,'event_key':'bad'})[0],403)
        self.transition(self.manager,fid,'RETURN',3,'return',comment='缺少环境检查截图')
        self.transition(self.owner,fid,'SUBMIT',4,'resubmit')
        self.transition(self.manager,fid,'ACCEPT',5,'accept')
        result=self.ok(self.manager,'/api/rectifications/'+fid)
        self.assertEqual(result['state'],'ACCEPTED')
        self.assertEqual(len(result['events']),6)
        self.assertEqual(self.manager.call('/api/rectifications/'+fid+'/transition',{'action':'CANCEL','expected_version':6,'event_key':'cancel','comment':'撤销'})[0],409)

    def test_transition_concurrency_single_effect(self):
        fid=self.fix()
        a=Client(self.base,'owner')
        b={'action':'START','expected_version':1,'event_key':'start'}
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            rs=list(pool.map(lambda cli:cli.call('/api/rectifications/'+fid+'/transition',b),[a,self.owner]))
        self.assertEqual([v[0] for v in rs],[200,200])
        result=self.ok(self.manager,'/api/rectifications/'+fid)
        self.assertEqual(result['version'],2)
        self.assertEqual(len(result['events']),2)

    def test_cancel_voids_approval_and_blocks_recovery(self):
        r=self.report()
        run=self.ok(self.manager,'/api/runs/'+r['run_id'])
        path='/api/runs/'+run['id']+'/cancel'
        body={'expected_version':run['version'],'reason':'用户终止'}
        self.ok(self.manager,path,body)
        self.ok(self.manager,path,body)
        self.assertEqual(self.manager.call('/api/approvals/'+r['approval']['id']+'/decision',self.decision(r))[0],409)
        self.assertEqual(self.manager.call('/api/runs/'+run['id']+'/resume',{'expected_version':run['version']+1})[0],409)
        self.drain()
        self.assertEqual(self.ok(self.manager,'/api/runs/'+run['id'])['state'],'CANCELLED')

    def test_worker_crash_restart_and_review_persistence(self):
        created=self.ok(self.manager,'/api/runs',self.run_body())
        self.server.service.process_next()
        before=self.ok(self.manager,'/api/runs/'+created['id'])
        self.server.shutdown();self.server.server_close();self.thread.join()
        self.start_server()
        self.manager=Client(self.base)
        self.drain()
        after=self.ok(self.manager,'/api/runs/'+created['id'])
        self.assertEqual(after['state'],'WAITING_REVIEW')
        self.assertEqual(after['snapshot_id'],before['snapshot_id'])
        self.assertEqual(after['data']['node_calls'],8)
        self.assertEqual(sum(a['node']=='ValidateInput' for a in after['attempts']),1)
        stored=self.ok(self.manager,'/api/reports/'+after['report']['id'])
        self.server.service.recover()
        self.assertEqual(self.ok(self.manager,'/api/reports/'+stored['id'])['approval'],stored['approval'])

    def test_upgrade_reconciles_old_review_trace_without_changing_business(self):
        from app.db import Database
        r=self.published()
        with self.server.db.tx() as c:
            c.execute("UPDATE attempts SET status='WAITING',ended_at=NULL WHERE node='HumanReview'")
            c.execute('DELETE FROM schema_migrations WHERE version=2')
        Database(self.path)
        run=self.ok(self.manager,'/api/runs/'+r['run_id'])
        review=next(a for a in run['attempts'] if a['node']=='HumanReview')
        self.assertEqual(review['status'],'SUCCEEDED')
        self.assertIsNotNone(review['ended_at'])
        after=self.ok(self.manager,'/api/reports/'+r['id'])
        self.assertEqual((after['status'],after['current']['content_hash'],after['approval']),(r['status'],r['current']['content_hash'],r['approval']))

    def test_failure_keeps_snapshot_and_attempt_budget(self):
        self.server.service.fail_once.add('RuleCompute')
        created=self.ok(self.manager,'/api/runs',self.run_body())
        self.drain()
        failed=self.ok(self.manager,'/api/runs/'+created['id'])
        self.assertEqual(failed['state'],'FAILED')
        self.assertNotIn('risks',failed['data'])
        self.ok(self.manager,'/api/runs/'+failed['id']+'/resume',{'expected_version':failed['version']})
        self.drain()
        after=self.ok(self.manager,'/api/runs/'+failed['id'])
        self.assertEqual(after['snapshot_id'],failed['snapshot_id'])
        self.assertEqual(after['data']['node_calls'],9)
        self.assertEqual(len([a for a in after['attempts'] if a['node']=='RuleCompute']),2)

    def test_csv_atomic_validation_and_repeat_import(self):
        csv='task_id,title,status,due_date\nX,标题,TODO,not-a-date\nX,重复,DONE,2026-11-10\n'
        batch=self.ok(self.manager,'/api/projects/p_demo/imports',{'csv':csv})
        self.assertTrue(batch['errors'])
        self.assertEqual(self.manager.call('/api/projects/p_demo/imports/'+batch['id']+'/commit',{})[0],400)
        self.assertEqual(len(self.ok(self.manager,'/api/projects/p_demo')['ledger']),10)
        batch=self.ok(self.manager,'/api/projects/p_demo/imports',{'csv':'task_id,title,status\nX,新增任务,TODO\n'})
        path='/api/projects/p_demo/imports/'+batch['id']+'/commit'
        self.ok(self.manager,path,{})
        self.ok(self.manager,path,{})
        self.assertEqual(len(self.ok(self.manager,'/api/projects/p_demo')['ledger']),11)

    def test_csv_duplicate_ids_owner_and_schema_rejected(self):
        for content in ['task_id,title,status\nX,第一项,TODO\nX,第二项,DONE\n', 'task_id,title,status,owner_id\nX,标题,TODO,u_other\n', 'task_id,title,status\nX,标题,UNKNOWN\n', 'task_id,title,status,completed_at,planned_start\nX,标题,DONE,2026-11-01,2026-11-10\n']:
            batch=self.ok(self.manager,'/api/projects/p_demo/imports',{'csv':content})
            self.assertTrue(batch['errors'])
            self.assertEqual(self.manager.call('/api/projects/p_demo/imports/'+batch['id']+'/commit',{})[0],400)
        self.assertEqual(len(self.ok(self.manager,'/api/projects/p_demo')['ledger']),10)

    def test_cancel_and_approval_race_cannot_reactivate(self):
        r=self.report()
        run=self.ok(self.manager,'/api/runs/'+r['run_id'])
        other=Client(self.base)
        jobs=[(self.manager,'/api/approvals/'+r['approval']['id']+'/decision',self.decision(r)),(other,'/api/runs/'+run['id']+'/cancel',{'expected_version':run['version'],'reason':'取消与审核竞争'})]
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            result=list(pool.map(lambda x:x[0].call(x[1],x[2]),jobs))
        self.assertEqual(sorted(x[0] for x in result),[200,409])
        self.drain()
        final=self.ok(self.manager,'/api/runs/'+run['id'])
        self.assertIn(final['state'],{'COMPLETED','CANCELLED'})
        self.assertEqual(len(self.ok(self.manager,'/api/projects/p_demo')['rectifications']),0)

    def test_owner_manager_cannot_self_accept(self):
        r=self.published()
        cf=self.confirmation(r,[self.fix_item(r,owner_id='u_manager')])
        fid=self.execute(cf)['results'][0]['id']
        self.transition(self.manager,fid,'START',1,'start')
        self.transition(self.manager,fid,'SUBMIT',2,'submit')
        self.assertEqual(self.manager.call('/api/rectifications/'+fid+'/transition',{'action':'ACCEPT','expected_version':3,'event_key':'self','comment':'自己验收'})[0],403)

    def test_budget_does_not_reset_on_resume(self):
        created=self.ok(self.manager,'/api/runs',self.run_body())
        self.server.service.fail_once.add('RuleCompute')
        self.drain()
        failed=self.ok(self.manager,'/api/runs/'+created['id'])
        with self.server.db.tx() as c:
            data=failed['data']
            data['node_calls']=40
            c.execute('UPDATE runs SET data=? WHERE id=?',(js(data),failed['id']))
        code,body=self.manager.call('/api/runs/'+failed['id']+'/resume',{'expected_version':failed['version']})
        self.assertEqual((code,body['error']),(409,'BUDGET_EXCEEDED'))
        self.assertEqual(self.ok(self.manager,'/api/runs/'+failed['id'])['data']['node_calls'],40)

    def test_archive_blocks_new_work_but_existing_fix_continues(self):
        fid=self.fix()
        self.ok(self.manager,'/api/projects/p_demo/status',{'expected_version':1,'status':'ARCHIVED'})
        self.assertEqual(self.manager.call('/api/runs',self.run_body(submission_key='archived'))[0],409)
        self.transition(self.owner,fid,'START',1,'start')

    def test_export_and_csrf_boundary(self):
        r=self.report()
        body=self.ok(self.manager,'/api/reports/'+r['id']+'/export.md')
        self.assertIn('未经审核',body)
        self.assertIn('40',body)
        code,_=self.manager.call('/api/runs',self.run_body(),headers={'Origin':'https://evil.example'})
        self.assertEqual(code,403)
        code,_=self.manager.call('/api/runs',self.run_body(),headers={'X-EAW-Request':''})
        self.assertEqual(code,403)


class RuleTests(unittest.TestCase):
    def test_timezone_and_future_completion(self):
        day=date(2026,11,10)
        rows=[dict(task_id='a',status='DONE',due_date='2026-11-09',completed_at='2026-11-09T16:30:00Z'),dict(task_id='b',status='DONE',due_date='2026-11-09',completed_at='2026-11-11')]
        m=compute_metrics(rows,day,day,day)
        self.assertEqual((m['completed'],m['period_completed'],m['completed_late'],m['overdue_count']),(1,1,1,1))

    def test_empty_missing_today_and_cancelled(self):
        day=date(2026,11,10)
        def row(id,status='TODO',due='',done=''):
            return dict(task_id=id,status=status,due_date=due,completed_at=done)
        self.assertIsNone(compute_metrics([],day,day,day)['completion_rate'])
        m=compute_metrics([row('a',due='2026-11-10'),row('b',due='2026-11-09'),row('c'),row('d','DONE',done=''),row('e','CANCELLED',due='2026-01-01')],day,day,day)
        self.assertEqual((m['total'],m['completed'],m['overdue_count'],m['period_completed']),(4,1,1,0))
        self.assertEqual(m['overdue_tasks'][0]['overdue_days'],1)
        self.assertTrue(any('缺截止日' in x for x in m['missing']))


if __name__=='__main__':
    unittest.main()
