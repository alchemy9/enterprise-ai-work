"""Working local demos for read-only integration, schedules and open analysis.

The connector reads an explicit simulated source. Analysis uses evidence and
deterministic planning; no external LLM or enterprise service is implied.
"""
import csv
import io
import json
import re
import secrets
import time
from datetime import datetime,timedelta
from .db import now,today,TZ,uid,js,digest,password_hash
from .domain import BusinessError,require,text,parse_date,validate_csv,compute_metrics,CSV_FIELDS
from .knowledge import row,rows

MAPPING={x:x for x in CSV_FIELDS}
READ_TOOLS={'tool_ledger','tool_rules','tool_knowledge'}


class Advanced:
    def __init__(self,host):
        self.host,self.db=host,host.db
        self.next_check=0

    def managers(self,c,u,pid,active=False):
        return self.host.project(c,u,pid,{'manager'},active)

    def connection(self,c,u,ident,manage=True):
        x=row(c,'SELECT * FROM connections WHERE id=? AND tenant_id=?',(ident,u['tenant_id']))
        self.host.project(c,u,x['project_id'],{'manager'} if manage else None)
        return {**x,'config':json.loads(x['config'])}

    def connection_event(self,c,u,x,action,state,data):
        c.execute('INSERT INTO connection_events VALUES(?,?,?,?,?,?,?)',(uid('connection_event'),x['id'],u['id'],action,state,js(data),now()))
        self.host.event(c,u,x['project_id'],action,x['id'],data)

    def connection_detail(self,c,u,x):
        snapshot=c.execute('SELECT * FROM connection_snapshots WHERE id=?',(x['last_snapshot_id'],)).fetchone()
        return {**x,'snapshot':{**dict(snapshot),'rows':json.loads(snapshot['rows'])} if snapshot else None,'jobs':[{**j,'data':json.loads(j['data'])} for j in rows(c,'SELECT * FROM sync_jobs WHERE connection_id=? ORDER BY rowid DESC LIMIT 20',(x['id'],))],'events':[{**e,'data':json.loads(e['data'])} for e in rows(c,'SELECT * FROM connection_events WHERE connection_id=? ORDER BY rowid DESC LIMIT 30',(x['id'],))]}

    def mapped_source(self,c,u,pid,config):
        mapping=config.get('field_mapping')
        source=config.get('source_rows')
        require(isinstance(mapping,dict) and set(mapping)==set(CSV_FIELDS),'请配置全部标准字段映射')
        require(all(isinstance(v,str) and re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,60}',v) for v in mapping.values()),'字段映射只能使用列名，不能包含代码或路径')
        require(len(set(mapping.values()))==len(mapping),'多个标准字段不能映射到同一源列')
        require(isinstance(source,list) and 0<len(source)<=10000 and all(isinstance(x,dict) for x in source),'模拟源需提供 1～10000 条对象记录')
        require(all(all(mapping[k] in record for k in ['task_id','title','status']) for record in source),'模拟源缺少必填映射列')
        output=io.StringIO();writer=csv.DictWriter(output,fieldnames=CSV_FIELDS);writer.writeheader()
        for record in source:
            require(all(isinstance(record.get(v,''),(str,int,float)) for v in mapping.values()),'源字段必须为字符串或数字')
            writer.writerow({k:record.get(v,'') for k,v in mapping.items()})
        members={x['user_id'] for x in rows(c,'SELECT m.user_id FROM memberships m JOIN users u ON u.id=m.user_id WHERE m.project_id=? AND u.active=1',(pid,))}
        result,errors=validate_csv(output.getvalue(),members)
        require(not errors,'模拟源数据校验失败，请修正后重试','SOURCE_INVALID',400,{'errors':errors[:30]})
        return result

    def config_connection(self,c,u,pid,b):
        config={'mode':'DEMO_READ_ONLY','address':'demo://enterprise-task-ledger','credential_ref':'DEMO_SOURCE_CREDENTIAL','field_mapping':b.get('field_mapping',MAPPING),'source_rows':b.get('source_rows',[]),'sync_minutes':b.get('sync_minutes',0),'credential_state':b.get('credential_state','VALID'),'failure_mode':b.get('failure_mode','NONE')}
        require(config['credential_state'] in {'VALID','EXPIRED','REVOKED'},'凭据演示状态无效')
        require(config['failure_mode'] in {'NONE','NETWORK','SCHEMA'},'故障演示类型无效')
        require(type(config['sync_minutes']) is int and 0<=config['sync_minutes']<=1440,'同步间隔需为 0～1440 分钟，0 表示手动')
        self.mapped_source(c,u,pid,config)
        return config

    def source_for_run(self,c,u,pid,ident):
        x=self.connection(c,u,ident)
        require(x['project_id']==pid,'数据源不属于当前项目','PERMISSION_DENIED',403)
        require(x['state']=='ACTIVE' and x['config']['credential_state']=='VALID','数据源已停用或凭据失效，请重新授权后同步','SOURCE_UNAVAILABLE',409)
        snapshot=row(c,'SELECT * FROM connection_snapshots WHERE id=? AND connection_id=?',(x['last_snapshot_id'],ident))
        require(digest(json.loads(snapshot['rows']))==snapshot['content_hash'],'数据源快照校验失败','SOURCE_UNAVAILABLE',409)
        return json.loads(snapshot['rows']),{'connection_id':ident,'name':x['name'],'snapshot_id':snapshot['id'],'captured_at':snapshot['captured_at'],'watermark':snapshot['watermark'],'mode':'DEMO_READ_ONLY','stale':x['last_success_at'][:10]<today().isoformat()}

    def dispatch(self,c,u,method,path,b,query):
        s=path.strip('/').split('/')[1:]
        if s==['portfolio','demo-project'] and method=='POST':return self.demo_project(c,u)
        if s==['portfolio']:return self.portfolio(c,u,query)
        if len(s)>=3 and s[0]=='projects':
            pid=s[1];self.managers(c,u,pid)
            if s[2]=='connections':
                if method=='GET':
                    return {'items':[{**x,'config':json.loads(x['config'])} for x in rows(c,'SELECT * FROM connections WHERE project_id=? ORDER BY rowid DESC',(pid,))],'sample_rows':[json.loads(x['data']) for x in rows(c,'SELECT data FROM ledger WHERE project_id=? ORDER BY task_id',(pid,))],'field_mapping':MAPPING}
                self.managers(c,u,pid,True)
                config=self.config_connection(c,u,pid,b);ident=uid('connection')
                c.execute('INSERT INTO connections(id,tenant_id,project_id,name,state,config,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)',(ident,u['tenant_id'],pid,text(b.get('name'),'连接名称',100),'ACTIVE',js(config),u['id'],now(),now()))
                x={'id':ident,'project_id':pid};self.connection_event(c,u,x,'CONNECTION_CREATED','ACTIVE',{'mode':'DEMO_READ_ONLY'})
                return {'id':ident}
            if s[2]=='schedules':
                if method=='GET':return {'items':[{**x,'data':json.loads(x['data'])} for x in rows(c,'SELECT s.*,u.name AS execution_name FROM schedules s JOIN users u ON u.id=s.execution_user_id WHERE s.project_id=? ORDER BY s.rowid DESC',(pid,))],'templates':self.host.governance.templates(c,u,pid),'members':rows(c,"SELECT u.id,u.name FROM users u JOIN memberships m ON m.user_id=u.id WHERE m.project_id=? AND u.active=1 AND m.role IN ('manager','reviewer')",(pid,))}
                return self.create_schedule(c,u,pid,b)
            if s[2]=='analyses':
                if method=='GET':
                    found=[]
                    for x in rows(c,'SELECT * FROM analyses WHERE project_id=? ORDER BY rowid DESC',(pid,)):
                        try:self.analysis(c,u,x['id'])
                        except BusinessError:continue
                        data=json.loads(x.pop('data'));found.append({**x,'goal':data['goal'],'period_start':data.get('period_start'),'period_end':data.get('period_end')})
                    return {'items':found,'tasks':[json.loads(x['data']) for x in rows(c,'SELECT data FROM ledger WHERE project_id=? ORDER BY task_id',(pid,))]}
                return self.create_analysis(c,u,pid,b)
        if len(s)>=2 and s[0]=='connections':
            x=self.connection(c,u,s[1]);ident=x['id']
            if method=='GET':return self.connection_detail(c,u,x)
            action=s[2] if len(s)>2 else 'save'
            if action=='sync':
                old=self.host.receipt(c,'connection-sync:'+ident,b)
                if old:return old
                require(x['state']=='ACTIVE','连接已停用','CONFIG_DISABLED',409)
                self.managers(c,u,x['project_id'],True)
                pending=c.execute("SELECT id FROM sync_jobs WHERE connection_id=? AND state='QUEUED'",(ident,)).fetchone()
                jid=pending['id'] if pending else uid('sync')
                if not pending:c.execute('INSERT INTO sync_jobs VALUES(?,?,?,?,?,?,?)',(jid,ident,u['id'],'QUEUED','{}',now(),now()))
                return self.host.save_receipt(c,'connection-sync:'+ident,b,{'id':jid,'connection_id':ident,'state':'QUEUED'})
            self.host.version(x,b)
            if action=='save':
                config=self.config_connection(c,u,x['project_id'],b)
                c.execute('UPDATE connections SET name=?,config=?,version=version+1,updated_at=? WHERE id=?',(text(b.get('name'),'连接名称',100),js(config),now(),ident))
                self.connection_event(c,u,x,'CONNECTION_UPDATED',x['state'],{'credential_state':config['credential_state'],'mode':'DEMO_READ_ONLY'})
            elif action=='test':
                self.connection_available(x)
                mapped=self.mapped_source(c,u,x['project_id'],x['config'])
                self.connection_event(c,u,x,'CONNECTION_TESTED','SUCCEEDED',{'row_count':len(mapped),'read_only':True})
                return {'state':'SUCCEEDED','row_count':len(mapped),'mode':'DEMO_READ_ONLY','message':'本地模拟源字段及读取范围有效，未请求外部服务'}
            elif action=='status':
                require(b.get('state') in {'ACTIVE','DISABLED'},'连接状态无效')
                c.execute('UPDATE connections SET state=?,version=version+1,updated_at=? WHERE id=?',(b['state'],now(),ident))
                self.connection_event(c,u,x,'CONNECTION_STATUS',b['state'],{})
            else:raise BusinessError(404,'NOT_FOUND','连接操作不存在')
            return {'id':ident}
        if len(s)>=2 and s[0]=='schedules':
            schedule=self.schedule(c,u,s[1]);ident=schedule['id']
            if method=='GET':return {**schedule,'fires':[{**f,'data':json.loads(f['data'])} for f in rows(c,'SELECT * FROM schedule_fires WHERE schedule_id=? ORDER BY rowid DESC LIMIT 30',(ident,))]}
            action=s[2] if len(s)>2 else 'save';self.host.version(schedule,b)
            if action=='trigger':
                replay=self.host.receipt(c,'schedule-trigger:'+ident,b)
                if replay:return replay
                require(schedule['state']=='ACTIVE','计划尚未启用，请检查后启用','SCHEDULE_PAUSED',409)
                result=self.fire(c,schedule,'manual:'+text(b.get('event_key'),'触发键',100),'MANUAL',u)
                return self.host.save_receipt(c,'schedule-trigger:'+ident,b,result)
            if action=='status':
                require(b.get('state') in {'ACTIVE','PAUSED'},'计划状态无效')
                if b['state']=='ACTIVE':self.valid_schedule_identity(c,schedule)
                c.execute('UPDATE schedules SET state=?,version=version+1,updated_at=? WHERE id=?',(b['state'],now(),ident))
            elif action=='save':
                data=self.schedule_config(c,u,schedule['project_id'],b)
                c.execute('UPDATE schedules SET data=?,next_at=?,version=version+1,updated_at=? WHERE id=?',(js(data),self.next_time(data),now(),ident))
            else:raise BusinessError(404,'NOT_FOUND','计划操作不存在')
            self.host.event(c,u,schedule['project_id'],'SCHEDULE_UPDATED',ident,{'action':action,'state':b.get('state')})
            return {'id':ident}
        if len(s)>=2 and s[0]=='analyses':return self.analysis_dispatch(c,u,method,s,b)
        raise BusinessError(404,'NOT_FOUND','扩展接口不存在')

    def connection_available(self,x):
        require(x['state']=='ACTIVE','数据连接已停用','CONFIG_DISABLED',409)
        require(x['config']['credential_state']=='VALID','模拟凭据已到期或撤销，请在连接配置中重新授权','CREDENTIAL_EXPIRED',409)
        require(x['config']['failure_mode']!='NETWORK','模拟数据源网络中断；最近有效快照保留','SOURCE_TEMPORARY',503)
        require(x['config']['failure_mode']!='SCHEMA','模拟数据源返回字段不兼容；未切换有效快照','SOURCE_SCHEMA_CHANGED',409)

    def sync_next(self):
        with self.db.tx() as c:
            job=c.execute("SELECT * FROM sync_jobs WHERE state='QUEUED' ORDER BY rowid LIMIT 1").fetchone()
            if not job:return False
            job=dict(job);x=None
            try:
                u=row(c,'SELECT * FROM users WHERE id=? AND active=1',(job['actor_id'],))
                x=self.connection(c,u,job['connection_id']);self.connection_available(x)
                self.managers(c,u,x['project_id'],True)
                source=self.mapped_source(c,u,x['project_id'],x['config'])
                # A simulated incremental feed is deduplicated by its stable task ID.
                old=c.execute('SELECT rows FROM connection_snapshots WHERE id=?',(x['last_snapshot_id'],)).fetchone()
                previous={r['task_id']:r for r in json.loads(old['rows'])} if old else {}
                changed=sum(previous.get(r['task_id'])!=r for r in source)
                watermark=x['watermark']+1;sid=uid('source_snapshot')
                c.execute('INSERT INTO connection_snapshots VALUES(?,?,?,?,?,?)',(sid,x['id'],digest(source),js(source),watermark,now()))
                c.execute('UPDATE connections SET last_snapshot_id=?,last_success_at=?,watermark=?,version=version+1,updated_at=? WHERE id=?',(sid,now(),watermark,now(),x['id']))
                result={'snapshot_id':sid,'row_count':len(source),'changed_count':changed,'watermark':watermark,'mode':'DEMO_READ_ONLY'}
                c.execute("UPDATE sync_jobs SET state='SUCCEEDED',data=?,updated_at=? WHERE id=?",(js(result),now(),job['id']))
                self.connection_event(c,u,x,'CONNECTION_SYNCED','SUCCEEDED',result)
            except BusinessError as exc:
                result={'error':{'code':exc.code,'message':exc.message,'trace_id':job['id']},'retained_snapshot_id':x['last_snapshot_id'] if x else None}
                c.execute("UPDATE sync_jobs SET state='FAILED',data=?,updated_at=? WHERE id=?",(js(result),now(),job['id']))
                if x:self.connection_event(c,u,x,'CONNECTION_SYNC_FAILED','FAILED',result)
            return True

    def schedule_config(self,c,u,pid,b):
        name=text(b.get('name'),'计划名称',100);frequency=b.get('frequency','DAILY')
        require(frequency in {'DAILY','WEEKLY'},'请选择每天或每周')
        at=text(b.get('time'),'执行时间',5)
        require(re.fullmatch(r'([01]\d|2[0-3]):[0-5]\d',at),'执行时间应为 HH:mm')
        weekday=b.get('weekday',0);require(type(weekday) is int and 0<=weekday<=6,'星期无效')
        days=b.get('period_days',7);require(type(days) is int and 1<=days<=90,'统计天数为 1～90 天')
        reviewer=b.get('reviewer_id');self.host.member(c,pid,reviewer,{'manager','reviewer'})
        template=b.get('workflow_id','wf_progress');cfg=self.host.governance.bind(c,u,pid,template)
        strategy=b.get('version_strategy','LATEST');require(strategy in {'LATEST','PINNED'},'模板版本策略无效')
        until=b.get('expires_on') or None
        if until:require(parse_date(until)>=today(),'计划截止日期不能早于今天')
        return {'name':name,'frequency':frequency,'time':at,'weekday':weekday,'timezone':'Asia/Shanghai','period_days':days,'reviewer_id':reviewer,'workflow_id':template,'version_strategy':strategy,'workflow_version':cfg['workflow']['version'],'expires_on':until,'include_documents':b.get('include_documents',True) is True,'read_scope':'CURRENT_PROJECT','auto_approve':False}

    def next_time(self,data,after=None):
        base=after or datetime.now(TZ);hh,mm=map(int,data['time'].split(':'))
        candidate=base.replace(hour=hh,minute=mm,second=0,microsecond=0)
        if data['frequency']=='WEEKLY':candidate+=timedelta(days=(data['weekday']-candidate.weekday())%7)
        if candidate<=base:candidate+=timedelta(days=7 if data['frequency']=='WEEKLY' else 1)
        return candidate.isoformat(timespec='seconds')

    def create_schedule(self,c,u,pid,b):
        self.managers(c,u,pid,True);data=self.schedule_config(c,u,pid,b)
        ident,execution=uid('schedule'),uid('svc_schedule');salt=secrets.token_hex(16)
        c.execute('INSERT INTO users VALUES(?,?,?,?,?,?,1)',(execution,u['tenant_id'],execution,'计划执行 · '+data['name'][:30],salt,password_hash(secrets.token_urlsafe(48),salt)))
        c.execute('INSERT INTO memberships VALUES(?,?,?)',(pid,execution,'service_runner'))
        c.execute('INSERT INTO system_roles VALUES(?,\'[]\',1)',(execution,))
        c.execute('INSERT INTO schedules(id,tenant_id,project_id,created_by,execution_user_id,state,data,next_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)',(ident,u['tenant_id'],pid,u['id'],execution,'ACTIVE',js(data),self.next_time(data),now(),now()))
        self.host.event(c,u,pid,'SCHEDULE_CREATED',ident,{'execution_user_id':execution,'reviewer_id':data['reviewer_id'],'draft_only':True})
        return {'id':ident}

    def schedule(self,c,u,ident):
        x=row(c,'SELECT * FROM schedules WHERE id=? AND tenant_id=?',(ident,u['tenant_id']));self.managers(c,u,x['project_id'])
        return {**x,'data':json.loads(x['data'])}

    def valid_schedule_identity(self,c,s):
        creator=row(c,'SELECT * FROM users WHERE id=? AND active=1',(s['created_by'],));self.managers(c,creator,s['project_id'],True)
        execution=row(c,'SELECT * FROM users WHERE id=? AND active=1',(s['execution_user_id'],));self.host.project(c,execution,s['project_id'],{'service_runner'},True)
        self.host.member(c,s['project_id'],s['data']['reviewer_id'],{'manager','reviewer'})
        return execution

    def fire(self,c,s,scheduled_at,trigger_type,actor=None):
        old=c.execute('SELECT * FROM schedule_fires WHERE schedule_id=? AND scheduled_at=?',(s['id'],scheduled_at)).fetchone()
        if old:return dict(old)
        ident=uid('fire');state='SKIPPED';rid=None;result={}
        data=s['data']
        try:
            execution=self.valid_schedule_identity(c,s)
            require(not data.get('expires_on') or data['expires_on']>=today().isoformat(),'计划已到截止日期','SCHEDULE_EXPIRED',409)
            previous=c.execute("SELECT f.run_id FROM schedule_fires f JOIN runs r ON r.id=f.run_id WHERE f.schedule_id=? AND r.state NOT IN ('COMPLETED','CANCELLED','FAILED') LIMIT 1",(s['id'],)).fetchone()
            if previous:result={'reason':'上一次运行仍在执行或等待审核，本次跳过','previous_run_id':previous['run_id']}
            else:
                body={'project_id':s['project_id'],'submission_key':s['id']+':'+scheduled_at,'period_start':(today()-timedelta(days=data['period_days']-1)).isoformat(),'period_end':today().isoformat(),'reviewer_id':data['reviewer_id'],'acknowledge_gaps':True,'include_documents':data['include_documents'],'workflow_id':data['workflow_id']}
                if data['version_strategy']=='PINNED':body['workflow_version']=data['workflow_version']
                created=self.host.start_run(c,execution,body,scheduled=True);rid=created['id'];state='CREATED'
                run=row(c,'SELECT data FROM runs WHERE id=?',(rid,));rd=json.loads(run['data']);rd['schedule_id']=s['id'];rd['scheduled_at']=scheduled_at;rd['initiated_by']=s['created_by']
                c.execute('UPDATE runs SET data=? WHERE id=?',(js(rd),rid))
                result={'mode':'DRAFT_ONLY','delayed':trigger_type=='TIMER' and datetime.fromisoformat(scheduled_at)<datetime.now(TZ)-timedelta(minutes=1),'execution_user_id':execution['id']}
        except BusinessError as exc:
            state='PAUSED';result={'error':{'code':exc.code,'message':exc.message},'reason':'身份、授权或配置不可用；计划已暂停，需人工检查'}
            c.execute("UPDATE schedules SET state='PAUSED',version=version+1,updated_at=? WHERE id=?",(now(),s['id']))
        c.execute('INSERT INTO schedule_fires VALUES(?,?,?,?,?,?,?,?)',(ident,s['id'],scheduled_at,trigger_type,state,rid,js(result),now()))
        creator=row(c,'SELECT * FROM users WHERE id=?',(s['created_by'],))
        self.host.event(c,actor or creator,s['project_id'],'SCHEDULE_TRIGGERED',s['id'],{'state':state,'run_id':rid,**result})
        return {'id':ident,'state':state,'run_id':rid,'data':result}

    def tick(self):
        # Polling does no network I/O. Timers are durable and use the service timezone.
        if time.monotonic()<self.next_check:return False
        self.next_check=time.monotonic()+5
        with self.db.tx() as c:
            for raw in rows(c,"SELECT * FROM schedules WHERE state='ACTIVE' AND next_at<=? ORDER BY next_at LIMIT 10",(now(),)):
                s={**raw,'data':json.loads(raw['data'])}
                # After an offline period only the latest due slot is caught up.
                future=datetime.fromisoformat(self.next_time(s['data']))
                slot=future-timedelta(days=7 if s['data']['frequency']=='WEEKLY' else 1)
                self.fire(c,s,slot.isoformat(timespec='seconds'),'TIMER')
                c.execute('UPDATE schedules SET next_at=? WHERE id=?',(future.isoformat(timespec='seconds'),s['id']))
            for raw in rows(c,"SELECT * FROM connections WHERE state='ACTIVE'"):
                cfg=json.loads(raw['config']);minutes=cfg['sync_minutes']
                if not minutes or cfg['credential_state']!='VALID':continue
                last=raw['last_success_at']
                recent=c.execute('SELECT created_at FROM sync_jobs WHERE connection_id=? ORDER BY rowid DESC LIMIT 1',(raw['id'],)).fetchone()
                stamp=max([x for x in [last,recent['created_at'] if recent else None] if x],default=raw['created_at'])
                if datetime.now(TZ)-datetime.fromisoformat(stamp)<timedelta(minutes=minutes):continue
                c.execute('INSERT INTO sync_jobs VALUES(?,?,?,?,?,?,?)',(uid('sync'),raw['id'],raw['created_by'],'QUEUED','{}',now(),now()))
        return False

    def analysis(self,c,u,ident):
        a=row(c,'SELECT * FROM analyses WHERE id=? AND tenant_id=?',(ident,u['tenant_id']));self.managers(c,u,a['project_id'])
        data=json.loads(a['data']);self.host.knowledge.assert_refs(c,u,data.get('document_refs',[]))
        return {**a,'data':data}

    def plan(self,c,u,a,data):
        pid=a['project_id'];self.managers(c,u,pid,True)
        for task in data.get('task_ids',[]):row(c,'SELECT task_id FROM ledger WHERE project_id=? AND task_id=?',(pid,task))
        configuration=self.host.governance.bind(c,u,pid)
        allowed=set(configuration['agent']['data']['tools'])&READ_TOOLS
        require({'tool_ledger','tool_rules'}<=allowed,'分析需要台账读取与规则计算工具','TOOL_DENIED',403)
        steps=[{'tool':'tool_ledger','title':'核对任务当前事实','scope':data.get('task_ids',[]) or ['当前项目台账'],'required':True},{'tool':'tool_rules','title':'计算逾期与数据缺口','scope':['当前项目快照'],'required':True}]
        if data.get('include_documents',True) and 'tool_knowledge' in allowed:steps.append({'tool':'tool_knowledge','title':'查找原因线索与验收依据','scope':['当前授权项目资料'],'required':False})
        version=c.execute('SELECT coalesce(max(version),0)+1 FROM analysis_plans WHERE analysis_id=?',(a['id'],)).fetchone()[0]
        plan={'goal':data['goal'],'project_id':pid,'period_start':data['period_start'],'period_end':data['period_end'],'task_ids':data.get('task_ids',[]),'steps':steps,'budget':{'tool_calls':8,'iterations':3,'active_seconds':300},'expected_result':'事实、原因假设、相反证据或缺口、建议验证动作','risk':'只读分析，不创建或修改业务任务','model_mode':'DEMO_RULES','estimated_tokens':'未调用外部模型','configuration':configuration}
        c.execute('INSERT INTO analysis_plans VALUES(?,?,?,?,?)',(a['id'],version,digest(plan),js(plan),now()))
        data['plan_version']=version;data['plan_hash']=digest(plan)
        return data

    def create_analysis(self,c,u,pid,b):
        self.managers(c,u,pid,True)
        key=text(b.get('submission_key'),'提交键',200)
        old=c.execute('SELECT * FROM analyses WHERE project_id=? AND actor_id=? AND submission_key=?',(pid,u['id'],key)).fetchone()
        if old:
            require(old['request_hash']==digest(b),'提交键参数已变化','IDEMPOTENCY_CONFLICT',409);return {'id':old['id']}
        self.host.governance.check_capacity(c,u)
        goal=text(b.get('goal'),'分析目标',2000)
        require(not any(x in goal for x in ['自动付款','批准合同','发送外部消息','删除全部']),'当前入口仅支持有证据的只读风险分析，业务动作请使用相应确认流程')
        data={'goal':goal,'period_start':b.get('period_start'),'period_end':b.get('period_end'),'task_ids':b.get('task_ids',[]),'include_documents':b.get('include_documents',True) is True,'clarification_rounds':0,'tool_calls':0,'iterations':0,'active_seconds':0,'facts':[],'hypotheses':[],'missing_information':[]}
        require(isinstance(data['task_ids'],list) and len(data['task_ids'])<=50 and all(isinstance(x,str) for x in data['task_ids']),'关注任务无效')
        if data['period_start']:parse_date(data['period_start'])
        if data['period_end']:parse_date(data['period_end'])
        if data['period_start'] and data['period_end']:require(data['period_start']<=data['period_end']<=today().isoformat(),'分析周期无效')
        state='AWAITING_PLAN' if data['period_start'] and data['period_end'] else 'NEEDS_CLARIFICATION'
        ident=uid('analysis')
        c.execute('INSERT INTO analyses VALUES(?,?,?,?,?,?,?,?,?,?,?)',(ident,u['tenant_id'],pid,u['id'],key,digest(b),state,1,js(data),now(),now()))
        if state=='AWAITING_PLAN':
            data=self.plan(c,u,{'id':ident,'project_id':pid},data);c.execute('UPDATE analyses SET data=? WHERE id=?',(js(data),ident))
        self.host.event(c,u,pid,'ANALYSIS_CREATED',ident,{'state':state})
        return {'id':ident,'state':state}

    def analysis_dispatch(self,c,u,method,s,b):
        a=self.analysis(c,u,s[1]);data=a['data'];ident=a['id']
        if method=='GET':
            plans=[{**p,'data':self.host.governance.public_data(c,u,json.loads(p['data']))} for p in rows(c,'SELECT * FROM analysis_plans WHERE analysis_id=? ORDER BY version DESC',(ident,))]
            return {**a,'plans':plans,'steps':[{**x,'params':json.loads(x['params']),'result':json.loads(x['result'])} for x in rows(c,'SELECT * FROM analysis_steps WHERE analysis_id=? ORDER BY ordinal',(ident,))],'events':self.host.history(c,ident)}
        require(len(s)==3,'分析操作不存在','NOT_FOUND',404)
        replay=self.host.receipt(c,'analysis:'+ident,b)
        if replay:return replay
        self.host.version(a,b);action=s[2]
        if action in {'clarify','revise'}:
            require(a['state'] in {'NEEDS_CLARIFICATION','AWAITING_PLAN'},'执行后修改目标或范围请新建分析','STATE_CONFLICT',409)
            if action=='clarify':
                require(data['clarification_rounds']<2,'已达到两轮澄清上限，请重新填写目标并新建分析','CLARIFICATION_LIMIT',409)
                data['clarification_rounds']+=1
            for k in ['goal','period_start','period_end','include_documents','task_ids']:
                if k in b:data[k]=b[k]
            data['goal']=text(data['goal'],'分析目标',2000)
            require(isinstance(data['task_ids'],list) and len(data['task_ids'])<=50 and all(isinstance(x,str) for x in data['task_ids']),'关注任务无效')
            require(type(data['include_documents']) is bool,'资料范围无效')
            if data.get('period_start') and data.get('period_end'):
                start,end=parse_date(data['period_start']),parse_date(data['period_end']);require(start<=end<=today(),'分析周期无效')
                data=self.plan(c,u,a,data);state='AWAITING_PLAN'
            else:state='STOPPED' if data['clarification_rounds']>=2 else 'NEEDS_CLARIFICATION'
        elif action=='confirm':
            require(a['state']=='AWAITING_PLAN','当前没有待确认计划','STATE_CONFLICT',409)
            require(b.get('confirmed') is True and b.get('plan_version')==data['plan_version'] and b.get('plan_hash')==data['plan_hash'],'计划版本或参数已变化，请重新核对','VERSION_CONFLICT',409)
            plan=row(c,'SELECT * FROM analysis_plans WHERE analysis_id=? AND version=?',(ident,data['plan_version']))
            require(digest(json.loads(plan['data']))==data['plan_hash'],'计划摘要不匹配')
            ledger=[json.loads(x['data']) for x in rows(c,'SELECT data FROM ledger WHERE project_id=? ORDER BY task_id',(a['project_id'],))]
            sid=uid('snap');stamp=now();c.execute('INSERT INTO snapshots VALUES(?,?,?,?,?)',(sid,a['project_id'],stamp,digest(ledger),js(ledger)))
            data['snapshot_id']=sid;data['cutoff_time']=stamp;data['document_refs']=self.host.knowledge.available_refs(c,u,a['project_id']) if data['include_documents'] else []
            data['retrieval_profile']=self.host.sources.profile(c,a['project_id'])
            data['confirmed_by']=u['id'];data['confirmed_at']=stamp;data['evidence']=[];state='QUEUED'
        elif action=='cancel':
            require(a['state'] not in {'COMPLETED','CANCELLED'},'当前分析已结束','STATE_CONFLICT',409)
            data['cancel_reason']=text(b.get('reason'),'取消原因',1000);state='CANCELLED'
        else:raise BusinessError(404,'NOT_FOUND','分析操作不存在')
        c.execute('UPDATE analyses SET state=?,version=version+1,data=?,updated_at=? WHERE id=?',(state,js(data),now(),ident))
        self.host.event(c,u,a['project_id'],'ANALYSIS_'+action.upper(),ident,{'state':state,'plan_version':data.get('plan_version')})
        return self.host.save_receipt(c,'analysis:'+ident,b,{'id':ident,'state':state})

    def analysis_next(self):
        with self.db.tx() as c:
            raw=c.execute("SELECT * FROM analyses WHERE state IN ('QUEUED','RUNNING') ORDER BY rowid LIMIT 1").fetchone()
            if not raw:return False
            a=dict(raw);data=json.loads(a['data']);started=time.monotonic()
            try:
                u=row(c,'SELECT * FROM users WHERE id=? AND active=1',(a['actor_id'],));self.managers(c,u,a['project_id'])
                self.host.knowledge.assert_refs(c,u,data.get('document_refs',[]))
                plan=json.loads(row(c,'SELECT data FROM analysis_plans WHERE analysis_id=? AND version=?',(a['id'],data['plan_version']))['data'])
                steps=rows(c,'SELECT ordinal FROM analysis_steps WHERE analysis_id=?',(a['id'],));number=len(steps)
                require(data['tool_calls']<plan['budget']['tool_calls'] and data['iterations']<plan['budget']['iterations'] and data['active_seconds']<plan['budget']['active_seconds'],'分析预算已达到上限，部分结果已保留','BUDGET_EXCEEDED',409)
                selected=plan['steps'][number];tool=selected['tool'];require(tool in READ_TOOLS,'分析不允许写工具','TOOL_DENIED',403)
                self.host.governance.published(c,u['tenant_id'],tool)
                require(tool in plan['configuration']['agent']['data']['tools'],'工具不在已确认计划授权中','TOOL_DENIED',403)
                snap=row(c,'SELECT * FROM snapshots WHERE id=?',(data['snapshot_id'],));ledger=json.loads(snap['rows'])
                require(digest(ledger)==snap['content_hash'],'冻结快照不可用','SOURCE_UNAVAILABLE',409)
                target=[x for x in ledger if not data['task_ids'] or x['task_id'] in data['task_ids']]
                data['tool_calls']+=1;data['iterations']+=1
                stamp=now();result={}
                if tool=='tool_ledger':
                    data['evidence']=[{'evidence_id':'A-'+a['id']+'-'+x['task_id'],'kind':'LEDGER','title':x['title'],'task_id':x['task_id'],'row':x,'snapshot_id':snap['id'],'locator':x['task_id']} for x in target]
                    result={'task_count':len(target),'snapshot_id':snap['id'],'scope':'所选任务当前状态，非历史还原'}
                elif tool=='tool_rules':
                    metrics=compute_metrics(target,datetime.fromisoformat(data['cutoff_time']).date(),parse_date(data['period_start']),parse_date(data['period_end']));data['metrics']=metrics
                    data['facts']=[{'text':f"任务 {x['task_id']} 在数据截点为 {x['status']}，计划截止 {x['due_date'] or '未提供'}。",'evidence_ids':['A-'+a['id']+'-'+x['task_id']]} for x in target]
                    result={'overdue_count':metrics['overdue_count'],'completion_rate':metrics['completion_rate']}
                else:
                    query=' '.join([data['goal']]+data['task_ids'])
                    evidence=self.host.knowledge.evidence(c,u,data['document_refs'],query,limit=6,profile=data.get('retrieval_profile'))
                    data['evidence']+=evidence;result={'evidence_count':len(evidence),'retrieval_status':'FOUND' if evidence else 'EMPTY','mode':'LOCAL_TEXT'}
                c.execute('INSERT INTO analysis_steps VALUES(?,?,?,?,?,?,?,?,?)',(uid('analysis_step'),a['id'],number+1,tool,'SUCCEEDED',js({'task_ids':data['task_ids'],'project_id':a['project_id']}),js(result),stamp,now()))
                c.execute('INSERT INTO tool_invocations VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(uid('call'),u['tenant_id'],a['project_id'],u['id'],None,tool,plan['configuration']['tools'][tool]['version'],'OpenAnalysis',digest({'analysis_id':a['id'],'ordinal':number+1}),'SUCCEEDED',js(result)[:500],a['id']+':'+str(number+1),a['id'],now()))
                state='RUNNING'
                if number+1==len(plan['steps']):
                    self.finish_analysis(data);state='COMPLETED'
                    used=self.host.sources.evidence_refs(data['evidence']);self.host.knowledge.attach_sources(c,'analysis',a['id'],used)
                    self.host.event(c,u,a['project_id'],'ANALYSIS_COMPLETED',a['id'],{'tool_calls':data['tool_calls'],'mode':'DEMO_RULES'})
                data['active_seconds']=round(data['active_seconds']+time.monotonic()-started,4)
            except BusinessError as exc:
                state='PARTIAL' if data.get('facts') else 'FAILED';data['error']={'code':exc.code,'message':exc.message,'trace_id':a['id']}
                if state=='PARTIAL':
                    self.finish_analysis(data);data['stop_reason']='分析未完整完成：'+exc.message+'。已获得的规则事实和证据保留。'
                self.host.event(c,{'id':a['actor_id']},a['project_id'],'ANALYSIS_FAILED',a['id'],{'state':state,'error_code':exc.code})
            c.execute('UPDATE analyses SET state=?,version=version+1,data=?,updated_at=? WHERE id=?',(state,js(data),now(),a['id']))
            return True

    def finish_analysis(self,data):
        documents=[x for x in data['evidence'] if x.get('kind')=='DOCUMENT'];data['hypotheses']=[]
        for task in data.get('metrics',{}).get('overdue_tasks',[]):
            matched=[x for x in documents if task['task_id'] in x['text']]
            data['hypotheses'].append({'risk_id':'AR-'+task['task_id'],'task_id':task['task_id'],'title':task['title'],'hypothesis':('资料线索：'+matched[0]['text'][:450]) if matched else '无法确认延期原因，当前授权资料未提供与该任务直接对应的原因证据。','supporting_evidence_ids':[x['evidence_id'] for x in matched],'counter_evidence':[],'missing_information':['缺少负责人确认及恢复计划','尚不能排除资源、依赖或数据更新滞后的替代解释'],'validation_action':'与负责人核对阻塞事项和恢复日期，补充可定位证据，再决定是否创建整改。'})
        data['missing_information']=['本地规则与关键词摘录演示，原因假设未被认定为根因。','台账为当前采集状态；选定周期仅用于完成统计，不还原缺失的历史状态。']
        if not documents:data['missing_information'].append('未找到可支持原因分析的文档证据，请补充会议纪要或依赖说明。')
        data['summary']=f"已核对 {len(data['facts'])} 项任务事实，发现 {len(data['hypotheses'])} 项未完成逾期；建议逐项补充原因与处理依据。"
        data['stop_reason']='计划内读取已完成；证据不足项明确保留缺口，不扩大资料或工具范围。'

    def portfolio(self,c,u,query):
        projects=[];cutoff=today()
        for p in rows(c,'SELECT p.*,m.role FROM projects p JOIN memberships m ON m.project_id=p.id WHERE p.tenant_id=? AND m.user_id=? ORDER BY p.rowid',(u['tenant_id'],u['id'])):
            ledger=[json.loads(x['data']) for x in rows(c,'SELECT data FROM ledger WHERE project_id=?',(p['id'],))]
            metrics=compute_metrics(ledger,cutoff,cutoff-timedelta(days=6),cutoff)
            fixes=self.host.list_fixes(c,p['id']);fixes=[x for x in fixes if self.host.knowledge.output_allowed(c,u,'report',x['report_id'])]
            reports=[]
            for r in rows(c,"SELECT r.*,w.created_at FROM reports r JOIN runs w ON w.id=r.run_id WHERE r.project_id=? AND r.status IN ('PUBLISHED','SUPERSEDED') ORDER BY w.rowid DESC",(p['id'],)):
                if self.host.knowledge.output_allowed(c,u,'report',r['id']):reports.append(r)
            trend=[]
            for r in list(reversed(reports[:8])):
                report=json.loads(row(c,'SELECT data FROM report_versions WHERE report_id=? AND version=?',(r['id'],r['current_version']))['data'])
                trend.append({'report_id':r['id'],'cutoff_time':report['cutoff_time'],'completion_rate':report['metrics']['completion_rate'],'overdue_count':report['metrics']['overdue_count']})
            projects.append({'project':p,'metrics':metrics,'open_fixes':sum(x['state'] not in {'ACCEPTED','CANCELLED'} for x in fixes),'accepted_fixes':sum(x['state']=='ACCEPTED' for x in fixes),'published_reports':len(reports),'trend':trend,'updated_at':max((x.get('updated_at','') for x in ledger),default=None)})
        return {'items':projects,'cutoff':cutoff.isoformat(),'period_start':(cutoff-timedelta(days=6)).isoformat(),'totals':{'projects':len(projects),'tasks':sum(x['metrics']['total'] for x in projects),'completed':sum(x['metrics']['completed'] for x in projects),'overdue':sum(x['metrics']['overdue_count'] for x in projects),'open_fixes':sum(x['open_fixes'] for x in projects)},'trend_note':'趋势仅使用当前仍有访问权的已发布报告；没有历史记录时不生成模拟曲线。'}

    def demo_project(self,c,u):
        self.host.platform.authorize(c,u)
        existing=c.execute("SELECT id FROM projects WHERE tenant_id=? AND code='DEMO-CS-002'",(u['tenant_id'],)).fetchone()
        if existing:
            self.host.project(c,u,existing['id'])
            return {'id':existing['id'],'state':'EXISTS'}
        ident=uid('project')
        c.execute('INSERT INTO projects(id,tenant_id,name,code,description) VALUES(?,?,?,?,?)',(ident,u['tenant_id'],'客户服务中心 · 二期交付','DEMO-CS-002','跨项目演示使用的虚构项目，不包含真实客户数据。'))
        c.execute('INSERT INTO memberships VALUES(?,?,?)',(ident,u['id'],'manager'))
        owner=u['id']
        for username,role in [('owner','member'),('reviewer','reviewer')]:
            person=c.execute('SELECT id FROM users WHERE username=? AND tenant_id=? AND active=1',(username,u['tenant_id'])).fetchone()
            if person and person['id']!=u['id']:
                c.execute('INSERT INTO memberships VALUES(?,?,?)',(ident,person['id'],role))
                if username=='owner':owner=person['id']
        c.execute('INSERT INTO knowledge_libraries VALUES(?,?,?,?,?)',(uid('lib'),ident,'项目资料','模拟客户服务项目资料',now()))
        d=today()
        names=['服务流程调研','工单字段梳理','权限模型确认','客户标签导入方案','响应时效规则确认','工单分派联调','知识检索验收','试点培训与交付']
        for i,name in enumerate(names,1):
            task={'task_id':f'CS-{i:03}','title':name,'owner_id':owner,'status':'DONE' if i<=5 else 'IN_PROGRESS' if i<=7 else 'TODO','planned_start':(d-timedelta(days=14)).isoformat(),'due_date':(d+timedelta(days=-2 if i==6 else 2 if i>=7 else -3)).isoformat(),'completed_at':(d-timedelta(days=4)).isoformat() if i<=5 else '','milestone_id':'','updated_at':now()}
            c.execute('INSERT INTO ledger VALUES(?,?,?)',(ident,task['task_id'],js(task)))
        c.execute('INSERT INTO project_settings VALUES(?,?)',(ident,js({'timezone':'Asia/Shanghai','planned_start':(d-timedelta(days=14)).isoformat(),'planned_end':(d+timedelta(days=10)).isoformat()})))
        self.host.event(c,u,ident,'DEMO_PROJECT_CREATED',ident,{'fictional':True,'task_count':8})
        return {'id':ident,'state':'CREATED'}

    def process_next(self):
        self.tick()
        return self.sync_next() or self.analysis_next()
