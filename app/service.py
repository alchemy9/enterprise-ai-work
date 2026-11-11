"""Business API and fixed workflow. Every write is authorized and transactional."""
import json
import time
from datetime import timedelta, datetime
from .db import js, digest, now, today, uid, TZ
from .domain import BusinessError, require, text, parse_date, local_date, compute_metrics, validate_csv

NODES = ['ValidateInput','ReadSnapshot','RuleCompute','RetrieveEvidence','AnalyzeAgent','ValidateOutput','SaveDraft','HumanReview']
NODE_LABELS = dict(zip(NODES, ['校验参数与权限','冻结输入快照','计算进度指标','核对台账证据','生成风险建议','校验数字与引用','保存报告原稿','等待人工审核']))
NODE_LABELS['DeriveDraft']='派生正式版修订草稿'
NODE_LABELS['ManualTakeover']='人工接管草稿'
VERSIONS = dict(workflow='progress-v1', rules='rules-v1', prompt='demo-v1', model='DEMO_RULES', retrieval='ledger-evidence-v1')


def one(c, sql, params=()):
    r = c.execute(sql,params).fetchone()
    require(r is not None,'对象不存在或不可访问','NOT_FOUND',404)
    return dict(r)


def items(c, sql, params=()):
    return [dict(r) for r in c.execute(sql,params)]


def decoded(row):
    return {**row, 'data':json.loads(row['data'])}


class Service:
    def __init__(self, db):
        self.db = db
        self.fail_once = set()  # In-process fault injection used only by automated tests.
        from .knowledge import Knowledge
        from .source_policies import SourcePolicies
        self.sources = SourcePolicies(self)
        self.knowledge = Knowledge(self)
        from .platform import Platform
        self.platform = Platform(self)
        from .governance import Governance
        self.governance = Governance(self)
        from .advanced import Advanced
        self.advanced = Advanced(self)
        from .reporting import Reporting
        self.reporting = Reporting(self)
        from .collaboration_features import CollaborationFeatures
        self.collaboration = CollaborationFeatures(self)
        from .flows import Flows
        self.flows = Flows(self)
        from .delivery import Delivery
        self.delivery = Delivery(self)
        from .evaluations import Evaluations
        self.evaluations = Evaluations(self)

    def project(self,c,u,pid,roles=None,active=False):
        p = c.execute('SELECT p.*,m.role FROM projects p JOIN memberships m ON m.project_id=p.id JOIN users u ON u.id=m.user_id WHERE p.id=? AND m.user_id=? AND p.tenant_id=? AND u.active=1',(pid,u['id'],u['tenant_id'])).fetchone()
        require(p is not None,'没有此项目的访问权限','PERMISSION_DENIED',403)
        require(not roles or p['role'] in roles,'当前角色不能执行此操作','PERMISSION_DENIED',403)
        require(not active or p['status']=='ACTIVE','项目已归档，不能新增汇总、修改台账或创建整改','PROJECT_ARCHIVED',409)
        return dict(p)

    def member(self,c,pid,user_id,roles=None):
        r = c.execute('SELECT u.id,u.name,m.role FROM memberships m JOIN users u ON u.id=m.user_id JOIN projects p ON p.id=m.project_id WHERE m.project_id=? AND u.id=? AND u.active=1 AND u.tenant_id=p.tenant_id',(pid,user_id)).fetchone()
        require(r is not None and (not roles or r['role'] in roles),'请选择有效且有相应权限的项目成员')
        return dict(r)

    def event(self,c,u,pid,action,obj,data=None,trace=None):
        eid=uid('evt')
        c.execute('INSERT INTO events VALUES(?,?,?,?,?,?,?,?)',(eid,pid,u['id'],action,obj,js(data or {}),trace or uid('trace'),now()))
        self.platform.on_event(c,u,pid,action,obj,data or {},eid)

    def history(self,c,obj):
        return [decoded(r) for r in items(c,'SELECT e.*,u.name AS actor_name FROM events e JOIN users u ON u.id=e.actor_id WHERE object_id=? ORDER BY e.rowid',(obj,))]

    def receipt(self,c,scope,b):
        key = text(b.get('event_key'),'操作幂等键',200)
        old = c.execute('SELECT * FROM receipts WHERE scope=? AND event_key=?',(scope,key)).fetchone()
        if old:
            require(old['request_hash']==digest(b),'同一操作键的参数已变化，请刷新并重新确认','IDEMPOTENCY_CONFLICT',409)
            return json.loads(old['result'])

    def save_receipt(self,c,scope,b,result):
        c.execute('INSERT INTO receipts VALUES(?,?,?,?)',(scope,b['event_key'],digest(b),js(result)))
        return result

    def version(self,obj,b,field='version'):
        require(type(b.get('expected_version')) is int and b['expected_version']==obj[field],'页面版本已过期，请刷新后重试','VERSION_CONFLICT',409)

    def run(self,c,u,rid):
        r = decoded(one(c,'SELECT * FROM runs WHERE id=?',(rid,)))
        self.project(c,u,r['project_id'],{'manager','reviewer'})
        self.knowledge.assert_refs(c,u,r['data'].get('document_refs',[]))
        return r

    def report(self,c,u,rid):
        r = one(c,'SELECT * FROM reports WHERE id=?',(rid,))
        p = self.project(c,u,r['project_id'])
        require(r['status'] in {'PUBLISHED','SUPERSEDED'} or p['role'] in {'manager','reviewer'},'没有报告草稿访问权限','PERMISSION_DENIED',403)
        self.knowledge.assert_output(c,u,'report',rid)
        return r

    def report_detail(self,c,u,rid):
        r = self.report(c,u,rid)
        vs = [decoded(v) for v in items(c,'SELECT * FROM report_versions WHERE report_id=? ORDER BY version',(rid,))]
        approval = decoded(one(c,'SELECT * FROM approvals WHERE id=?',(r['approval_id'],))) if r['approval_id'] else None
        run = decoded(one(c,'SELECT * FROM runs WHERE id=?',(r['run_id'],)))
        run['data']=self.governance.public_data(c,u,run['data'])
        relations=items(c,'SELECT * FROM report_relations WHERE child_report_id=? OR parent_report_id=?',(rid,rid))
        updates=[]
        for ref in items(c,"SELECT s.document_id,s.document_version,d.active_version,d.title FROM output_sources s JOIN documents d ON d.id=s.document_id WHERE s.output_type='report' AND s.output_id=?",(rid,)):
            if ref['active_version'] and ref['active_version']>ref['document_version']:updates.append(ref)
        return {**r,'project_name':self.project(c,u,r['project_id'])['name'],'versions':vs,'current':vs[-1],'approval':approval,'run':run,'events':self.history(c,rid),'relations':relations,'source_updates':updates}

    def dispatch(self,c,u,method,path,b,query):
        s = path.strip('/').split('/')[1:]
        if s[0]=='retrieval' or len(s)==3 and s[0]=='documents' and s[2]=='fragments':return self.sources.dispatch(c,u,method,path,b,query)
        if s[0]=='evaluations':return self.evaluations.dispatch(c,u,method,path,b,query)
        if s[0] in {'exports','retention'} or len(s)==3 and s[0]=='rectifications' and s[2] in {'related','communication'}:return self.delivery.dispatch(c,u,method,path,b,query)
        if s[0] in {'flows','flow-runs'}:return self.flows.dispatch(c,u,method,path,b,query)
        if len(s)>=3 and s[0]=='projects' and s[2]=='reminders':return self.collaboration.dispatch(c,u,method,path,b,query)
        if len(s)>=3 and s[0]=='projects' and s[2] in {'planning','snapshots','milestones'}:
            return self.reporting.dispatch(c,u,method,path,b,query)
        if s[0] in {'connections','schedules','analyses','portfolio'} or len(s)>=3 and s[0]=='projects' and s[2] in {'connections','schedules','analyses'}:
            return self.advanced.dispatch(c,u,method,path,b,query)
        if s[0] in {'definitions','templates','operations'}:
            return self.governance.dispatch(c,u,method,path,b,query)
        if s[0] in {'admin','notifications','todos','artifacts','bookmarks'} or s==['projects'] or len(s)>=3 and s[0]=='projects' and s[2] in {'members','settings'} or len(s)==3 and s[0]=='approvals' and s[2]=='transfer':
            return self.platform.dispatch(c,u,method,path,b,query)
        if s[0] in {'documents','questions','evidence'} or len(s)>=3 and s[0]=='projects' and s[2] in {'knowledge','libraries','documents','questions','feedback'}:
            return self.knowledge.dispatch(c,u,method,path,b,query)
        if method=='GET' and s==['me']:
            projects=items(c,'SELECT p.*,m.role FROM projects p JOIN memberships m ON m.project_id=p.id WHERE m.user_id=? AND p.tenant_id=?',(u['id'],u['tenant_id']))
            return {'user':{k:u[k] for k in ['id','name','username']},'projects':projects,'system_roles':self.platform.roles(c,u),'unread':c.execute('SELECT count(*) FROM notifications WHERE user_id=? AND read_at IS NULL',(u['id'],)).fetchone()[0],'today':today().isoformat(),'mode':'DEMO_RULES','versions':VERSIONS,'templates':self.governance.templates(c,u)}
        if len(s)>=2 and s[0]=='projects':
            pid=s[1]
            p=self.project(c,u,pid)
            if method=='GET' and len(s)==2:
                rows=[json.loads(r['data']) for r in items(c,'SELECT data FROM ledger WHERE project_id=? ORDER BY task_id',(pid,))]
                people=items(c,'SELECT u.id,u.name,u.username,m.role FROM users u JOIN memberships m ON m.user_id=u.id WHERE m.project_id=? AND u.active=1',(pid,))
                role=p['role']
                reports=items(c,'SELECT r.*,w.created_at FROM reports r JOIN runs w ON w.id=r.run_id WHERE r.project_id=?'+('' if role in {'manager','reviewer'} else " AND r.status IN ('PUBLISHED','SUPERSEDED')")+' ORDER BY w.created_at DESC',(pid,))
                reports=[r for r in reports if self.knowledge.output_allowed(c,u,'report',r['id'])]
                runs=items(c,'SELECT id,state,phase,version,created_at,updated_at FROM runs WHERE project_id=? ORDER BY rowid DESC',(pid,)) if role in {'manager','reviewer'} else []
                visible_runs=[]
                for run in runs:
                    data=json.loads(c.execute('SELECT data FROM runs WHERE id=?',(run['id'],)).fetchone()[0])
                    try:
                        self.knowledge.assert_refs(c,u,data.get('document_refs',[]))
                        visible_runs.append(run)
                    except BusinessError:
                        pass
                runs=visible_runs
                fixes=self.list_fixes(c,pid)
                fixes=[f for f in fixes if self.knowledge.output_allowed(c,u,'report',f['report_id'])]
                document_count=len(self.knowledge.available_refs(c,u,pid))
                connections=[{'id':x['id'],'name':x['name'],'last_success_at':x['last_success_at'],'last_snapshot_id':x['last_snapshot_id']} for x in items(c,"SELECT id,name,last_success_at,last_snapshot_id FROM connections WHERE project_id=? AND state='ACTIVE' AND last_snapshot_id IS NOT NULL",(pid,))] if role=='manager' else []
                return {'project':p,'members':people,'ledger':rows,'metrics':compute_metrics(rows,today(),today()-timedelta(days=6),today()),'runs':runs,'reports':reports,'rectifications':fixes,'document_count':document_count,'connections':connections,'period_snapshots':self.reporting.snapshots(c,pid) if role in {'manager','reviewer'} else [],'milestones':self.reporting.milestones(c,pid),'libraries':[{'id':lib['id'],'name':lib['name']} for lib in self.knowledge.libraries(c,u,pid)],'updated_at':max((r.get('updated_at','') for r in rows),default=None)}
            if method=='POST' and len(s)==3 and s[2]=='status':
                self.project(c,u,pid,{'manager'})
                self.version(p,b)
                require(b.get('status') in {'ACTIVE','ARCHIVED'},'项目状态无效')
                if b['status']=='ARCHIVED':
                    pending=c.execute("SELECT count(*) FROM rectifications WHERE project_id=? AND state NOT IN ('ACCEPTED','CANCELLED')",(pid,)).fetchone()[0]
                    require(not pending or b.get('confirm_continue') is True,'项目还有未完成整改，请确认归档后继续处理','ARCHIVE_CONFIRMATION_REQUIRED',409,{'pending_rectifications':pending})
                c.execute('UPDATE projects SET status=?,version=version+1 WHERE id=?',(b['status'],pid))
                self.event(c,u,pid,'PROJECT_STATUS',pid,{'status':b['status'],'existing_rectifications':'continue'})
                return {'status':b['status']}
            if len(s)==3 and s[2]=='imports' and method=='POST':
                self.project(c,u,pid,{'manager'},True)
                people={r['user_id'] for r in items(c,'SELECT m.user_id FROM memberships m JOIN users u ON u.id=m.user_id WHERE m.project_id=? AND u.active=1',(pid,))}
                rows,errors=validate_csv(b.get('csv'),people)
                ident=uid('imp')
                existing={r['task_id'] for r in items(c,'SELECT task_id FROM ledger WHERE project_id=?',(pid,))}
                c.execute('INSERT INTO imports VALUES(?,?,?,?,?,?,?,?)',(ident,pid,u['id'],digest(b['csv']),js(rows),js(errors),'PREVIEW',now()))
                return {'id':ident,'total':len(rows)+len(errors),'valid':len(rows),'errors':errors,'new':sum(r['task_id'] not in existing for r in rows),'updated':sum(r['task_id'] in existing for r in rows)}
            if len(s)==5 and s[2]=='imports' and s[4]=='commit' and method=='POST':
                self.project(c,u,pid,{'manager'},True)
                batch=one(c,'SELECT * FROM imports WHERE id=? AND project_id=? AND actor_id=?',(s[3],pid,u['id']))
                require(not json.loads(batch['errors']),'CSV 有错误，整批未提交，请修正后重新预检')
                if batch['state']=='COMMITTED':
                    return {'id':batch['id'],'state':'COMMITTED','replayed':True}
                rows=json.loads(batch['rows'])
                for row in rows:
                    if row['owner_id']:
                        self.member(c,pid,row['owner_id'])
                    row['updated_at']=now()
                    c.execute('INSERT INTO ledger VALUES(?,?,?) ON CONFLICT(project_id,task_id) DO UPDATE SET data=excluded.data',(pid,row['task_id'],js(row)))
                c.execute("UPDATE imports SET state='COMMITTED' WHERE id=?",(batch['id'],))
                self.event(c,u,pid,'CSV_COMMITTED',batch['id'],{'rows':len(rows)})
                return {'id':batch['id'],'state':'COMMITTED'}
        if s==['runs'] and method=='POST':
            return self.start_run(c,u,b)
        if len(s)>=2 and s[0]=='runs':
            if method=='POST' and len(s)==3 and s[2]=='cancel':
                run=decoded(one(c,'SELECT * FROM runs WHERE id=?',(s[1],)))
                self.project(c,u,run['project_id'],{'manager'})
            else:run=self.run(c,u,s[1])
            if method=='GET' and len(s)==2:
                attempts=items(c,'SELECT * FROM attempts WHERE run_id=? ORDER BY rowid',(run['id'],))
                report=c.execute('SELECT id,status FROM reports WHERE run_id=?',(run['id'],)).fetchone()
                return {**run,'data':self.governance.public_data(c,u,run['data']),'attempts':[{**a,'label':NODE_LABELS.get(a['node'],'发布正式报告')} for a in attempts],'report':dict(report) if report else None,'events':self.history(c,run['id'])}
            if method=='POST' and len(s)==3:
                self.project(c,u,run['project_id'],{'manager'})
                if s[2]=='cancel':
                    if run['state']=='CANCELLED':
                        return {'id':run['id'],'state':'CANCELLED','committed_objects':[]}
                    self.version(run,b)
                    require(run['state']!='COMPLETED','报告已发布，不能取消已完成运行','STATE_CONFLICT',409)
                    reason=text(b.get('reason'),'取消原因')
                    report=c.execute('SELECT * FROM reports WHERE run_id=?',(run['id'],)).fetchone()
                    if report:
                        c.execute("UPDATE approvals SET state='VOID',version=version+1 WHERE report_id=? AND state='PENDING'",(report['id'],))
                        # An approval already committed remains recorded; publishing is stopped.
                        c.execute("UPDATE reports SET status='DRAFT' WHERE id=? AND status!='PUBLISHED'",(report['id'],))
                    c.execute("UPDATE attempts SET status='CANCELLED',ended_at=?,summary='运行已取消，审核等待结束' WHERE run_id=? AND status='WAITING'",(now(),run['id']))
                    self.update_run(c,run,'CANCELLED','CANCELLED')
                    self.event(c,u,run['project_id'],'RUN_CANCELLED',run['id'],{'reason':reason,'committed_objects':[]})
                    return {'id':run['id'],'state':'CANCELLED','committed_objects':[]}
                if s[2]=='resume':
                    self.version(run,b)
                    require(run['state']=='FAILED','只有故障运行可以恢复','STATE_CONFLICT',409)
                    require(run['phase']=='PUBLISHING' or run['data'].get('node_calls',0)<40,'累计节点尝试预算已耗尽，可人工接管','BUDGET_EXCEEDED',409)
                    snap=one(c,'SELECT * FROM snapshots WHERE id=?',(run['snapshot_id'],))
                    require(digest(json.loads(snap['rows']))==snap['content_hash'],'原始快照不可用，需新建运行','SOURCE_UNAVAILABLE',409)
                    phase=run['phase']
                    run['data'].pop('error',None)
                    self.update_run(c,run,'QUEUED',phase)
                    self.event(c,u,run['project_id'],'RUN_RESUMED',run['id'])
                    return {'id':run['id'],'state':'QUEUED'}
                if s[2]=='takeover':return self.reporting.takeover(c,u,run,b)
        if len(s)>=2 and s[0]=='reports':
            report=self.report(c,u,s[1])
            if method=='GET' and len(s)==2:
                return self.report_detail(c,u,report['id'])
            if method=='POST' and len(s)==3:
                if s[2]=='confirmations':
                    return self.confirm(c,u,report['id'],b)
                if s[2]=='derive':return self.reporting.revision(c,u,report,b)
                return self.report_command(c,u,report,s[2],b)
        if len(s)==3 and s[0]=='approvals' and s[2]=='decision' and method=='POST':
            return self.decide(c,u,s[1],b)
        if len(s)==3 and s[0]=='confirmations' and s[2]=='execute' and method=='POST':
            return self.execute_confirmation(c,u,s[1],b)
        if len(s)>=2 and s[0]=='rectifications':
            f=decoded(one(c,'SELECT * FROM rectifications WHERE id=?',(s[1],)))
            self.project(c,u,f['project_id'])
            self.knowledge.assert_output(c,u,'report',f['report_id'])
            if method=='GET' and len(s)==2:
                return {**f,'events':self.history(c,f['id'])}
            if method=='POST' and len(s)==3 and s[2]=='transition':
                return self.transition(c,u,f,b)
        raise BusinessError(404,'NOT_FOUND','接口不存在')

    def start_run(self,c,u,b,scheduled=False):
        pid=b.get('project_id')
        self.project(c,u,pid,{'service_runner'} if scheduled else {'manager'},True)
        key=text(b.get('submission_key'),'提交键',200)
        allowed={'project_id','submission_key','period_start','period_end','reviewer_id','acknowledge_gaps','include_documents','workflow_id','workflow_version','connection_id','snapshot_id','compare_previous','previous_snapshot_id','library_ids','focus','parent_run_id','demo_interrupt'}
        require(not(set(b)-allowed),'不允许覆盖系统字段或输入未知参数')
        old=c.execute('SELECT * FROM runs WHERE project_id=? AND actor_id=? AND submission_key=?',(pid,u['id'],key)).fetchone()
        if old:
            require(old['request_hash']==digest(b),'相同提交键的参数已变化','IDEMPOTENCY_CONFLICT',409)
            return {'id':old['id'],'state':old['state'],'replayed':True}
        start,end=parse_date(b.get('period_start')),parse_date(b.get('period_end'))
        require(start<=end<=today(),'统计周期无效，结束日期不能晚于今天')
        selected,baseline,milestones=self.reporting.input_metadata(c,u,pid,b,start,end)
        self.member(c,pid,b.get('reviewer_id'),{'manager','reviewer'})
        require(b.get('acknowledge_gaps') is True,'请检查并明确确认数据缺口后继续')
        rows=[json.loads(r['data']) for r in items(c,'SELECT data FROM ledger WHERE project_id=? ORDER BY task_id',(pid,))]
        source=None
        if b.get('connection_id'):rows,source=self.advanced.source_for_run(c,u,pid,b['connection_id'])
        if selected:
            rows=selected['rows'];source={'name':'期末快照 · '+selected['period_end'],'snapshot_id':selected['id'],'captured_at':selected['captured_at'],'mode':'HISTORICAL_'+selected['kind'],'kind':selected['kind'],'note':selected['note']}
        require(any(r['status']!='CANCELLED' for r in rows),'没有有效任务数据，不能生成进度汇总')
        self.governance.check_capacity(c,u)
        configuration=self.governance.bind(c,u,pid,b.get('workflow_id','wf_progress'),b.get('workflow_version'))
        snap,rid=uid('snap'),uid('run')
        stamp=source['captured_at'] if source else now()
        c.execute('INSERT INTO snapshots VALUES(?,?,?,?,?)',(snap,pid,stamp,digest(rows),js(rows)))
        data={'period_start':start.isoformat(),'period_end':end.isoformat(),'reviewer_id':b['reviewer_id'],'cutoff_time':stamp,'versions':VERSIONS,'mode':'DEMO_RULES','node_calls':0,'model_calls':0,'tokens':0,'cost':None,'snapshot_hash':digest(rows)}
        data['configuration']=configuration
        data.update(statistics_version='rules-v2',milestone_definitions=milestones,compare_previous=b.get('compare_previous',False),focus=b.get('focus',''))
        require(type(b.get('demo_interrupt',False)) is bool,'演示中断开关无效')
        data['demo_interrupt']=b.get('demo_interrupt',False)
        require(isinstance(data['focus'],str) and len(data['focus'])<=1000,'关注事项最多 1000 字')
        if baseline:data['previous_snapshot']={k:baseline[k] for k in ['id','period_end','kind','content_hash']}
        if source:data['data_source']=source
        data['tool_calls']=0
        libraries=b.get('library_ids')
        if libraries is not None:
            require(isinstance(libraries,list) and libraries,'请选择知识库范围')
            for lib in libraries:one(c,'SELECT id FROM knowledge_libraries WHERE id=? AND project_id=?',(lib,pid))
        data['library_ids']=libraries
        data['document_refs']=self.knowledge.available_refs(c,u,pid,libraries,at_date=end) if b.get('include_documents',True) else []
        data['retrieval_profile']=self.sources.profile(c,pid)
        reviewer=one(c,'SELECT * FROM users WHERE id=?',(b['reviewer_id'],))
        self.knowledge.assert_refs(c,reviewer,data['document_refs'])
        data['versions']={**VERSIONS,'retrieval':'local-text-v1/profile-'+str(data['retrieval_profile']['version']) if data['document_refs'] else 'ledger-evidence-v1'}
        data['versions'].update(workflow=configuration['workflow']['id']+'@v'+str(configuration['workflow']['version']),prompt=configuration['agent']['id']+'@v'+str(configuration['agent']['version']),model=configuration['model']['id']+'@v'+str(configuration['model']['version']))
        data['versions']['rules']='rules-v2'
        if b.get('parent_run_id'):
            parent=self.run(c,u,b['parent_run_id']);require(parent['project_id']==pid,'来源运行不属于当前项目','PERMISSION_DENIED',403);data['parent_run_id']=parent['id']
        c.execute('INSERT INTO runs VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(rid,pid,u['id'],snap,key,digest(b),'QUEUED','ANALYSIS',1,js(data),now(),now()))
        if b.get('parent_run_id'):c.execute('INSERT INTO run_relations VALUES(?,?,?,?)',(rid,b['parent_run_id'],'REGENERATED',now()))
        self.event(c,u,pid,'RUN_CREATED',rid,{'snapshot_id':snap},rid)
        return {'id':rid,'state':'QUEUED'}

    def update_run(self,c,run,state=None,phase=None):
        c.execute('UPDATE runs SET state=?,phase=?,version=version+1,data=?,updated_at=? WHERE id=?',(state or run['state'],phase or run['phase'],js(run['data']),now(),run['id']))

    def report_command(self,c,u,r,command,b):
        self.project(c,u,r['project_id'],{'manager'})
        run=self.run(c,u,r['run_id'])
        require(run['state'] not in {'CANCELLED','COMPLETED'},'运行已终止，不能修改报告','STATE_CONFLICT',409)
        require(command in {'withdraw','edit','submit','publish','confirmations'},'报告操作不存在')
        self.version(r,b,'current_version')
        current=decoded(one(c,'SELECT * FROM report_versions WHERE report_id=? AND version=?',(r['id'],r['current_version'])))
        if command=='withdraw':
            require(r['status']=='IN_REVIEW','报告不在审核中','STATE_CONFLICT',409)
            reason=text(b.get('reason'),'撤回原因')
            c.execute("UPDATE approvals SET state='VOID',version=version+1 WHERE id=? AND state='PENDING'",(r['approval_id'],))
            c.execute("UPDATE reports SET status='DRAFT' WHERE id=?",(r['id'],))
            c.execute("UPDATE attempts SET status='CANCELLED',ended_at=?,summary='审核已撤回，等待修订后重新提交' WHERE run_id=? AND node='HumanReview' AND status='WAITING'",(now(),run['id']))
            self.update_run(c,run,'WAITING_REVIEW','WAITING_REVISION')
            self.event(c,u,r['project_id'],'REVIEW_WITHDRAWN',r['id'],{'reason':reason,'version':r['current_version']})
        elif command=='edit':
            require(r['status'] in {'DRAFT','CHANGES_REQUESTED'},'请先撤回审核再编辑；正式报告只读','STATE_CONFLICT',409)
            require(set(b)<={'expected_version','narrative','reason','adjustments'},'统计、引用与风险事实不可由正文编辑覆盖')
            narrative=text(b.get('narrative'),'报告修订正文',16000)
            reason=text(b.get('reason'),'修改原因')
            data={**current['data'],'narrative':narrative,'human_supplement':True}
            if 'adjustments' in b:
                adjustments=b['adjustments'];require(isinstance(adjustments,list) and len(adjustments)<=6,'人工指标调整格式无效')
                allowed={'total','completed','completion_rate','period_completed','overdue_count','completed_late'};seen=set();normalized=[]
                for adjustment in adjustments:
                    require(isinstance(adjustment,dict) and set(adjustment)=={'metric','value','reason'},'人工调整字段无效')
                    metric=adjustment['metric'];value=adjustment['value'];require(metric in allowed and metric not in seen,'指标不存在或重复');seen.add(metric)
                    require(type(value) in {int,float} and 0<=value<=(100 if metric=='completion_rate' else 10000) and (metric=='completion_rate' or type(value) is int),'人工指标须为合法非负数，完成率不超过 100%')
                    normalized.append({'metric':metric,'source_value':data['metrics'][metric],'value':value,'reason':text(adjustment['reason'],'指标调整原因',2000),'actor_id':u['id'],'at':now()})
                data['human_adjustments']=normalized
            v=r['current_version']+1
            c.execute('INSERT INTO report_versions VALUES(?,?,?,?,?,?,?)',(r['id'],v,digest(data),js(data),u['id'],reason,now()))
            c.execute("UPDATE reports SET current_version=?,status='DRAFT' WHERE id=?",(v,r['id']))
            self.event(c,u,r['project_id'],'REPORT_REVISED',r['id'],{'version':v,'reason':reason})
        elif command=='submit':
            require(r['status'] in {'DRAFT','CHANGES_REQUESTED'},'只能提交草稿或退回稿','STATE_CONFLICT',409)
            reviewer=b.get('reviewer_id',run['data']['reviewer_id'])
            self.member(c,r['project_id'],reviewer,{'manager','reviewer'})
            self.new_approval(c,r,current,reviewer)
            run['data']['node_calls']+=1
            attempt=c.execute("SELECT count(*) FROM attempts WHERE run_id=? AND node='HumanReview'",(run['id'],)).fetchone()[0]+1
            c.execute('INSERT INTO attempts VALUES(?,?,?,?,?,?,?,?)',(uid('attempt'),run['id'],'HumanReview',attempt,'WAITING',now(),None,f"正文 v{r['current_version']} 已重新提交，等待人工审核"))
            self.update_run(c,run,'WAITING_REVIEW','HUMAN_REVIEW')
            self.event(c,u,r['project_id'],'REVIEW_SUBMITTED',r['id'],{'version':r['current_version'],'reviewer_id':reviewer})
        elif command=='publish':
            require(r['status']=='APPROVED','仅可发布已批准版本','STATE_CONFLICT',409)
            self.update_run(c,run,'QUEUED','PUBLISHING')
            self.event(c,u,r['project_id'],'PUBLISH_REQUESTED',r['id'])
        else:
            raise BusinessError(409,'STATE_CONFLICT','请从已发布报告独立确认整改')
        return {'id':r['id'],'operation':command}

    def new_approval(self,c,r,current,reviewer):
        aid=uid('apr')
        c.execute('INSERT INTO approvals VALUES(?,?,?,?,?,?,?,?,?)',(aid,r['id'],r['current_version'],current['content_hash'],reviewer,'PENDING',1,js({}),now()))
        c.execute("UPDATE reports SET status='IN_REVIEW',approval_id=? WHERE id=?",(aid,r['id']))
        return aid

    def decide(self,c,u,aid,b):
        a=decoded(one(c,'SELECT * FROM approvals WHERE id=?',(aid,)))
        r=self.report(c,u,a['report_id'])
        self.project(c,u,r['project_id'],{'manager','reviewer'})
        require(u['id']==a['reviewer_id'],'只有此审核单的指定审核人可决策','PERMISSION_DENIED',403)
        scope='approval:'+aid
        old=self.receipt(c,scope,b)
        if old:
            return old
        self.version(a,b)
        require(not a['data'].get('needs_transfer'),'审核人授权曾失效，请由项目经理明确转交后重新处理','REVIEW_HANDOFF_REQUIRED',409)
        require(a['state']=='PENDING' and r['status']=='IN_REVIEW' and r['approval_id']==aid,'审核单已结束或失效，请刷新','VERSION_CONFLICT',409)
        require(b.get('report_version')==a['report_version']==r['current_version'] and b.get('content_hash')==a['content_hash'],'正文版本或 hash 不匹配，不能审核','VERSION_CONFLICT',409)
        current=one(c,'SELECT content_hash FROM report_versions WHERE report_id=? AND version=?',(r['id'],r['current_version']))
        require(current['content_hash']==a['content_hash'],'正文 hash 校验失败','VERSION_CONFLICT',409)
        require(b.get('decision') in {'APPROVE','REJECT'},'审核决策无效')
        run=self.run(c,u,r['run_id'])
        require(run['state']=='WAITING_REVIEW' and run['phase']=='HUMAN_REVIEW','运行当前不能审核','STATE_CONFLICT',409)
        comment=b.get('comment','')
        require(isinstance(comment,str) and len(comment)<=2000,'审核说明过长')
        if b['decision']=='REJECT':
            text(comment,'退回原因')
        approve=b['decision']=='APPROVE'
        c.execute("UPDATE attempts SET status='SUCCEEDED',ended_at=?,summary=? WHERE run_id=? AND node='HumanReview' AND status='WAITING'",(now(),'人工审核已通过，进入发布阶段' if approve else '人工审核已退回，等待修订',run['id']))
        c.execute('UPDATE approvals SET state=?,version=version+1,data=? WHERE id=?',('APPROVED' if approve else 'REJECTED',js({'comment':comment,'actor_id':u['id'],'decided_at':now(),'content_hash':a['content_hash']}),aid))
        c.execute('UPDATE reports SET status=? WHERE id=?',('APPROVED' if approve else 'CHANGES_REQUESTED',r['id']))
        self.event(c,u,r['project_id'],'REPORT_APPROVED' if approve else 'REPORT_REJECTED',r['id'],{'report_version':a['report_version'],'content_hash':a['content_hash'],'comment':comment},run['id'])
        self.update_run(c,run,'QUEUED' if approve else 'REVIEW_REJECTED','PUBLISHING' if approve else 'WAITING_REVISION')
        if approve:
            self.event(c,u,r['project_id'],'PUBLISH_REQUESTED',r['id'],{'approved_version':a['report_version']},run['id'])
        return self.save_receipt(c,scope,b,{'id':aid,'state':'APPROVED' if approve else 'REJECTED','report_id':r['id']})

    def confirm(self,c,u,rid,b):
        r=self.report(c,u,rid)
        self.project(c,u,r['project_id'],{'manager'},True)
        require(r['status']=='PUBLISHED','仅可从已发布报告创建整改','STATE_CONFLICT',409)
        self.version(r,b,'current_version')
        raw=b.get('items')
        require(isinstance(raw,list) and 0<len(raw)<=50,'请至少选择一项风险，最多 50 项')
        current=decoded(one(c,'SELECT * FROM report_versions WHERE report_id=? AND version=?',(rid,r['current_version'])))
        risks={x['risk_id']:x for x in current['data']['risks']}
        normalized=[]
        seen=set()
        for item in raw:
            require(isinstance(item,dict),'整改参数格式无效')
            risk_id=item.get('risk_id')
            require(risk_id in risks and risk_id not in seen,'风险不存在或重复')
            seen.add(risk_id)
            normalized.append({'risk_id':risk_id,'title':text(item.get('title'),'整改标题',100),'description':text(item.get('description'),'问题描述',2000),'owner_id':text(item.get('owner_id'),'负责人',100),'due_date':text(item.get('due_date'),'截止日期',10),'acceptance':text(item.get('acceptance'),'验收标准',2000),'priority':item.get('priority','MEDIUM')})
            require(item.get('priority','MEDIUM') in {'LOW','MEDIUM','HIGH'},'优先级无效')
            self.member(c,r['project_id'],item['owner_id'],{'manager','member','reviewer','knowledge_admin'})
            owner=one(c,'SELECT * FROM users WHERE id=?',(item['owner_id'],))
            self.knowledge.assert_output(c,owner,'report',rid)
            require(parse_date(item['due_date'])>=today(),'截止日期不能早于今天')
        ident=uid('confirm')
        expiry=(datetime.now(TZ)+timedelta(minutes=30)).isoformat(timespec='seconds')
        c.execute('INSERT INTO confirmations VALUES(?,?,?,?,?,?,?,?,?)',(ident,r['project_id'],rid,r['current_version'],u['id'],digest(normalized),js(normalized),expiry,now()))
        self.event(c,u,r['project_id'],'ACTION_PREPARED',rid,{'confirmation_id':ident,'params_hash':digest(normalized),'count':len(normalized)})
        return {'id':ident,'params_hash':digest(normalized),'items':normalized,'expires_at':expiry,'report_id':rid,'report_version':r['current_version']}

    def execute_confirmation(self,c,u,ident,b):
        cf=one(c,'SELECT * FROM confirmations WHERE id=?',(ident,))
        self.project(c,u,cf['project_id'],{'manager'},True)
        require(cf['actor_id']==u['id'],'确认不属于当前操作者','PERMISSION_DENIED',403)
        require(b.get('confirmed') is True,'必须明确确认创建整改')
        require(set(b)=={'confirmed','params_hash'},'确认参数已变化，请重新生成确认单','VERSION_CONFLICT',409)
        require(b.get('params_hash')==cf['params_hash'],'确认参数摘要已变化','VERSION_CONFLICT',409)
        r=self.report(c,u,cf['report_id'])
        require(r['status'] in {'PUBLISHED','SUPERSEDED'} and r['current_version']==cf['report_version'],'来源报告版本已变化，请重新确认','VERSION_CONFLICT',409)
        normalized=json.loads(cf['items'])
        results=[]
        for item in normalized:
            action_id=item.get('action_id') or digest([cf['project_id'],cf['report_id'],cf['report_version'],item['risk_id'],'CREATE_RECTIFICATION'])
            old=c.execute('SELECT id,params_hash FROM rectifications WHERE action_id=?',(action_id,)).fetchone()
            if old:
                if old['params_hash']==digest(item):
                    results.append({'risk_id':item['risk_id'],'id':old['id'],'state':'EXISTS'})
                else:
                    results.append({'risk_id':item['risk_id'],'error':'IDEMPOTENCY_CONFLICT','message':'该风险已创建整改，参数不同，不能重复覆盖'})
                continue
            try:
                require(r['status']=='PUBLISHED' or item.get('parent_fix_id') and r['status']=='SUPERSEDED','来源正式版已被替代，仅可返回既有整改；新增事项请从新版确认','SOURCE_SUPERSEDED',409)
                if item.get('parent_fix_id'):
                    parent=one(c,'SELECT * FROM rectifications WHERE id=? AND project_id=?',(item['parent_fix_id'],cf['project_id']))
                    require(parent['state']=='ACCEPTED' if item['relation']=='FOLLOWUP' else parent['state'] not in {'ACCEPTED','CANCELLED'},'来源整改状态已变化，请重新核对','STATE_CONFLICT',409)
                require(cf['expires_at']>now(),'确认已超过 30 分钟，请重新确认','CONFIRMATION_EXPIRED',409)
                tool=self.governance.published(c,u['tenant_id'],'tool_rectify')
                self.member(c,cf['project_id'],item['owner_id'],{'manager','member','reviewer','knowledge_admin'})
                owner=one(c,'SELECT * FROM users WHERE id=?',(item['owner_id'],))
                self.knowledge.assert_output(c,owner,'report',cf['report_id'])
                require(parse_date(item['due_date'])>=today(),'截止日期已过，请重新确认')
                fid=uid('fix')
                c.execute('INSERT INTO rectifications VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',(fid,action_id,cf['project_id'],cf['report_id'],cf['report_version'],item['risk_id'],item['owner_id'],'TODO',1,digest(item),js(item),now(),now()))
                self.event(c,u,cf['project_id'],'RECTIFICATION_CREATED',fid,{'origin':cf['report_id'],'risk_id':item['risk_id'],'params_hash':digest(item),'confirmation_id':ident})
                c.execute('INSERT INTO tool_invocations VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(uid('call'),u['tenant_id'],cf['project_id'],u['id'],r['run_id'],'tool_rectify',tool['config_version'],'CreateRectification',digest(item),'SUCCEEDED','用户确认后创建整改',action_id,fid,now()))
                results.append({'risk_id':item['risk_id'],'id':fid,'state':'CREATED'})
            except BusinessError as e:
                results.append({'risk_id':item['risk_id'],'error':e.code,'message':e.message})
        return {'confirmation_id':ident,'results':results}

    def list_fixes(self,c,pid):
        return [decoded(r) for r in items(c,'SELECT f.*,u.name AS owner_name FROM rectifications f JOIN users u ON u.id=f.owner_id WHERE f.project_id=? ORDER BY f.rowid DESC',(pid,))]

    def transition(self,c,u,f,b):
        p=self.project(c,u,f['project_id'])
        action=b.get('action')
        manager_actions={'ACCEPT','RETURN','CANCEL','REASSIGN','RESCHEDULE'}
        if action in manager_actions:
            require(p['role']=='manager','仅项目经理可以执行此操作','PERMISSION_DENIED',403)
        else:
            require(f['owner_id']==u['id'],'只有负责人可以处理或提交验收','PERMISSION_DENIED',403)
        if action=='ACCEPT':
            require(f['owner_id']!=u['id'],'负责人不能自行验收，请由另一位项目经理验收','PERMISSION_DENIED',403)
        scope='transition:'+f['id']
        old=self.receipt(c,scope,b)
        if old:
            return old
        self.version(f,b)
        require(f['state'] not in {'ACCEPTED','CANCELLED'},'任务已结束，不能再次修改','STATE_CONFLICT',409)
        states={'START':({'TODO','REWORK'},'IN_PROGRESS'),'SUBMIT':({'IN_PROGRESS','REWORK'},'PENDING_ACCEPTANCE'),'ACCEPT':({'PENDING_ACCEPTANCE'},'ACCEPTED'),'RETURN':({'PENDING_ACCEPTANCE'},'REWORK'),'CANCEL':({'TODO','IN_PROGRESS','REWORK','PENDING_ACCEPTANCE'},'CANCELLED')}
        states['UPDATE']=({'IN_PROGRESS','REWORK'},f['state'])
        data=f['data']
        detail={'from':f['state'],'action':action}
        if action in {'REASSIGN','RESCHEDULE'}:
            reason=text(b.get('comment'),'调整原因')
            if action=='REASSIGN':
                self.member(c,f['project_id'],b.get('owner_id'),{'manager','member','reviewer','knowledge_admin'})
                detail.update(old_owner=f['owner_id'],new_owner=b['owner_id'])
                f['owner_id']=b['owner_id']
                data['owner_id']=b['owner_id']
                owner=one(c,'SELECT * FROM users WHERE id=?',(f['owner_id'],));self.knowledge.assert_output(c,owner,'report',f['report_id'])
                for field in ['needs_assignment','assignment_reason','assignment_detected_at']:data.pop(field,None)
            else:
                require(parse_date(b.get('due_date'))>=today(),'新截止日期不能早于今天')
                detail.update(old_due=data['due_date'],new_due=b['due_date'])
                data['due_date']=b['due_date']
            state=f['state']
            detail['comment']=reason
        else:
            require(action in states and f['state'] in states[action][0],'不允许此状态转换','STATE_CONFLICT',409)
            state=states[action][1]
            comment=text(b.get('comment'),'处理/验收说明') if action!='START' else b.get('comment','')
            evidence=text(b.get('evidence'),'处理证据（检查结果或文件定位）',4000) if action=='SUBMIT' or action=='UPDATE' and b.get('evidence') else ''
            detail.update(to=state,comment=comment,evidence=evidence)
            if action=='SUBMIT':
                data['last_submission']={'comment':comment,'evidence':evidence,'submitted_at':now(),'actor_id':u['id']}
        c.execute('UPDATE rectifications SET owner_id=?,state=?,version=version+1,data=?,updated_at=? WHERE id=?',(f['owner_id'],state,js(data),now(),f['id']))
        self.event(c,u,f['project_id'],'RECTIFICATION_'+action,f['id'],detail)
        return self.save_receipt(c,scope,b,{'id':f['id'],'state':state,'version':f['version']+1})

    def recover(self):
        self.delivery.recover()
        self.flows.recover()
        self.knowledge.recover()
        with self.db.tx() as c:
            for row in items(c,"SELECT * FROM runs WHERE state='RUNNING'"):
                r=decoded(row)
                self.update_run(c,r,'QUEUED')
                self.event(c,{'id':r['actor_id']},r['project_id'],'WORKER_RECOVERED',r['id'],{'snapshot_id':r['snapshot_id'],'node_calls':r['data']['node_calls']},r['id'])

    def process_next(self):
        if self.evaluations.process_next():return True
        if self.delivery.process_next():return True
        if self.collaboration.process_next():return True
        if self.flows.process_next():return True
        if self.advanced.process_next():
            return True
        if self.knowledge.process_next():
            return True
        with self.db.tx() as c:
            row=c.execute("SELECT * FROM runs WHERE state IN ('QUEUED','RUNNING') ORDER BY rowid LIMIT 1").fetchone()
            if not row:
                return False
            r=decoded(dict(row))
            completed={a['node'] for a in items(c,"SELECT node FROM attempts WHERE run_id=? AND status='SUCCEEDED'",(r['id'],))}
            node='PublishReport' if r['phase']=='PUBLISHING' else next((n for n in NODES if n not in completed),None)
            if not node:
                return False
            attempt=c.execute('SELECT count(*) FROM attempts WHERE run_id=? AND node=?',(r['id'],node)).fetchone()[0]+1
            started=now()
            active_started=time.monotonic()
            r['data']['node_calls']+=1
            invocation=None
            c.execute('SAVEPOINT node_work')
            try:
                u=one(c,'SELECT * FROM users WHERE id=?',(r['actor_id'],))
                self.project(c,u,r['project_id'],{'service_runner'} if r['data'].get('schedule_id') else {'manager'})
                if r['data'].get('schedule_id'):
                    schedule=decoded(one(c,'SELECT * FROM schedules WHERE id=?',(r['data']['schedule_id'],)))
                    self.advanced.valid_schedule_identity(c,schedule)
                require(node=='PublishReport' or r['data']['node_calls']<=40,'累计节点尝试超过上限，可人工接管','BUDGET_EXCEEDED',409)
                budget=r['data'].get('configuration',{}).get('agent',{}).get('data',{}).get('budget',{})
                if node!='PublishReport':require(r['data'].get('active_seconds',0)<budget.get('active_seconds',300),'分析活跃时间预算已用尽，已有输入和结果保留','BUDGET_EXCEEDED',409)
                invocation=self.governance.check_node(c,u,r,node)
                if node in self.fail_once:
                    self.fail_once.remove(node)
                    raise BusinessError(503,'SOURCE_UNAVAILABLE','测试注入：节点暂不可用，可从原快照恢复')
                if node=='AnalyzeAgent' and r['data'].get('demo_interrupt') and not r['data'].get('demo_interrupt_fired'):
                    r['data']['demo_interrupt_fired']=True
                    raise BusinessError(409,'DEMO_INTERRUPTION','此运行演示了一次分析中断。输入与已完成步骤保留，可恢复运行或人工接管；这不是外部服务故障。')
                summary=self.perform_node(c,u,r,node)
                r['data']['active_seconds']=round(r['data'].get('active_seconds',0)+time.monotonic()-active_started,5)
                c.execute('UPDATE runs SET data=? WHERE id=?',(js(r['data']),r['id']))
                c.execute('RELEASE node_work')
                self.governance.log_tool(c,u,r,node,invocation,'SUCCEEDED',summary)
                c.execute('INSERT INTO attempts VALUES(?,?,?,?,?,?,?,?)',(uid('attempt'),r['id'],node,attempt,'WAITING' if node=='HumanReview' else 'SUCCEEDED',started,None if node=='HumanReview' else now(),summary))
            except Exception as exc:
                c.execute('ROLLBACK TO node_work')
                c.execute('RELEASE node_work')
                code=exc.code if isinstance(exc,BusinessError) else 'INTERNAL_ERROR'
                message=exc.message if isinstance(exc,BusinessError) else '节点执行失败，已保留输入，请联系维护人员并提供运行编号'
                r['data']['active_seconds']=round(r['data'].get('active_seconds',0)+time.monotonic()-active_started,5)
                if invocation:self.governance.log_tool(c,u,r,node,invocation,'FAILED',message)
                r['data']['error']={'code':code,'message':message,'node':node,'trace_id':r['id']}
                self.update_run(c,r,'FAILED','PUBLISHING' if node=='PublishReport' else 'ANALYSIS')
                c.execute('INSERT INTO attempts VALUES(?,?,?,?,?,?,?,?)',(uid('attempt'),r['id'],node,attempt,'FAILED',started,now(),message))
                self.event(c,{'id':r['actor_id']},r['project_id'],'RUN_FAILED',r['id'],r['data']['error'],r['id'])
                if not isinstance(exc,BusinessError):
                    import traceback
                    traceback.print_exc()
            return True

    def perform_node(self,c,u,r,node):
        d=r['data']
        snap=one(c,'SELECT * FROM snapshots WHERE id=?',(r['snapshot_id'],))
        rows=json.loads(snap['rows'])
        require(digest(rows)==snap['content_hash'],'冻结快照完整性校验失败','SOURCE_UNAVAILABLE',409)
        summary=''
        state,phase='RUNNING','ANALYSIS'
        if node=='ValidateInput':
            require(bool(rows),'台账数据为空')
            self.member(c,r['project_id'],d['reviewer_id'],{'manager','reviewer'})
            summary='身份、项目、审核人和统计周期已校验'
        elif node=='ReadSnapshot':
            summary=f"冻结 {len(rows)} 行台账；快照 {snap['id']}"
        elif node=='RuleCompute':
            d['metrics']=self.reporting.metrics(c,r,rows)
            summary=f"完成率 {d['metrics']['completion_rate']}%；未完成逾期 {d['metrics']['overdue_count']} 项"
        elif node=='RetrieveEvidence':
            d['evidence']=[{'evidence_id':'E-'+row['task_id'],'snapshot_id':snap['id'],'locator':row['task_id'],'title':row['title'],'row':row,'version':snap['content_hash'][:12]} for row in rows]
            for milestone in d.get('milestone_definitions',[]):
                d['evidence'].append({'evidence_id':'E-M-'+milestone['id'],'kind':'MILESTONE','snapshot_id':snap['id'],'title':'里程碑 · '+milestone['name'],'locator':milestone['id'],'version':str(milestone['version']),'milestone':milestone})
            doc_refs=d.get('document_refs',[])
            reviewer=one(c,'SELECT * FROM users WHERE id=?',(d['reviewer_id'],))
            self.knowledge.assert_refs(c,reviewer,doc_refs)
            documents=self.knowledge.evidence(c,u,doc_refs,limit=30,profile=d.get('retrieval_profile'))
            remaining=d.get('configuration',{}).get('agent',{}).get('data',{}).get('budget',{}).get('context_chars',40000)
            selected=[]
            for evidence in documents:
                if len(evidence['text'])>remaining:
                    d['context_truncated']=True
                    continue
                selected.append(evidence)
                remaining-=len(evidence['text'])
            documents=selected
            for evidence in documents:
                evidence['snapshot_id']=snap['id']
            d['evidence']+=documents
            d['retrieval_status']='LOCAL_TEXT' if documents else 'LEDGER_ONLY'
            summary=f"已绑定台账证据及 {len(documents)} 条授权文档片段；来源版本已冻结"
        elif node=='AnalyzeAgent':
            from .variables import resolve
            d['analysis_context']=resolve(d.get('configuration',{}).get('workflow',{}).get('data',{}),d,node,snapshot_id=r['snapshot_id'])
            d['risks']=[{'risk_id':'R-'+row['task_id'],'title':row['title']+'逾期','fact':f"任务 {row['task_id']} 尚未完成，截至数据截点已逾期 {row['overdue_days']} 个自然日。",'task_id':row['task_id'],'level':'LOW','evidence_ids':['E-'+row['task_id']],'hypothesis':'无法确认原因；缺少会议纪要与依赖信息，请负责人补充。','recommendation':'核实阻塞项，补齐处理证据并提交项目经理验收。','pending_fields':['负责人','截止日期','验收标准']} for row in d['metrics']['overdue_tasks']]
            for risk in d['risks']:
                ms=d['metrics'].get('milestones',[])
                critical=[m for m in ms if m['critical'] and m['status']=='OVERDUE' and risk['task_id'] in m['task_ids']]
                downstream=[m for m in ms if m['status']!='DONE' and any(up in m['depends_on'] for up in [x['id'] for x in ms if risk['task_id'] in x['task_ids']])]
                risk['level']='HIGH' if critical else 'MEDIUM' if downstream else 'LOW'
                risk['rule_trigger']='关键里程碑逾期' if critical else '逾期事项存在未完成下游依赖' if downstream else '普通任务逾期；关键路径依据不足时不升级'
                risk['impact']='可能影响 '+('、'.join(m['name'] for m in critical or downstream)) if critical or downstream else '当前任务交付受影响，下游影响需补充依据。'
                risk['evidence_ids']+=['E-M-'+m['id'] for m in critical or downstream]
                agent=d.get('configuration',{}).get('agent',{}).get('data',{})
                if agent.get('recommendation'):risk['recommendation']=agent['recommendation']
                threshold=d.get('configuration',{}).get('workflow',{}).get('data',{}).get('rules',{}).get('followup_days',3)
                task=next(x for x in d['metrics']['overdue_tasks'] if x['task_id']==risk['task_id'])
                if task['overdue_days']>=threshold:risk['pending_fields'].append('已达到 '+str(threshold)+' 天关注阈值，请确认阻塞与恢复计划')
                supporting=[e for e in d['evidence'] if e.get('kind')=='DOCUMENT' and risk['task_id'] in e['text']]
                if supporting:
                    risk['hypothesis']='资料记录（原因仍待核实）：'+supporting[0]['text'][:400]
                    risk['evidence_ids']+=[supporting[0]['evidence_id']]
            summary=f"演示规则生成 {len(d['risks'])} 项待确认风险；未调用 LLM"
        elif node=='ValidateOutput':
            expected=self.reporting.metrics(c,r,rows)
            require(d['metrics']==expected,'输出统计与规则不一致','OUTPUT_INVALID',409)
            ids={e['evidence_id'] for e in d['evidence']}
            self.knowledge.assert_refs(c,u,d.get('document_refs',[]))
            require(all(set(risk['evidence_ids'])<=ids for risk in d['risks']),'输出含无效引用','OUTPUT_INVALID',409)
            summary='统计数字、风险字段与引用归属校验通过'
        elif node=='SaveDraft':
            rid=uid('report')
            report_data={'title':'项目进度汇总','narrative':'本期进展以冻结台账为准。请重点核对逾期任务，补充阻塞原因、计划与处理证据。\n\n下周期关注：推动未完成事项，确认风险对应的整改负责人及验收要求。','metrics':d['metrics'],'risks':d['risks'],'evidence':d['evidence'],'missing':d['metrics']['missing'],'snapshot_id':snap['id'],'cutoff_time':d['cutoff_time'],'period_start':d['period_start'],'period_end':d['period_end'],'mode':'DEMO_RULES','human_supplement':False}
            prefix=d.get('configuration',{}).get('workflow',{}).get('data',{}).get('narrative_prefix')
            if prefix:report_data['narrative']=prefix+'\n\n请重点核对逾期任务，补充阻塞原因、计划与处理证据。\n\n下周期关注：确认整改负责人及验收要求。'
            report_data['document_refs']=d.get('document_refs',[])
            if d.get('retrieval_profile'):report_data['retrieval_profile']=d['retrieval_profile']
            report_data['completed_tasks']=[x for x in rows if x['status']=='DONE' and x.get('completed_at') and parse_date(d['period_start'])<=local_date(x['completed_at'])<=min(parse_date(d['period_end']),datetime.fromisoformat(d['cutoff_time']).date())]
            report_data['in_progress_tasks']=[x for x in rows if x['status'] not in {'DONE','CANCELLED'}]
            report_data['focus']=d.get('focus','')
            if d.get('previous_snapshot'):report_data['previous_snapshot']=d['previous_snapshot']
            if d.get('data_source'):report_data['data_source']=d['data_source']
            if d.get('context_truncated'):report_data['missing']=report_data['missing']+['部分文档片段超出本次上下文预算，未进入分析；请收窄范围或补充人工核对。']
            if report_data['document_refs']:
                report_data['missing']=[m for m in report_data['missing'] if '未接入会议纪要' not in m]+['分析为规则与原文摘录，延期原因仍需人工核实。']
            c.execute("INSERT INTO reports VALUES(?,?,?,?,?,NULL)",(rid,r['id'],r['project_id'],1,'DRAFT'))
            c.execute('INSERT INTO report_versions VALUES(?,?,?,?,?,?,?)',(rid,1,digest(report_data),js(report_data),u['id'],'演示规则原稿',now()))
            self.knowledge.attach_sources(c,'report',rid,d.get('document_refs',[]))
            if d.get('parent_run_id'):
                parent=c.execute('SELECT id,current_version FROM reports WHERE run_id=?',(d['parent_run_id'],)).fetchone()
                if parent:c.execute('INSERT INTO report_relations VALUES(?,?,?,?,?,?,?)',(rid,parent['id'],parent['current_version'],'REGENERATED','根据新输入重新生成',u['id'],now()))
            d['report_id']=rid
            self.event(c,u,r['project_id'],'REPORT_DRAFTED',rid,{'version':1,'content_hash':digest(report_data)},r['id'])
            summary='原稿 v1 已保存，正文与 hash 不可覆盖'
        elif node=='HumanReview':
            self.member(c,r['project_id'],d['reviewer_id'],{'manager','reviewer'})
            report=one(c,'SELECT * FROM reports WHERE run_id=?',(r['id'],))
            current=one(c,'SELECT * FROM report_versions WHERE report_id=? AND version=?',(report['id'],report['current_version']))
            self.new_approval(c,report,current,d['reviewer_id'])
            self.event(c,u,r['project_id'],'REVIEW_SUBMITTED',report['id'],{'version':report['current_version'],'reviewer_id':d['reviewer_id']},r['id'])
            state,phase='WAITING_REVIEW','HUMAN_REVIEW'
            summary='审核单已持久化，等待明确人工决策'
        elif node=='PublishReport':
            self.knowledge.assert_refs(c,u,d.get('document_refs',[]))
            report=one(c,'SELECT * FROM reports WHERE run_id=?',(r['id'],))
            approval=one(c,'SELECT * FROM approvals WHERE id=?',(report['approval_id'],))
            require(report['status']=='APPROVED' and approval['state']=='APPROVED','报告尚未批准，禁止发布','STATE_CONFLICT',409)
            require(report['current_version']==approval['report_version'],'批准版本与当前版本不同','VERSION_CONFLICT',409)
            self.member(c,r['project_id'],approval['reviewer_id'],{'manager','reviewer'})
            current=one(c,'SELECT * FROM report_versions WHERE report_id=? AND version=?',(report['id'],report['current_version']))
            require(current['content_hash']==approval['content_hash'],'批准内容 hash 不一致','VERSION_CONFLICT',409)
            self.reporting.published(c,u,r,report)
            c.execute("UPDATE reports SET status='PUBLISHED' WHERE id=?",(report['id'],))
            self.event(c,u,r['project_id'],'REPORT_PUBLISHED',report['id'],{'version':report['current_version'],'content_hash':current['content_hash']},r['id'])
            state,phase='COMPLETED','PUBLISHED'
            summary='已批准版本正式发布；未自动创建整改'
        self.update_run(c,r,state,phase)
        return summary
