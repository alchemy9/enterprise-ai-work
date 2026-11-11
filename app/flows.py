"""Bounded read-only DAGs: genuine parallel reads, explicit joins and review.

All analysis views are deterministic demo functions. There is no arbitrary code,
network adapter, LLM call, business write node or implicit credential access.
"""
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta
from .db import uid,js,digest,now,today
from .domain import require,text,parse_date,compute_metrics,BusinessError
from .knowledge import row,rows

TYPES={'START','LEDGER','RULES','KNOWLEDGE','RISK','ACCEPTANCE','SUBFLOW','JOIN','REVIEW','END'}
TOOLS={'LEDGER':'tool_ledger','RULES':'tool_rules','KNOWLEDGE':'tool_knowledge'}
TERMINAL={'SUCCEEDED','FAILED','SKIPPED'}


def node(ident,kind,title,deps,x,y,config=None):
    return {'id':ident,'type':kind,'title':title,'deps':deps,'x':x,'y':y,'config':config or {}}


class Flows:
    def __init__(self,host):
        self.host,self.db=host,host.db
        with self.db.tx() as c:
            if not c.execute("SELECT 1 FROM users WHERE id='u_manager'").fetchone():return
            child={'scope':'CURRENT_PROJECT','nodes':[node('start','START','继承父流程范围',[],30,110),node('evidence','KNOWLEDGE','检索验收依据',['start'],260,110,{'query':'验收标准 处理证据'}),node('accept','ACCEPTANCE','核对验收证据',['evidence'],490,110),node('end','END','返回核对结果',['accept'],720,110)]}
            main={'scope':'CURRENT_PROJECT','nodes':[node('start','START','开始',[],20,180),node('ledger','LEDGER','读取冻结台账',['start'],230,40),node('knowledge','KNOWLEDGE','检索风险线索',['start'],230,190),node('rules','RULES','计算规则数字',['ledger'],450,40),node('risk','RISK','进度风险视角',['rules','knowledge'],670,100),node('sub','SUBFLOW','验收核对子流程',['start'],450,340,{'flow_id':'flow_demo_check','version':1}),node('join','JOIN','汇合独立结果',['risk','sub'],890,190,{'policy':'ALL_SUCCESS'}),node('review','REVIEW','人工确认成果',['join'],1110,190),node('end','END','完成归档',['review'],1330,190)]}
            for ident,name,purpose,graph in [('flow_demo_check','验收资料核对 · 子流程','SUBFLOW',child),('flow_demo_main','进度与验收 · 并行核对','TOP_LEVEL',main)]:
                if c.execute('SELECT 1 FROM flow_definitions WHERE id=?',(ident,)).fetchone():continue
                c.execute('INSERT INTO flow_definitions VALUES(?,?,?,?,1,1,1,?,?,?)',(ident,'tenant_demo',name,purpose,'u_manager',now(),now()))
                c.execute('INSERT INTO flow_versions VALUES(?,1,\'PUBLISHED\',1,?,?,?,?,?)',(ident,digest(graph),js(graph),'内置只读编排演示，未调用模型','u_manager',now()))

    def definition(self,c,u,ident):
        return row(c,'SELECT * FROM flow_definitions WHERE id=? AND tenant_id=?',(ident,u['tenant_id']))

    def published(self,c,tid,ident,version=None,new=True):
        require(version is None or type(version) is int and version>0,'流程版本必须为正整数')
        d=row(c,'SELECT * FROM flow_definitions WHERE id=? AND tenant_id=?',(ident,tid))
        require(not new or d['enabled'],'流程已停用，不接受新任务','CONFIG_DISABLED',409)
        v=row(c,"SELECT * FROM flow_versions WHERE flow_id=? AND version=? AND state='PUBLISHED'",(ident,version or d['active_version']))
        return d,{**v,'data':json.loads(v['data'])}

    def validate(self,c,u,d,graph,depth=0,chain=()):
        require(isinstance(graph,dict) and set(graph)=={'scope','nodes'} and graph['scope']=='CURRENT_PROJECT','流程只能继承当前项目授权范围')
        nodes=graph['nodes'];require(isinstance(nodes,list) and 3<=len(nodes)<=16,'流程须有 3～16 个节点')
        require(all(isinstance(n,dict) and set(n)=={'id','type','title','deps','x','y','config'} for n in nodes),'节点字段不完整或包含未知字段')
        ids=[n['id'] for n in nodes];require(all(isinstance(x,str) and re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,30}',x) for x in ids) and len(ids)==len(set(ids)),'节点 ID 必须唯一，且仅含字母、数字和 _-')
        by_id={n['id']:n for n in nodes}
        for n in nodes:
            require(isinstance(n['type'],str) and n['type'] in TYPES,'不支持该节点；编排演示不开放写入、外发或代码执行')
            text(n['title'],'节点名称',60)
            require(type(n['x']) in {int,float} and type(n['y']) in {int,float} and 0<=n['x']<=4000 and 0<=n['y']<=2000,'节点位置超出画布范围')
            require(isinstance(n['deps'],list) and all(isinstance(x,str) for x in n['deps']) and len(n['deps'])==len(set(n['deps'])) and all(x in by_id and x!=n['id'] for x in n['deps']),'上游节点不存在、重复或引用自身')
            require(isinstance(n['config'],dict),'节点配置无效')
            if n['type']=='JOIN':require(set(n['config'])=={'policy'} and n['config']['policy'] in {'ALL_SUCCESS','ALLOW_PARTIAL'} and len(n['deps'])>=2,'汇合节点须选择全部成功或允许部分结果，并至少有两个上游')
            elif n['type']=='KNOWLEDGE':
                require(set(n['config'])<={'query'},'检索节点不接受项目或权限覆盖参数')
                require(isinstance(n['config'].get('query',''),str) and len(n['config'].get('query',''))<=2000,'检索问题最多 2000 字')
            elif n['type']=='SUBFLOW':
                require(set(n['config'])=={'flow_id','version'} and type(n['config']['version']) is int,'子流程需绑定明确发布版本')
                require(depth<2 and n['config']['flow_id'] not in chain+(d['id'],),'子流程嵌套超过两层或存在循环')
                child,version=self.published(c,u['tenant_id'],n['config']['flow_id'],n['config']['version'])
                require(child['purpose']=='SUBFLOW','只能引用已发布的子流程定义')
                self.validate(c,u,child,version['data'],depth+1,chain+(d['id'],))
            else:require(not n['config'],'此节点没有可编辑执行参数')
        starts=[n for n in nodes if n['type']=='START'];ends=[n for n in nodes if n['type']=='END'];reviews=[n for n in nodes if n['type']=='REVIEW']
        require(len(starts)==len(ends)==1 and not starts[0]['deps'],'必须有唯一开始和结束节点，开始节点不能有上游')
        require(len(reviews)==(1 if d['purpose']=='TOP_LEVEL' else 0),'主流程必须且只能有一个人工确认；子流程的人工确认由父流程承担')
        def ancestors(ident,path=()):
            require(ident not in path,'节点连线存在循环，不能发布')
            result=set()
            for upstream in by_id[ident]['deps']:result|={upstream}|ancestors(upstream,path+(ident,))
            return result
        ancestors_by_id={ident:ancestors(ident) for ident in ids}
        for n in nodes:
            if n['type']!='START':require(starts[0]['id'] in ancestors_by_id[n['id']],'存在未连接到开始节点的分支')
            require(n['id']==ends[0]['id'] or n['id'] in ancestors_by_id[ends[0]['id']],'节点没有连到结束节点')
            upstream_types={by_id[k]['type'] for k in ancestors_by_id[n['id']]}
            direct_types={by_id[k]['type'] for k in n['deps']}
            if n['type']=='RULES':require('LEDGER' in direct_types,'规则统计需要直接连接台账节点')
            if n['type']=='RISK':require('RULES' in direct_types,'风险视角需要直接连接规则数字')
            if n['type']=='ACCEPTANCE':require('KNOWLEDGE' in direct_types,'验收视角需要直接连接文档证据')
        if reviews:
            review=reviews[0]
            require(review['id'] in ancestors_by_id[ends[0]['id']],'结束节点不能绕过人工确认')
            require(all(n['type'] in {'START','REVIEW','END'} or n['id'] in ancestors_by_id[review['id']] for n in nodes),'读取和分析必须在人工确认前完成')
        return {'checks':['节点契约有效','连线无环且全部可达','结果按节点隔离，汇合策略明确','当前项目与工具授权不扩大','主流程人工确认不能绕过'],'node_count':len(nodes),'mode':'READ_ONLY_DEMO'}

    def run(self,c,u,ident):
        r=row(c,'SELECT * FROM flow_runs WHERE id=? AND tenant_id=?',(ident,u['tenant_id']))
        self.host.project(c,u,r['project_id'],{'manager','reviewer'})
        r['data']=json.loads(r['data']);self.host.knowledge.assert_refs(c,u,r['data']['document_refs'])
        return r

    def dispatch(self,c,u,method,path,b,query):
        s=path.strip('/').split('/')[1:]
        if s==['flows'] and method=='GET':
            return {'items':rows(c,'SELECT * FROM flow_definitions WHERE tenant_id=? ORDER BY rowid DESC',(u['tenant_id'],)),'types':sorted(TYPES),'can_edit':'operations' in self.host.platform.roles(c,u)}
        if s[:1]==['flow-runs']:
            r=self.run(c,u,s[1]);data=r['data']
            if method=='GET':return {**r,'attempts':[{**a,'data':json.loads(a['data'])} for a in rows(c,'SELECT * FROM flow_attempts WHERE run_id=? ORDER BY rowid',(r['id'],))],'calls':rows(c,'SELECT tool_id,tool_version,node,state,summary,created_at FROM tool_invocations WHERE run_id=? ORDER BY rowid',(r['id'],))}
            replay=self.host.receipt(c,'flow-run:'+r['id'],b)
            if replay:return replay
            self.host.version(r,b);action=s[2]
            if action=='transfer':
                self.host.project(c,u,r['project_id'],{'manager'})
                require(r['state']=='WAITING_REVIEW','仅待确认成果可转交','STATE_CONFLICT',409)
                self.host.member(c,r['project_id'],b.get('reviewer_id'),{'manager','reviewer'})
                reviewer=row(c,'SELECT * FROM users WHERE id=?',(b['reviewer_id'],));self.host.knowledge.assert_refs(c,reviewer,data['document_refs'])
                reason=text(b.get('reason'),'转交原因',2000)
                data.pop('needs_transfer',None)
                data.setdefault('handoffs',[]).append({'from':r['reviewer_id'],'to':reviewer['id'],'actor_id':u['id'],'reason':reason,'at':now()})
                c.execute('UPDATE flow_runs SET reviewer_id=?,data=?,version=version+1,updated_at=? WHERE id=?',(reviewer['id'],js(data),now(),r['id']))
                self.host.event(c,u,r['project_id'],'FLOW_REVIEW_REQUESTED',r['id'],{'reviewer_id':reviewer['id'],'reason':reason})
                return self.host.save_receipt(c,'flow-run:'+r['id'],b,{'id':r['id'],'state':r['state']})
            if action=='review':
                require(not data.get('needs_transfer'),'确认人曾失效，请由项目经理明确转交','REVIEW_HANDOFF_REQUIRED',409)
                require(r['state']=='WAITING_REVIEW' and r['reviewer_id']==u['id'],'只有指定审核人可确认当前成果','PERMISSION_DENIED',403)
                self.host.member(c,r['project_id'],u['id'],{'manager','reviewer'})
                require(b.get('content_hash')==data['review_hash'] and digest(data['outputs'])==data['review_hash'],'待确认成果已变化，请刷新','VERSION_CONFLICT',409)
                require(b.get('decision') in {'APPROVE','REJECT'},'确认结果无效');comment=b.get('comment','')
                require(isinstance(comment,str) and len(comment)<=2000,'确认说明过长')
                if b['decision']=='REJECT':text(comment,'退回原因')
                n=next(n for n in data['graph']['nodes'] if n['type']=='REVIEW')
                data['outputs'][n['id']]={'decision':b['decision'],'actor_id':u['id'],'comment':comment,'decided_at':now()};data['statuses'][n['id']]='SUCCEEDED'
                c.execute("UPDATE flow_attempts SET state='SUCCEEDED',ended_at=?,data=? WHERE run_id=? AND node_id=? AND state='WAITING'",(now(),js(data['outputs'][n['id']]),r['id'],n['id']))
                state='QUEUED' if b['decision']=='APPROVE' else 'REVIEW_REJECTED'
            else:
                self.host.project(c,u,r['project_id'],{'manager'})
                if action=='cancel':
                    require(r['state'] not in {'COMPLETED','CANCELLED'},'运行已结束','STATE_CONFLICT',409);text(b.get('reason'),'取消原因');state='CANCELLED'
                    c.execute("UPDATE flow_attempts SET state='CANCELLED',ended_at=? WHERE run_id=? AND state IN ('RUNNING','WAITING')",(now(),r['id']))
                    for key,value in data['statuses'].items():
                        if value in {'RUNNING','WAITING','PENDING'}:data['statuses'][key]='CANCELLED'
                elif action=='resume':
                    require(r['state']=='FAILED' and data['tool_calls']<8 and data['active_seconds']<300,'当前运行不可恢复或累计预算已耗尽','STATE_CONFLICT',409)
                    for key,value in data['statuses'].items():
                        if value in {'FAILED','SKIPPED'}:data['statuses'][key]='PENDING';data['outputs'].pop(key,None)
                    data.pop('error',None);state='QUEUED'
                else:raise BusinessError(404,'NOT_FOUND','运行操作不存在')
            c.execute('UPDATE flow_runs SET state=?,data=?,version=version+1,updated_at=? WHERE id=?',(state,js(data),now(),r['id']))
            self.host.event(c,u,r['project_id'],'FLOW_'+action.upper(),r['id'],{'state':state})
            return self.host.save_receipt(c,'flow-run:'+r['id'],b,{'id':r['id'],'state':state})
        d=self.definition(c,u,s[1])
        if method=='GET':
            versions=[{**v,'data':json.loads(v['data'])} for v in rows(c,'SELECT * FROM flow_versions WHERE flow_id=? ORDER BY version DESC',(d['id'],))]
            if 'operations' not in self.host.platform.roles(c,u):versions=[v for v in versions if v['state']=='PUBLISHED']
            runs=[]
            for r in rows(c,'SELECT id FROM flow_runs WHERE flow_id=? ORDER BY rowid DESC LIMIT 30',(d['id'],)):
                try:
                    visible=self.run(c,u,r['id']);runs.append({k:visible[k] for k in ['id','state','project_id','flow_version','created_at']})
                except BusinessError:pass
            return {**d,'versions':versions,'runs':runs,'types':sorted(TYPES),'can_edit':'operations' in self.host.platform.roles(c,u),'subflows':rows(c,"SELECT id,name,active_version FROM flow_definitions WHERE tenant_id=? AND purpose='SUBFLOW' AND enabled=1",(u['tenant_id'],))}
        action=s[2]
        if action=='run':return self.start(c,u,d,b)
        self.host.platform.authorize(c,u,'operations')
        if action in {'derive','copy'}:
            old=row(c,'SELECT * FROM flow_versions WHERE flow_id=? AND version=?',(d['id'],b.get('version',d['active_version'])))
            if action=='copy':
                ident=uid('flow');c.execute('INSERT INTO flow_definitions VALUES(?,?,?,?,NULL,1,1,?,?,?)',(ident,u['tenant_id'],text(b.get('name'),'流程名称',100),d['purpose'],u['id'],now(),now()));version=1
            else:
                ident=d['id'];draft=c.execute("SELECT version FROM flow_versions WHERE flow_id=? AND state='DRAFT'",(ident,)).fetchone()
                if draft:return {'id':ident,'version':draft['version']}
                version=c.execute('SELECT max(version)+1 FROM flow_versions WHERE flow_id=?',(ident,)).fetchone()[0]
            c.execute('INSERT INTO flow_versions VALUES(?,?,\'DRAFT\',1,?,?,\'\',?,?)',(ident,version,old['content_hash'],old['data'],u['id'],now()))
            self.host.platform.audit(c,u,'FLOW_DERIVED',ident,{'source':d['id'],'version':version});return {'id':ident,'version':version}
        if action in {'status','rollback'}:
            self.host.version(d,b)
            if action=='status':
                require(type(b.get('enabled')) is bool,'启停状态无效');c.execute('UPDATE flow_definitions SET enabled=?,version=version+1,updated_at=? WHERE id=?',(int(b['enabled']),now(),d['id']))
            else:
                require(type(b.get('version')) is int and b['version']>0,'请选择已发布的回滚版本')
                self.published(c,u['tenant_id'],d['id'],b.get('version'),new=False);c.execute('UPDATE flow_definitions SET active_version=?,version=version+1,updated_at=? WHERE id=?',(b['version'],now(),d['id']))
            self.host.platform.audit(c,u,'FLOW_'+action.upper(),d['id'],{'note':text(b.get('note'),'操作说明',1000),'version':b.get('version')});return {'id':d['id']}
        v=row(c,"SELECT * FROM flow_versions WHERE flow_id=? AND version=? AND state='DRAFT'",(d['id'],b.get('version')))
        require(b.get('expected_revision')==v['revision'],'草稿已更新，请刷新','VERSION_CONFLICT',409)
        graph=b.get('data') if action=='save' else json.loads(v['data']);result=self.validate(c,u,d,graph)
        if action=='save':c.execute('UPDATE flow_versions SET data=?,content_hash=?,revision=revision+1 WHERE flow_id=? AND version=?',(js(graph),digest(graph),d['id'],v['version']))
        elif action=='publish':
            note=text(b.get('note'),'发布说明',1000)
            c.execute("UPDATE flow_versions SET state='PUBLISHED',note=? WHERE flow_id=? AND version=?",(note,d['id'],v['version']))
            c.execute('UPDATE flow_definitions SET active_version=?,version=version+1,updated_at=? WHERE id=?',(v['version'],now(),d['id']))
        else:require(action=='validate','流程操作不存在','NOT_FOUND',404)
        self.host.platform.audit(c,u,'FLOW_'+action.upper(),d['id'],{'version':v['version']})
        return {**result,'id':d['id'],'version':v['version']}

    def start(self,c,u,d,b):
        self.host.project(c,u,b.get('project_id'),{'manager'},True)
        replay=self.host.receipt(c,'flow-start:'+d['id']+':'+u['id'],b)
        if replay:return replay
        _,v=self.published(c,u['tenant_id'],d['id'],b.get('version'))
        require(d['purpose']=='TOP_LEVEL','子流程由父流程继承范围执行，不能单独发起')
        self.validate(c,u,d,v['data']);self.host.member(c,b.get('project_id'),b.get('reviewer_id'),{'manager','reviewer'})
        goal=text(b.get('goal'),'分析目标',2000);self.host.governance.check_capacity(c,u)
        ledger=[json.loads(x['data']) for x in rows(c,'SELECT data FROM ledger WHERE project_id=? ORDER BY task_id',(b['project_id'],))]
        require(ledger,'当前项目没有任务台账')
        refs=self.host.knowledge.available_refs(c,u,b['project_id']);reviewer=row(c,'SELECT * FROM users WHERE id=?',(b['reviewer_id'],));self.host.knowledge.assert_refs(c,reviewer,refs)
        subflows={}
        def bind(graph):
            for n in graph['nodes']:
                if n['type']=='SUBFLOW':
                    ident,version=n['config']['flow_id'],n['config']['version'];_,child=self.published(c,u['tenant_id'],ident,version)
                    subflows[ident+'@'+str(version)]=child['data'];bind(child['data'])
        bind(v['data']);sid,rid=uid('snap'),uid('flowrun');c.execute('INSERT INTO snapshots VALUES(?,?,?,?,?)',(sid,b['project_id'],now(),digest(ledger),js(ledger)))
        data={'goal':goal,'graph':v['data'],'definition_hash':v['content_hash'],'subflows':subflows,'snapshot_id':sid,'snapshot_hash':digest(ledger),'document_refs':refs,'outputs':{},'statuses':{n['id']:'PENDING' for n in v['data']['nodes']},'tool_calls':0,'active_seconds':0,'model_calls':0,'tokens':0,'mode':'READ_ONLY_DEMO','tools':{ident:self.host.governance.published(c,u['tenant_id'],ident)['config_version'] for ident in TOOLS.values()}}
        data.update(period_start=(today()-timedelta(days=6)).isoformat(),period_end=today().isoformat(),function_version='flow-demo-v1')
        data['retrieval_profile']=self.host.sources.profile(c,b['project_id'])
        c.execute('INSERT INTO flow_runs VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(rid,u['tenant_id'],b['project_id'],d['id'],v['version'],u['id'],b['reviewer_id'],'QUEUED',1,js(data),now(),now()))
        self.host.event(c,u,b['project_id'],'FLOW_STARTED',rid,{'flow_id':d['id'],'version':v['version'],'mode':'READ_ONLY_DEMO'})
        return self.host.save_receipt(c,'flow-start:'+d['id']+':'+u['id'],b,{'id':rid,'state':'QUEUED'})

    def invoke(self,rid,path,tool,callback):
        call=uid('call')
        with self.db.tx() as c:
            r=row(c,'SELECT * FROM flow_runs WHERE id=?',(rid,));data=json.loads(r['data']);require(r['state']=='RUNNING','运行已停止','RUN_STOPPED',409)
            u=row(c,'SELECT * FROM users WHERE id=? AND active=1',(r['actor_id'],));self.host.project(c,u,r['project_id'],{'manager'});self.host.knowledge.assert_refs(c,u,data['document_refs'])
            self.host.governance.published(c,u['tenant_id'],tool);require(data['tool_calls']<8,'累计工具调用达到八次上限','BUDGET_EXCEEDED',409)
            data['tool_calls']+=1;c.execute('UPDATE flow_runs SET data=?,version=version+1 WHERE id=?',(js(data),rid))
            c.execute('INSERT INTO tool_invocations VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(call,u['tenant_id'],r['project_id'],u['id'],rid,tool,data['tools'][tool],path,digest({'snapshot':data['snapshot_id'],'node':path}),'RUNNING','只读编排节点已发起',rid+':'+path,None,now()))
        try:
            c=self.db.connect()
            try:result=callback(c,u,data)
            finally:c.close()
            require(isinstance(result,dict),'工具返回类型不符合节点契约','OUTPUT_INVALID',409)
            with self.db.tx() as c:c.execute("UPDATE tool_invocations SET state='SUCCEEDED',summary=? WHERE id=?",('只读结果已返回',call))
            return result
        except Exception:
            with self.db.tx() as c:c.execute("UPDATE tool_invocations SET state='FAILED',summary='只读节点失败，未产生业务写入' WHERE id=?",(call,))
            raise

    def execute(self,rid,n,outputs,data,path='',depth=0):
        if depth==0:return self.execute_node(rid,n,outputs,data,path,depth)
        node_path=path+n['id'];attempt=uid('fnode')
        with self.db.tx() as c:
            run=row(c,'SELECT * FROM flow_runs WHERE id=?',(rid,));require(run['state']=='RUNNING','运行已停止','RUN_STOPPED',409)
            actor=row(c,'SELECT * FROM users WHERE id=? AND active=1',(run['actor_id'],));self.host.project(c,actor,run['project_id'],{'manager'});self.host.knowledge.assert_refs(c,actor,data['document_refs'])
            previous=c.execute('SELECT * FROM flow_attempts WHERE run_id=? AND node_id=? ORDER BY attempt DESC LIMIT 1',(rid,node_path)).fetchone()
            if previous and previous['state']=='SUCCEEDED':return json.loads(previous['data'])
            number=previous['attempt']+1 if previous else 1
            c.execute('INSERT INTO flow_attempts VALUES(?,?,?,?,?,?,?,NULL)',(attempt,rid,node_path,number,'RUNNING','{}',now()))
        try:
            result=self.execute_node(rid,n,outputs,data,path,depth)
            with self.db.tx() as c:
                run=row(c,'SELECT state FROM flow_runs WHERE id=?',(rid,));require(run['state']=='RUNNING','运行已停止','RUN_STOPPED',409)
                c.execute("UPDATE flow_attempts SET state='SUCCEEDED',data=?,ended_at=? WHERE id=?",(js(result),now(),attempt))
            return result
        except Exception as exc:
            with self.db.tx() as c:
                cancelled=row(c,'SELECT state FROM flow_runs WHERE id=?',(rid,))['state']=='CANCELLED'
                c.execute('UPDATE flow_attempts SET state=?,data=?,ended_at=? WHERE id=?',('CANCELLED' if cancelled else 'FAILED',js({'error':{'code':exc.code if isinstance(exc,BusinessError) else 'NODE_FAILED','message':exc.message if isinstance(exc,BusinessError) else '子流程节点未完成'}}),now(),attempt))
            raise

    def execute_node(self,rid,n,outputs,data,path='',depth=0):
        kind=n['type'];path=path+n['id']
        outputs={key:outputs[key] for key in n['deps'] if key in outputs}
        def read(c,u,current):
            source=row(c,'SELECT * FROM snapshots WHERE id=?',(current['snapshot_id'],));ledger=json.loads(source['rows']);require(digest(ledger)==current['snapshot_hash'],'冻结快照校验失败','SOURCE_UNAVAILABLE',409)
            if kind=='LEDGER':return {'record_count':len(ledger),'snapshot_id':source['id']}
            if kind=='RULES':return {'metrics':compute_metrics(ledger,datetime.fromisoformat(source['captured_at']).date(),parse_date(current['period_start']),parse_date(current['period_end'])),'snapshot_id':source['id']}
            evidence=self.host.knowledge.evidence(c,u,current['document_refs'],n['config'].get('query') or current['goal'],limit=6,profile=current.get('retrieval_profile'))
            return {'evidence':evidence,'retrieval_status':'FOUND' if evidence else 'EMPTY','mode':'LOCAL_TEXT'}
        if kind in TOOLS:return self.invoke(rid,path,TOOLS[kind],read)
        if kind=='START':return {'scope':'CURRENT_PROJECT','read_only':True}
        if kind=='SUBFLOW':
            require(depth<2,'子流程嵌套预算已达上限','BUDGET_EXCEEDED',409)
            graph=data['subflows'][n['config']['flow_id']+'@'+str(n['config']['version'])];local={};pending=list(graph['nodes'])
            while pending:
                ready=[x for x in pending if all(k in local for k in x['deps'])];require(ready,'子流程无法继续','OUTPUT_INVALID',409)
                for child in ready:local[child['id']]=self.execute(rid,child,local,data,path+'/',depth+1);pending.remove(child)
            return {'subflow_id':n['config']['flow_id'],'version':n['config']['version'],'outputs':local,'inherited_scope':'CURRENT_PROJECT'}
        evidence=[];metrics=None
        for value in outputs.values():
            if 'metrics' in value:metrics=value['metrics']
            evidence+=value.get('evidence',[])
        if kind=='RISK':
            require(metrics is not None,'缺少上游规则数字','OUTPUT_INVALID',409)
            risks=[]
            for task in metrics['overdue_tasks'][:20]:
                support=[e for e in evidence if task['task_id'] in e['text']]
                risks.append({'task_id':task['task_id'],'title':task['title'],'overdue_days':task['overdue_days'],'hypothesis':support[0]['text'][:450] if support else '缺少直接原因证据，无法确认根因','evidence_ids':[e['evidence_id'] for e in support],'proposal':'核对阻塞与恢复计划，业务动作另行确认'})
            return {'view':'进度风险视角（规则）','risk_items':risks,'truncated':metrics['overdue_count']>20,'missing_information':['资料线索不代表已经验证根因'],'model_calls':0}
        if kind=='ACCEPTANCE':return {'view':'验收证据视角（原文核对）','facts':[{'text':e['text'],'evidence_ids':[e['evidence_id']]} for e in evidence if any(k in e['text'] for k in ['验收','证据','检查'])][:6],'missing_information':[] if evidence else ['未找到授权验收资料'],'model_calls':0}
        if kind=='JOIN':return {'policy':n['config']['policy'],'sources':n['deps'],'outputs':{k:outputs[k] for k in n['deps'] if k in outputs},'partial':any(k not in outputs for k in n['deps']),'field_merge':'各节点独立命名空间，不覆盖规则数字'}
        if kind=='END':return {'summary':'已完成当前流程，原始结果与人工确认记录保留；未发布报告或创建整改。','model_calls':0}
        raise BusinessError(400,'NODE_INVALID','人工确认只能由显式决策推进')

    def recover(self):
        with self.db.tx() as c:
            for r in rows(c,"SELECT * FROM flow_runs WHERE state='RUNNING'"):
                data=json.loads(r['data'])
                for ident,status in data['statuses'].items():
                    if status=='RUNNING':data['statuses'][ident]='FAILED'
                data['error']={'code':'WORKER_INTERRUPTED','message':'服务重启中断只读节点，累计预算已保留，可受控恢复'}
                c.execute("UPDATE flow_runs SET state='FAILED',data=?,version=version+1 WHERE id=?",(js(data),r['id']))
                c.execute("UPDATE flow_attempts SET state='FAILED',ended_at=? WHERE run_id=? AND state='RUNNING'",(now(),r['id']))
                c.execute("UPDATE tool_invocations SET state='FAILED',summary='服务重启，读取结果未确认' WHERE run_id=? AND state='RUNNING'",(r['id'],))

    def process_next(self):
        claimed=[];run=None;started=time.monotonic()
        with self.db.tx() as c:
            raw=c.execute("SELECT * FROM flow_runs WHERE state IN ('QUEUED','RUNNING') ORDER BY rowid LIMIT 1").fetchone()
            if not raw:return False
            run=dict(raw);data=json.loads(run['data']);nodes=data['graph']['nodes']
            pending=[n for n in nodes if data['statuses'][n['id']]=='PENDING']
            ready=[n for n in pending if all(data['statuses'][k] in TERMINAL for k in n['deps'])]
            for n in ready[:3]:
                failed=any(data['statuses'][k]!='SUCCEEDED' for k in n['deps'])
                partial_join=n['type']=='JOIN' and n['config']['policy']=='ALLOW_PARTIAL' and any(data['statuses'][k]=='SUCCEEDED' for k in n['deps'])
                if failed and not partial_join:
                    data['statuses'][n['id']]='SKIPPED';c.execute('INSERT INTO flow_attempts VALUES(?,?,?,?,?,?,?,?)',(uid('fnode'),run['id'],n['id'],c.execute('SELECT count(*)+1 FROM flow_attempts WHERE run_id=? AND node_id=?',(run['id'],n['id'])).fetchone()[0],'SKIPPED',js({'reason':'上游未满足节点契约，未执行此节点'}),now(),now()));continue
                if n['type']=='REVIEW':
                    data['statuses'][n['id']]='WAITING';data['review_hash']=digest(data['outputs'])
                    c.execute('INSERT INTO flow_attempts VALUES(?,?,?,?,?,?,?,NULL)',(uid('fnode'),run['id'],n['id'],c.execute('SELECT count(*)+1 FROM flow_attempts WHERE run_id=? AND node_id=?',(run['id'],n['id'])).fetchone()[0],'WAITING','{}',now()))
                    c.execute("UPDATE flow_runs SET state='WAITING_REVIEW',data=?,version=version+1,updated_at=? WHERE id=?",(js(data),now(),run['id']))
                    self.host.event(c,{'id':run['actor_id']},run['project_id'],'FLOW_REVIEW_REQUESTED',run['id'],{'reviewer_id':run['reviewer_id']})
                    return True
                attempt=uid('fnode');data['statuses'][n['id']]='RUNNING';claimed.append((n,attempt))
                c.execute('INSERT INTO flow_attempts VALUES(?,?,?,?,?,?,?,NULL)',(attempt,run['id'],n['id'],c.execute('SELECT count(*)+1 FROM flow_attempts WHERE run_id=? AND node_id=?',(run['id'],n['id'])).fetchone()[0],'RUNNING','{}',now()))
            state='RUNNING'
            if not claimed and all(x in TERMINAL for x in data['statuses'].values()):state='COMPLETED' if all(data['statuses'][n['id']]=='SUCCEEDED' for n in nodes if n['type']=='END') else 'FAILED'
            c.execute('UPDATE flow_runs SET state=?,data=?,version=version+1,updated_at=? WHERE id=?',(state,js(data),now(),run['id']))
            if state in {'COMPLETED','FAILED'}:self.host.event(c,{'id':run['actor_id']},run['project_id'],'FLOW_'+state,run['id'],{'state':state,'tool_calls':data['tool_calls']})
            if not claimed:return True
        results=[]
        with ThreadPoolExecutor(max_workers=min(3,len(claimed)),thread_name_prefix='eaw-flow') as executor:
            futures=[(n,attempt,executor.submit(self.execute,run['id'],n,data['outputs'],data)) for n,attempt in claimed]
            for n,attempt,future in futures:
                try:results.append((n,attempt,'SUCCEEDED',future.result()))
                except Exception as exc:results.append((n,attempt,'FAILED',{'error':{'code':exc.code if isinstance(exc,BusinessError) else 'NODE_FAILED','message':exc.message if isinstance(exc,BusinessError) else '只读节点失败，输入与已完成结果保留'}}))
        with self.db.tx() as c:
            current=row(c,'SELECT * FROM flow_runs WHERE id=?',(run['id'],));latest=json.loads(current['data'])
            if current['state']=='CANCELLED':
                for _,attempt,_,_ in results:c.execute("UPDATE flow_attempts SET state='CANCELLED',ended_at=? WHERE id=?",(now(),attempt))
                return True
            try:
                u=row(c,'SELECT * FROM users WHERE id=? AND active=1',(current['actor_id'],));self.host.project(c,u,current['project_id'],{'manager'});self.host.knowledge.assert_refs(c,u,latest['document_refs'])
                require(latest['active_seconds']<300,'活跃运行预算已耗尽','BUDGET_EXCEEDED',409)
                for n,attempt,status,value in results:
                    latest['statuses'][n['id']]=status
                    if status=='SUCCEEDED':latest['outputs'][n['id']]=value
                    else:latest['error']=value['error']
                    c.execute('UPDATE flow_attempts SET state=?,data=?,ended_at=? WHERE id=?',(status,js(value),now(),attempt))
                latest['active_seconds']=round(latest['active_seconds']+time.monotonic()-started,5)
                state='RUNNING'
            except BusinessError as exc:
                state='FAILED';latest['error']={'code':exc.code,'message':exc.message}
                for n,attempt,_,_ in results:latest['statuses'][n['id']]='FAILED';c.execute("UPDATE flow_attempts SET state='FAILED',data=?,ended_at=? WHERE id=?",(js(latest['error']),now(),attempt))
            c.execute('UPDATE flow_runs SET state=?,data=?,version=version+1,updated_at=? WHERE id=?',(state,js(latest),now(),current['id']))
        return True
