"""Reporting features built around immutable, explicitly dated inputs."""
import json
from datetime import datetime,timedelta
from .db import now,today,TZ,uid,js,digest
from .domain import require,text,parse_date,local_date,validate_csv,compute_metrics,BusinessError
from .knowledge import row,rows


class Reporting:
    def __init__(self,host):
        self.host,self.db=host,host.db
        with self.db.tx() as c:
            for r in rows(c,"SELECT * FROM reports WHERE status IN ('PUBLISHED','SUPERSEDED') AND id NOT IN (SELECT report_id FROM report_publications)"):
                e=c.execute("SELECT * FROM events WHERE object_id=? AND action='REPORT_PUBLISHED' ORDER BY rowid DESC LIMIT 1",(r['id'],)).fetchone()
                if e:c.execute('INSERT INTO report_publications VALUES(?,?,?,?,NULL)',(r['id'],r['current_version'],e['actor_id'],e['created_at']))

    def milestones(self,c,pid):
        return [{**x,'critical':bool(x['critical']),'data':json.loads(x['data'])} for x in rows(c,'SELECT * FROM milestones WHERE project_id=? ORDER BY due_date,id',(pid,))]

    def snapshots(self,c,pid):
        found=rows(c,'SELECT p.*,s.captured_at,s.content_hash,s.rows,u.name AS actor_name FROM period_snapshots p JOIN snapshots s ON s.id=p.id JOIN users u ON u.id=p.actor_id WHERE p.project_id=? ORDER BY p.period_end DESC,p.rowid DESC',(pid,))
        return [{**{k:v for k,v in x.items() if k!='rows'},'data':json.loads(x['data']),'row_count':len(json.loads(x['rows']))} for x in found]

    def get_snapshot(self,c,u,pid,ident):
        self.host.project(c,u,pid,{'manager','reviewer','service_runner'})
        x=row(c,'SELECT p.*,s.captured_at,s.content_hash,s.rows FROM period_snapshots p JOIN snapshots s ON s.id=p.id WHERE p.id=? AND p.project_id=?',(ident,pid))
        x['rows']=json.loads(x['rows']);x['data']=json.loads(x['data'])
        require(digest(x['rows'])==x['content_hash'],'历史快照完整性检查失败','SOURCE_UNAVAILABLE',409)
        return x

    def dispatch(self,c,u,method,path,b,query):
        s=path.strip('/').split('/')[1:]
        pid=s[1];self.host.project(c,u,pid,{'manager','reviewer'})
        if len(s)==3 and s[2]=='planning' and method=='GET':
            return {'milestones':self.milestones(c,pid),'snapshots':self.snapshots(c,pid),'tasks':[json.loads(x['data']) for x in rows(c,'SELECT data FROM ledger WHERE project_id=? ORDER BY task_id',(pid,))]}
        if s[2]=='snapshots':
            if len(s)==4 and method=='GET':
                x=self.get_snapshot(c,u,pid,s[3]);x['metrics']=compute_metrics(x['rows'],parse_date(x['period_end']),parse_date(x['period_end'])-timedelta(days=6),parse_date(x['period_end']));return x
            self.host.project(c,u,pid,{'manager'},True)
            if method=='POST' and len(s)==3:
                replay=self.host.receipt(c,'snapshot:'+pid,b)
                if replay:return replay
                kind=b.get('kind');require(kind in {'CURRENT','IMPORTED','DEMO'},'快照类型无效')
                note=text(b.get('note'),'来源与截点说明',2000)
                end=parse_date(b.get('period_end'))
                require(end<=today(),'快照日期不能晚于今天')
                if kind=='CURRENT':require(end==today(),'当前采集不能冒充历史期末，请导入历史快照')
                else:require(end<today(),'期末快照用于已经结束的日期；当天请采集当前快照')
                if kind=='IMPORTED':
                    people={x['user_id'] for x in rows(c,'SELECT m.user_id FROM memberships m JOIN users u ON u.id=m.user_id WHERE m.project_id=? AND u.active=1',(pid,))}
                    records,errors=validate_csv(b.get('csv'),people)
                    require(not errors,'历史 CSV 有错误，快照未保存','SOURCE_INVALID',400,{'errors':errors[:30]})
                else:records=[json.loads(x['data']) for x in rows(c,'SELECT data FROM ledger WHERE project_id=? ORDER BY task_id',(pid,))]
                require(records,'没有可保存的任务数据')
                cutoff=now() if kind=='CURRENT' else datetime.combine(end,datetime.max.time().replace(microsecond=0),TZ).isoformat(timespec='seconds')
                if kind=='DEMO':
                    # Explicit fictional history for a repeatable product demonstration.
                    for i,record in enumerate(records):
                        record['status']='DONE' if i<max(1,len(records)//5) else 'IN_PROGRESS'
                        record['completed_at']=(end-timedelta(days=1)).isoformat() if record['status']=='DONE' else ''
                        record['planned_start']=min(record.get('planned_start') or end.isoformat(),(end-timedelta(days=3)).isoformat())
                        record['updated_at']=cutoff
                for record in records:
                    for key in ['completed_at','updated_at']:
                        require(not record.get(key) or local_date(record[key])<=end,'快照含晚于截点的 '+key+'，请核对历史数据','SOURCE_CUTOFF_CONFLICT',409)
                ident=uid('snap')
                c.execute('INSERT INTO snapshots VALUES(?,?,?,?,?)',(ident,pid,cutoff,digest(records),js(records)))
                metadata={'declared_source':'本地模拟历史数据' if kind=='DEMO' else '用户提供的历史期末数据，未核验外部真实性' if kind=='IMPORTED' else '本次当前台账采集','milestones':self.milestones(c,pid) if kind=='CURRENT' else [],'full_day':kind!='CURRENT','fictional':kind=='DEMO'}
                c.execute('INSERT INTO period_snapshots VALUES(?,?,?,?,?,?,?,?)',(ident,pid,end.isoformat(),kind,note,u['id'],js(metadata),now()))
                self.host.event(c,u,pid,'PERIOD_SNAPSHOT_CREATED',ident,{'kind':kind,'period_end':end.isoformat(),'row_count':len(records),'note':note})
                return self.host.save_receipt(c,'snapshot:'+pid,b,{'id':ident,'kind':kind,'period_end':end.isoformat()})
        if s[2]=='milestones' and method=='POST':
            self.host.project(c,u,pid,{'manager'},True)
            if len(s)==5 and s[4]=='remove':
                target=row(c,'SELECT * FROM milestones WHERE id=? AND project_id=?',(s[3],pid));self.host.version(target,b)
                for other in self.milestones(c,pid):require(target['id'] not in other['data']['depends_on'],'其他里程碑仍依赖此项，请先调整依赖','DEPENDENCY_EXISTS',409)
                c.execute('DELETE FROM milestones WHERE id=?',(target['id'],));self.host.event(c,u,pid,'MILESTONE_REMOVED',target['id']);return {'id':target['id']}
            name=text(b.get('name'),'里程碑名称',100);due=parse_date(b.get('due_date')).isoformat();critical=b.get('critical',False)
            require(type(critical) is bool,'关键里程碑标识无效')
            tasks=b.get('task_ids',[]);deps=b.get('depends_on',[])
            require(isinstance(tasks,list) and tasks and len(tasks)==len(set(tasks)) and len(tasks)<=10000,'请选择不重复的关联任务')
            for task in tasks:row(c,'SELECT task_id FROM ledger WHERE project_id=? AND task_id=?',(pid,task))
            require(isinstance(deps,list) and len(deps)==len(set(deps)),'依赖项无效')
            ident=s[3] if len(s)==4 else uid('milestone')
            if len(s)==4:
                old=row(c,'SELECT * FROM milestones WHERE id=? AND project_id=?',(ident,pid));self.host.version(old,b)
            graph={x['id']:x['data']['depends_on'] for x in self.milestones(c,pid)}
            require(all(x in graph and x!=ident for x in deps),'依赖里程碑不存在或引用自身')
            graph[ident]=deps
            def visit(node,path):
                require(node not in path,'里程碑依赖存在循环')
                for upstream in graph.get(node,[]):visit(upstream,path|{node})
            for node in graph:visit(node,set())
            data={'task_ids':tasks,'depends_on':deps}
            c.execute('INSERT INTO milestones VALUES(?,?,?,?,?,1,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,due_date=excluded.due_date,critical=excluded.critical,version=milestones.version+1,data=excluded.data,updated_at=excluded.updated_at',(ident,pid,name,due,int(critical),js(data),now(),now()))
            self.host.event(c,u,pid,'MILESTONE_UPDATED',ident,{'name':name,'due_date':due,'critical':critical,'task_ids':tasks,'depends_on':deps})
            return {'id':ident}
        raise BusinessError(404,'NOT_FOUND','报告规划接口不存在')

    def input_metadata(self,c,u,pid,b,start,end):
        selected=None
        if b.get('snapshot_id'):
            selected=self.get_snapshot(c,u,pid,b['snapshot_id'])
            require(selected['period_end']==end.isoformat(),'快照日期必须与统计结束日期一致')
            require(end==today() or selected['data']['full_day'],'历史报告需使用明确声明的期末快照，不能使用当日中途采集','HISTORICAL_SNAPSHOT_MISSING',409)
            require(not b.get('connection_id'),'历史快照与连接来源不能同时选择')
        else:require(end==today(),'缺少该历史周期的期末快照，请先导入或选择历史快照','HISTORICAL_SNAPSHOT_MISSING',409)
        compare=b.get('compare_previous',False);require(type(compare) is bool,'比较开关无效')
        baseline=None
        if b.get('previous_snapshot_id'):
            require(compare,'请先启用上期比较')
            baseline=self.get_snapshot(c,u,pid,b['previous_snapshot_id'])
            require(baseline['period_end']==(start-timedelta(days=1)).isoformat() and baseline['data']['full_day'],'比较快照必须为本周期开始前一天的期末快照')
        elif compare:
            previous=c.execute("SELECT id FROM period_snapshots WHERE project_id=? AND period_end=? AND kind IN ('IMPORTED','DEMO') ORDER BY rowid DESC LIMIT 1",(pid,(start-timedelta(days=1)).isoformat())).fetchone()
            if previous:baseline=self.get_snapshot(c,u,pid,previous['id'])
        milestones=selected['data'].get('milestones',[]) if selected else self.milestones(c,pid)
        return selected,baseline,milestones

    def metrics(self,c,r,records):
        d=r['data'];cutoff=datetime.fromisoformat(d['cutoff_time']).date();start,end=parse_date(d['period_start']),parse_date(d['period_end'])
        result=compute_metrics(records,cutoff,start,end)
        if d.get('statistics_version')!='rules-v2':return result
        result['milestones']=[]
        by_id={x['task_id']:x for x in records}
        for m in d.get('milestone_definitions',[]):
            tasks=[by_id[x] for x in m['data']['task_ids'] if x in by_id and by_id[x]['status']!='CANCELLED']
            completed=[x for x in tasks if x['status']=='DONE' and (not x.get('completed_at') or local_date(x['completed_at'])<=cutoff)]
            status='NO_TASKS' if not tasks else 'DONE' if len(completed)==len(tasks) else 'OVERDUE' if parse_date(m['due_date'])<cutoff else 'ON_TRACK'
            result['milestones'].append({'id':m['id'],'name':m['name'],'due_date':m['due_date'],'critical':m['critical'],'status':status,'completed':len(completed),'total':len(tasks),'task_ids':[x['task_id'] for x in tasks],'depends_on':m['data']['depends_on']})
        if result['milestones']:result['missing']=[x for x in result['missing'] if '缺少里程碑' not in x]
        baseline=d.get('previous_snapshot')
        result['comparison']=None
        if baseline:
            prior=row(c,'SELECT * FROM snapshots WHERE id=? AND project_id=?',(baseline['id'],r['project_id']));previous=json.loads(prior['rows'])
            require(digest(previous)==prior['content_hash'],'上期快照不可用','SOURCE_UNAVAILABLE',409)
            old=compute_metrics(previous,parse_date(baseline['period_end']),start-(end-start)-timedelta(days=1),start-timedelta(days=1))
            result['comparison']={'snapshot_id':baseline['id'],'period_end':baseline['period_end'],'kind':baseline['kind'],'previous_total':old['total'],'previous_completion_rate':old['completion_rate'],'completion_rate_change':round(result['completion_rate']-old['completion_rate'],2) if result['completion_rate'] is not None and old['completion_rate'] is not None else None,'overdue_change':result['overdue_count']-old['overdue_count']}
            result['missing']=[x for x in result['missing'] if '缺少上期期末快照' not in x]
        elif d.get('compare_previous'):result['missing'].append('已请求上期比较，但缺少本周期开始前一天的有效期末快照，未生成比较数字。')
        return result

    def revision(self,c,u,report,b):
        self.host.project(c,u,report['project_id'],{'manager'},True)
        replay=self.host.receipt(c,'derive-report:'+report['id'],b)
        if replay:return replay
        self.host.version(report,b,'current_version')
        require(report['status']=='PUBLISHED','只有当前正式报告可以派生修订','STATE_CONFLICT',409)
        reason=text(b.get('reason'),'修订原因',2000)
        for relation in rows(c,'SELECT r.id,r.status,w.state AS run_state FROM report_relations x JOIN reports r ON r.id=x.child_report_id JOIN runs w ON w.id=r.run_id WHERE x.parent_report_id=? AND x.kind=\'REVISION\'',(report['id'],)):
            require(relation['run_state']=='CANCELLED' or relation['status'] in {'PUBLISHED','SUPERSEDED'},'已有修订草稿，请先继续处理','REVISION_EXISTS',409,{'report_id':relation['id']})
        original=row(c,'SELECT * FROM report_versions WHERE report_id=? AND version=?',(report['id'],report['current_version']))
        data=json.loads(original['data']);parent_run=row(c,'SELECT * FROM runs WHERE id=?',(report['run_id'],));old=json.loads(parent_run['data'])
        rid,report_id=uid('run'),uid('report');version=report['current_version']+1
        run_data={k:old[k] for k in ['period_start','period_end','cutoff_time','versions','document_refs','configuration','statistics_version','milestone_definitions','previous_snapshot','data_source','retrieval_profile'] if k in old}
        run_data.update(mode='HUMAN_REVISION',reviewer_id=u['id'],node_calls=1,tool_calls=0,model_calls=0,tokens=0,cost=None,report_id=report_id,parent_run_id=parent_run['id'],parent_report_id=report['id'],snapshot_hash=old['snapshot_hash'])
        c.execute('INSERT INTO runs VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(rid,report['project_id'],u['id'],parent_run['snapshot_id'],'revision:'+b['event_key'],digest(b),'WAITING_REVIEW','WAITING_REVISION',1,js(run_data),now(),now()))
        data['human_supplement']=True;data['revision_of']={'report_id':report['id'],'version':report['current_version'],'reason':reason}
        c.execute('INSERT INTO reports VALUES(?,?,?,?,?,NULL)',(report_id,rid,report['project_id'],version,'DRAFT'))
        c.execute('INSERT INTO report_versions VALUES(?,?,?,?,?,?,?)',(report_id,version,digest(data),js(data),u['id'],reason,now()))
        self.host.knowledge.attach_sources(c,'report',report_id,data.get('document_refs',[]))
        c.execute('INSERT INTO report_relations VALUES(?,?,?,?,?,?,?)',(report_id,report['id'],report['current_version'],'REVISION',reason,u['id'],now()))
        c.execute('INSERT INTO run_relations VALUES(?,?,?,?)',(rid,parent_run['id'],'REVISION',now()))
        c.execute('INSERT INTO attempts VALUES(?,?,?,?,?,?,?,?)',(uid('attempt'),rid,'DeriveDraft',1,'SUCCEEDED',now(),now(),'从已发布正文派生修订草稿；来源快照与原正式版保留'))
        self.host.event(c,u,report['project_id'],'REPORT_REVISION_DERIVED',report_id,{'parent_report_id':report['id'],'parent_version':report['current_version'],'reason':reason})
        return self.host.save_receipt(c,'derive-report:'+report['id'],b,{'id':report_id,'run_id':rid,'version':version})

    def takeover(self,c,u,run,b):
        self.host.project(c,u,run['project_id'],{'manager'})
        replay=self.host.receipt(c,'takeover:'+run['id'],b)
        if replay:return replay
        self.host.version(run,b)
        require(run['state']=='FAILED' and run['phase']!='PUBLISHING','分析故障可人工接管；批准后的发布故障请恢复发布','STATE_CONFLICT',409)
        reason=text(b.get('reason'),'接管原因',2000)
        narrative=text(b.get('narrative'),'人工接管正文',16000)
        require(set(b)<={'expected_version','event_key','reason','narrative'},'人工接管不能覆盖权限、规则数字或来源')
        snap=row(c,'SELECT * FROM snapshots WHERE id=?',(run['snapshot_id'],));records=json.loads(snap['rows'])
        require(digest(records)==snap['content_hash'],'原始快照不可用，请新建运行','SOURCE_UNAVAILABLE',409)
        self.host.knowledge.assert_refs(c,u,run['data'].get('document_refs',[]))
        existing=c.execute('SELECT * FROM reports WHERE run_id=?',(run['id'],)).fetchone()
        if existing:
            c.execute("UPDATE approvals SET state='VOID',version=version+1 WHERE report_id=? AND state='PENDING'",(existing['id'],))
            current=row(c,'SELECT * FROM report_versions WHERE report_id=? AND version=?',(existing['id'],existing['current_version']))
            output=json.loads(current['data']);output.update(narrative=narrative,human_supplement=True)
            version=existing['current_version']+1
            c.execute('INSERT INTO report_versions VALUES(?,?,?,?,?,?,?)',(existing['id'],version,digest(output),js(output),u['id'],reason,now()))
            c.execute("UPDATE reports SET status='DRAFT',current_version=? WHERE id=?",(version,existing['id']));rid=existing['id']
        else:
            rid=uid('report');m=self.metrics(c,run,records);d=run['data']
            evidence=[{'evidence_id':'E-'+x['task_id'],'snapshot_id':snap['id'],'locator':x['task_id'],'title':x['title'],'row':x,'version':snap['content_hash'][:12]} for x in records]
            output={'title':'项目进度汇总','narrative':narrative,'metrics':m,'risks':[],'evidence':evidence,'missing':m['missing']+['自动分析未完整完成；此稿为人工接管，未生成完整结构化风险清单。'],'snapshot_id':snap['id'],'cutoff_time':d['cutoff_time'],'period_start':d['period_start'],'period_end':d['period_end'],'mode':'HUMAN_TAKEOVER','human_supplement':True,'document_refs':d.get('document_refs',[])}
            c.execute('INSERT INTO reports VALUES(?,?,?,?,?,NULL)',(rid,run['id'],run['project_id'],1,'DRAFT'))
            c.execute('INSERT INTO report_versions VALUES(?,?,?,?,?,?,?)',(rid,1,digest(output),js(output),u['id'],reason,now()))
            self.host.knowledge.attach_sources(c,'report',rid,d.get('document_refs',[]))
        run['data']['mode']='HUMAN_TAKEOVER';run['data']['report_id']=rid;run['data']['node_calls']+=1
        run['data']['takeover_reason']=reason;run['data']['takeover_actor']=u['id'];run['data']['reviewer_id']=u['id']
        if run['data'].get('error'):run['data']['previous_error']=run['data'].pop('error')
        c.execute("UPDATE attempts SET status='CANCELLED',ended_at=?,summary='人工接管，旧等待结束' WHERE run_id=? AND status='WAITING'",(now(),run['id']))
        c.execute('INSERT INTO attempts VALUES(?,?,?,?,?,?,?,?)',(uid('attempt'),run['id'],'ManualTakeover',1,'SUCCEEDED',now(),now(),'人工接管已保存，仍需正常审核发布'))
        self.host.update_run(c,run,'WAITING_REVIEW','WAITING_REVISION')
        self.host.event(c,u,run['project_id'],'RUN_MANUALLY_TAKEN_OVER',run['id'],{'report_id':rid,'reason':reason})
        return self.host.save_receipt(c,'takeover:'+run['id'],b,{'id':rid,'run_id':run['id']})

    def published(self,c,u,r,report):
        relation=c.execute("SELECT * FROM report_relations WHERE child_report_id=? AND kind='REVISION'",(report['id'],)).fetchone()
        if relation:
            parent=row(c,'SELECT * FROM reports WHERE id=?',(relation['parent_report_id'],))
            require(parent['status']=='PUBLISHED' and parent['current_version']==relation['parent_version'],'来源正式版已被其他修订替代，请检查最新版本','VERSION_CONFLICT',409)
            c.execute("UPDATE reports SET status='SUPERSEDED' WHERE id=?",(parent['id'],))
            c.execute('UPDATE report_publications SET superseded_by=? WHERE report_id=?',(report['id'],parent['id']))
            self.host.event(c,u,report['project_id'],'REPORT_SUPERSEDED',parent['id'],{'replacement_report_id':report['id']})
        c.execute('INSERT OR IGNORE INTO report_publications VALUES(?,?,?,?,NULL)',(report['id'],report['current_version'],u['id'],now()))
