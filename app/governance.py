"""Local demo configuration lifecycle and operating statistics.

Definitions are real persisted versions. Sandbox previews use explicit demo rules;
they never call a model or create reports, approvals or rectification tasks.
"""
import json
import time
from datetime import datetime
from .db import js, digest, uid, now, today
from .domain import require, text, BusinessError, compute_metrics
from .knowledge import row, rows

PROGRESS_NODES=['ValidateInput','ReadSnapshot','RuleCompute','RetrieveEvidence','AnalyzeAgent','ValidateOutput','SaveDraft','HumanReview','PublishReport']
QUESTION_NODES=['ValidateInput','RetrieveEvidence','GenerateAnswer','ValidateOutput','SaveAnswer']
TOOLS={
 'tool_ledger':('读取任务台账','ledger_read','READ','ReadSnapshot'),
 'tool_rules':('计算进度指标','rule_compute','COMPUTE','RuleCompute'),
 'tool_knowledge':('检索项目资料','knowledge_search','READ','RetrieveEvidence'),
 'tool_publish':('发布已审核报告','report_publish','WRITE','PublishReport'),
 'tool_rectify':('创建确认整改','rectification_create','WRITE','CreateRectification'),
}
NODE_TOOLS={v[3]:k for k,v in TOOLS.items()}
MAPPINGS={'snapshot.rows':'array','metrics.overdue_tasks':'array','metrics.completion_rate':'number','evidence':'array','risks':'array','period_start':'date','period_end':'date'}


class Governance:
    def __init__(self,host):
        self.host,self.db=host,host.db
        with self.db.tx() as c:
            for tenant in rows(c,'SELECT DISTINCT tenant_id FROM users'):
                tid=tenant['tenant_id']
                if tid!='tenant_demo':continue
                definitions=[('model_demo','MODEL','本地演示分析','规则分析与原文摘录，无外部模型调用',{'mode':'DEMO_RULES','model':'DEMO_RULES','context_limit':12000,'max_output_tokens':1500,'timeout_seconds':45})]
                for ident,(name,handler,kind,node) in TOOLS.items():
                    definitions.append((ident,'TOOL',name,'平台内置能力，由服务端授权',{'handler':handler,'type':kind,'timeout_seconds':30,'max_retries':0 if kind=='WRITE' else 2,'input_schema':{'project_id':'system','object_id':'string'},'output_schema':{'result':'object'},'requires_confirmation':kind=='WRITE','credential_ref':''}))
                for ident,name in [('agent_progress','进度与风险分析 Agent'),('agent_question','资料引用问答 Agent')]:
                    definitions.append((ident,'AGENT',name,'在当前项目的授权证据范围内分析',{'responsibility':'区分事实、原因假设与行动建议；依据不足时明确缺口。','prompt':'根据冻结台账和授权资料生成建议，不将推测当作确定根因。','recommendation':'核实阻塞项，补齐处理证据并提交项目经理验收。','model_id':'model_demo','model_version':1,'tools':['tool_ledger','tool_rules','tool_knowledge'],'knowledge_policy':'CURRENT_PROJECT_AUTHORIZED','budget':{'tool_calls':8,'iterations':3,'active_seconds':300,'context_chars':12000}}))
                for ident,name,scene,agent,nodes in [('wf_progress','项目进度汇总','PROGRESS','agent_progress',PROGRESS_NODES),('wf_question','可信知识问答','QUESTION','agent_question',QUESTION_NODES)]:
                    definitions.append((ident,'WORKFLOW',name,'固定流程、版本绑定与来源追溯',{'scene':scene,'nodes':nodes,'agent_id':agent,'agent_version':1,'review_required':scene=='PROGRESS','narrative_prefix':'本期进展以冻结台账为准。','mappings':[{'source':'metrics.overdue_tasks','type':'array','target':'AnalyzeAgent.tasks'},{'source':'evidence','type':'array','target':'AnalyzeAgent.evidence'}],'branches':{'empty_evidence':'DEGRADED_WITH_GAPS','failure':'STOP','default':'CONTINUE'},'allowed_projects':[],'rules':{'followup_days':3}}))
                for ident,kind,name,description,data in definitions:
                    if c.execute('SELECT 1 FROM definitions WHERE id=?',(ident,)).fetchone():continue
                    c.execute('INSERT INTO definitions VALUES(?,?,?,?,?,1,1,1,?,?,?)',(ident,tid,kind,name,description,'u_manager',now(),now()))
                    c.execute('INSERT INTO definition_versions VALUES(?,1,?,1,?,?,?,?,?,?)',(ident,'PUBLISHED',digest(data),js(data),'内置演示配置','u_manager',now(),now()))
                    c.execute('INSERT INTO definition_releases VALUES(?,?,?,?,?,?,?)',(uid('release'),ident,1,'BOOTSTRAP','u_manager','内置配置；不代表真实模型质量评测',now()))
                c.execute('INSERT OR IGNORE INTO governance_limits VALUES(?,100,5,1)',(tid,))

    def authorize(self,c,u,kind=None):
        roles=self.host.platform.roles(c,u)
        required='tool_admin' if kind=='TOOL' else 'operations'
        require(required in roles,'当前账号没有此配置管理权限','PERMISSION_DENIED',403)

    def public_data(self,c,u,data):
        if 'operations' in self.host.platform.roles(c,u):return data
        result=json.loads(js(data))
        cfg=result.get('configuration')
        if cfg:
            result['configuration']={
                'workflow':{k:v for k,v in cfg.get('workflow',{}).items() if k in {'id','name','version','hash'}},
                'agent':{k:v for k,v in cfg.get('agent',{}).items() if k in {'id','version'}},
                'model':{k:v for k,v in cfg.get('model',{}).items() if k in {'id','version'}},
                'tools':{k:{'version':v['version']} for k,v in cfg.get('tools',{}).items()}}
        return result

    def definition(self,c,u,ident):
        d=row(c,'SELECT * FROM definitions WHERE id=? AND tenant_id=?',(ident,u['tenant_id']))
        self.authorize(c,u,d['kind'])
        return d

    def published(self,c,tid,ident,version=None,new=True):
        d=row(c,'SELECT * FROM definitions WHERE id=? AND tenant_id=?',(ident,tid))
        require(not new or d['enabled'],'配置已停用，不能发起新任务','CONFIG_DISABLED',409)
        v=version if version is not None else d['active_version']
        require(type(v) is int,'配置尚无可用发布版','CONFIG_UNPUBLISHED',409)
        config=row(c,"SELECT * FROM definition_versions WHERE definition_id=? AND version=? AND state='PUBLISHED'",(ident,v))
        return {**d,'config_version':v,'content_hash':config['content_hash'],'data':json.loads(config['data'])}

    def templates(self,c,u,pid=None):
        if pid:self.host.project(c,u,pid)
        result=[]
        for d in rows(c,"SELECT * FROM definitions WHERE tenant_id=? AND kind='WORKFLOW' AND enabled=1 AND active_version IS NOT NULL",(u['tenant_id'],)):
            cfg=self.published(c,u['tenant_id'],d['id'])['data']
            if cfg['allowed_projects'] and pid and pid not in cfg['allowed_projects']:continue
            if cfg['allowed_projects'] and not pid and not any(c.execute('SELECT 1 FROM memberships WHERE project_id=? AND user_id=?',(p,u['id'])).fetchone() for p in cfg['allowed_projects']):continue
            result.append({'id':d['id'],'name':d['name'],'description':d['description'],'version':d['active_version'],'scene':cfg['scene'],'nodes':cfg['nodes'],'allowed_projects':cfg['allowed_projects']})
        return result

    def bind(self,c,u,pid,ident='wf_progress',version=None,scene='PROGRESS'):
        w=self.published(c,u['tenant_id'],ident,version)
        require(w['kind']=='WORKFLOW' and w['data']['scene']==scene,'所选模板不适用于此场景')
        require(not w['data']['allowed_projects'] or pid in w['data']['allowed_projects'],'此模板不适用于当前项目','PERMISSION_DENIED',403)
        a=self.published(c,u['tenant_id'],w['data']['agent_id'],w['data']['agent_version'])
        m=self.published(c,u['tenant_id'],a['data']['model_id'],a['data']['model_version'])
        require(m['data']['mode']=='DEMO_RULES','此版本尚未接通外部模型，请选择本地演示分析','MODEL_UNAVAILABLE',409)
        tools={}
        needed=['tool_ledger','tool_rules','tool_knowledge','tool_publish'] if scene=='PROGRESS' else ['tool_knowledge']
        for tool in needed:
            t=self.published(c,u['tenant_id'],tool)
            tools[tool]={'version':t['config_version'],'data':t['data']}
        return {'workflow':{'id':w['id'],'name':w['name'],'version':w['config_version'],'hash':w['content_hash'],'data':w['data']},'agent':{'id':a['id'],'version':a['config_version'],'data':a['data']},'model':{'id':m['id'],'version':m['config_version'],'data':m['data']},'tools':tools}

    def validate(self,c,u,kind,data):
        require(isinstance(data,dict),'配置必须为对象')
        if kind=='WORKFLOW':
            fields={'scene','nodes','agent_id','agent_version','review_required','narrative_prefix','mappings','branches','allowed_projects','rules'}
            require(set(data) in (fields,fields|{'variables'}),'Workflow 配置字段不完整或含未知字段')
            from .variables import validate as validate_variables,defaults
            validate_variables(data.get('variables',defaults(data.get('scene'))),data.get('scene'))
            require(data['scene'] in {'PROGRESS','QUESTION'},'场景无效')
            require(data['nodes']==(PROGRESS_NODES if data['scene']=='PROGRESS' else QUESTION_NODES),'内置节点拓扑不可修改')
            require(data['review_required']==(data['scene']=='PROGRESS'),'不能取消报告人工审核')
            a=self.published(c,u['tenant_id'],data['agent_id'],data['agent_version'])
            require(a['kind']=='AGENT','Agent 引用无效')
            require(isinstance(data['narrative_prefix'],str) and len(data['narrative_prefix'])<=1000,'报告开场文字最多 1000 字')
            require(isinstance(data['mappings'],list) and len(data['mappings'])<=20,'变量映射无效')
            for mapping in data['mappings']:
                require(isinstance(mapping,dict) and set(mapping)=={'source','type','target'},'变量映射字段无效')
                require(mapping['source'] in MAPPINGS and MAPPINGS[mapping['source']]==mapping['type'],'来源路径不存在或类型不匹配')
                require(mapping['target'] in {'AnalyzeAgent.tasks','AnalyzeAgent.evidence'} and mapping['type']=='array','目标仅支持分析任务/证据数组，禁止覆盖系统变量')
                require(mapping['source']==('metrics.overdue_tasks' if mapping['target']=='AnalyzeAgent.tasks' else 'evidence'),'映射不符合分析节点输入契约')
            require({m['target'] for m in data['mappings']}=={'AnalyzeAgent.tasks','AnalyzeAgent.evidence'} and len(data['mappings'])==2,'分析节点必须保留任务与证据两个独立输入')
            require(data['branches']=={'empty_evidence':'DEGRADED_WITH_GAPS','failure':'STOP','default':'CONTINUE'},'必须保留默认、证据不足和故障路径')
            require(isinstance(data['allowed_projects'],list),'项目范围无效')
            for pid in data['allowed_projects']:self.host.project(c,u,pid)
            require(isinstance(data['rules'],dict) and set(data['rules'])=={'followup_days'} and type(data['rules']['followup_days']) is int and 1<=data['rules']['followup_days']<=365,'关注阈值须为 1～365 天')
        elif kind=='AGENT':
            fields={'responsibility','prompt','recommendation','model_id','model_version','tools','knowledge_policy','budget'}
            require(set(data)==fields,'Agent 配置字段不完整或含未知字段')
            for key in ['responsibility','prompt','recommendation']:text(data.get(key),key,6000 if key=='prompt' else 2000)
            m=self.published(c,u['tenant_id'],data['model_id'],data['model_version'])
            require(m['kind']=='MODEL','模型引用无效')
            require(data['knowledge_policy']=='CURRENT_PROJECT_AUTHORIZED','知识范围只能是当前授权项目')
            require(isinstance(data['tools'],list) and len(data['tools'])==len(set(data['tools'])),'工具名单无效')
            for ident in data['tools']:
                tool=self.published(c,u['tenant_id'],ident)
                require(tool['kind']=='TOOL' and tool['data']['type'] in {'READ','COMPUTE'},'分析 Agent 不允许业务写工具')
            budget=data['budget'];require(isinstance(budget,dict) and set(budget)=={'tool_calls','iterations','active_seconds','context_chars'},'预算字段无效')
            for key,lo,hi in [('tool_calls',3,30),('iterations',1,3),('active_seconds',10,300),('context_chars',1000,40000)]:
                require(type(budget[key]) is int and lo<=budget[key]<=hi,f'{key} 超出允许范围 {lo}～{hi}')
        elif kind=='TOOL':
            require(set(data)=={'handler','type','timeout_seconds','max_retries','input_schema','output_schema','requires_confirmation','credential_ref'},'工具字段不完整或含未知字段')
            known=next((v for v in TOOLS.values() if v[1]==data['handler']),None)
            require(known is not None and data['type']==known[2],'仅允许平台内置工具，不能改变读写类型')
            require(data['requires_confirmation']==(data['type']=='WRITE'),'写工具必须要求人工确认')
            require(data['credential_ref']=='','内置工具不需要外部凭据，不得填写真实密钥')
            require(data['input_schema']=={'project_id':'system','object_id':'string'} and data['output_schema']=={'result':'object'},'内置工具 Schema 不可修改')
            require(type(data['timeout_seconds']) is int and 1<=data['timeout_seconds']<=120,'超时范围为 1～120 秒')
            require(type(data['max_retries']) is int and 0<=data['max_retries']<=(0 if data['type']=='WRITE' else 2),'写工具不能盲目重试；读工具最多重试两次')
        elif kind=='MODEL':
            require(set(data)=={'mode','model','context_limit','max_output_tokens','timeout_seconds'},'模型字段不完整或含未知字段')
            require(data['mode']=='DEMO_RULES' and data['model']=='DEMO_RULES','当前演示版本使用本地规则，不发起外部模型调用')
            for key,lo,hi in [('context_limit',1000,40000),('max_output_tokens',128,8000),('timeout_seconds',1,120)]:
                require(type(data[key]) is int and lo<=data[key]<=hi,key+' 超出允许范围')
        else:raise BusinessError(400,'INPUT_INVALID','配置类型无效')
        return ['结构和必填字段有效','依赖版本可用','知识与工具授权边界有效','默认路径、人工审核与预算规则保留']

    def detail(self,c,u,d):
        versions=[{**v,'data':json.loads(v['data'])} for v in rows(c,'SELECT * FROM definition_versions WHERE definition_id=? ORDER BY version DESC',(d['id'],))]
        dependencies=[]
        for v in rows(c,"SELECT d.id,d.name,d.kind,v.version,v.data FROM definitions d JOIN definition_versions v ON v.definition_id=d.id WHERE d.tenant_id=? AND v.state='PUBLISHED'",(u['tenant_id'],)):
            cfg=json.loads(v.pop('data'))
            if cfg.get('agent_id')==d['id'] or cfg.get('model_id')==d['id'] or d['id'] in cfg.get('tools',[]):dependencies.append(v)
        debugs=[]
        for x in rows(c,'SELECT * FROM definition_debugs WHERE definition_id=? ORDER BY rowid DESC LIMIT 10',(d['id'],)):
            data=json.loads(x['data'])
            try:
                self.host.project(c,u,x['project_id'])
                self.host.knowledge.assert_refs(c,u,data.get('document_refs',[]))
                debugs.append({**x,'data':data})
            except BusinessError:pass
        return {**d,'versions':versions,'dependencies':dependencies,'debugs':debugs,'releases':rows(c,'SELECT * FROM definition_releases WHERE definition_id=? ORDER BY rowid DESC',(d['id'],))}

    def dispatch(self,c,u,method,path,b,query):
        s=path.strip('/').split('/')[1:]
        if s==['templates'] and method=='GET':return {'items':self.templates(c,u,query.get('project_id',[''])[0] or None)}
        if s[:1]==['operations']:return self.operations(c,u,method,s,b,query)
        if s==['definitions']:
            kind=query.get('kind',['WORKFLOW'])[0]
            if not (kind=='TOOL' and method=='GET' and 'operations' in self.host.platform.roles(c,u)):self.authorize(c,u,kind)
            require(kind in {'WORKFLOW','AGENT','TOOL','MODEL'},'配置类型无效')
            return {'items':rows(c,'SELECT d.*,(SELECT max(version) FROM definition_versions v WHERE v.definition_id=d.id AND v.state=\'DRAFT\') AS draft_version FROM definitions d WHERE tenant_id=? AND kind=? ORDER BY rowid',(u['tenant_id'],kind))}
        require(len(s)>=2 and s[0]=='definitions','接口不存在','NOT_FOUND',404)
        d=self.definition(c,u,s[1])
        if method=='GET' and len(s)==2:return self.detail(c,u,d)
        require(method=='POST' and len(s)==3,'接口不存在','NOT_FOUND',404)
        action=s[2]
        if action in {'derive','copy'}:
            source=row(c,'SELECT * FROM definition_versions WHERE definition_id=? AND version=?',(d['id'],b.get('version',d['active_version'])))
            if action=='copy':
                require(d['kind']!='TOOL','内置工具不能复制为新的可执行能力')
                ident=uid(d['kind'].lower());name=text(b.get('name',d['name']+' · 副本'),'名称',100)
                c.execute('INSERT INTO definitions VALUES(?,?,?,?,?,NULL,1,1,?,?,?)',(ident,u['tenant_id'],d['kind'],name,d['description'],u['id'],now(),now()))
                data=json.loads(source['data'])
                if d['kind']=='WORKFLOW':data['allowed_projects']=[]
                version=1
            else:
                ident=d['id']
                existing=c.execute("SELECT version FROM definition_versions WHERE definition_id=? AND state='DRAFT'",(ident,)).fetchone()
                if existing:return {'id':ident,'version':existing['version']}
                data=json.loads(source['data']);version=c.execute('SELECT max(version)+1 FROM definition_versions WHERE definition_id=?',(ident,)).fetchone()[0]
            if d['kind']=='WORKFLOW':
                from .variables import defaults
                data.setdefault('variables',defaults(data['scene']))
            c.execute('INSERT INTO definition_versions VALUES(?,?,\'DRAFT\',1,?,?,\'\',?,?,NULL)',(ident,version,digest(data),js(data),u['id'],now()))
            self.host.platform.audit(c,u,'CONFIG_'+action.upper(),ident,{'source':d['id'],'version':version})
            return {'id':ident,'version':version}
        if action in {'status','rollback'}:
            self.host.version(d,b)
            note=text(b.get('note'),'操作说明',1000)
            if action=='status':
                require(type(b.get('enabled')) is bool,'启停状态无效')
                c.execute('UPDATE definitions SET enabled=?,version=version+1,updated_at=? WHERE id=?',(int(b['enabled']),now(),d['id']))
                v=d['active_version'] or 0
            else:
                v=b.get('version');self.published(c,u['tenant_id'],d['id'],v,new=False)
                c.execute('UPDATE definitions SET active_version=?,version=version+1,updated_at=? WHERE id=?',(v,now(),d['id']))
            c.execute('INSERT INTO definition_releases VALUES(?,?,?,?,?,?,?)',(uid('release'),d['id'],v,action.upper(),u['id'],note,now()))
            self.host.platform.audit(c,u,'CONFIG_'+action.upper(),d['id'],{'version':v,'note':note,'enabled':b.get('enabled')})
            return {'id':d['id']}
        v=row(c,"SELECT * FROM definition_versions WHERE definition_id=? AND version=? AND state='DRAFT'",(d['id'],b.get('version')))
        require(b.get('expected_revision')==v['revision'],'配置草稿已更新，请刷新','VERSION_CONFLICT',409)
        data=json.loads(v['data'])
        if action=='save':
            data=b.get('data');checks=self.validate(c,u,d['kind'],data)
            c.execute('UPDATE definition_versions SET data=?,content_hash=?,revision=revision+1 WHERE definition_id=? AND version=?',(js(data),digest(data),d['id'],v['version']))
            self.host.platform.audit(c,u,'CONFIG_SAVED',d['id'],{'version':v['version'],'revision':v['revision']+1})
            return {'id':d['id'],'version':v['version'],'revision':v['revision']+1,'checks':checks}
        checks=self.validate(c,u,d['kind'],data)
        if action=='validate':return {'checks':checks,'state':'VALID'}
        if action=='debug':
            started=time.monotonic();pid=b.get('project_id')
            p=self.host.project(c,u,pid)
            ledger=[json.loads(x['data']) for x in rows(c,'SELECT data FROM ledger WHERE project_id=?',(pid,))]
            refs=self.host.knowledge.available_refs(c,u,pid)
            evidence=self.host.knowledge.evidence(c,u,refs,limit=5)
            metrics=compute_metrics(ledger,today(),today(),today())
            variables={}
            if d['kind']=='WORKFLOW':
                from .variables import resolve
                variables=resolve(data,{'metrics':metrics,'evidence':evidence,'period_end':today().isoformat()},'AnalyzeAgent' if data['scene']=='PROGRESS' else 'GenerateAnswer',question='演示配置预览',snapshot_id='sandbox:'+d['id'])
            result={'mode':'SANDBOX_DEMO','project_name':p['name'],'checks':checks,'input':{'ledger_rows':len(ledger),'document_versions':len(refs)},'evidence':[{'evidence_id':e['evidence_id'],'title':e['title'],'locator':e['locator']} for e in evidence],'output':{'summary':data.get('narrative_prefix','使用授权演示资料的配置预览'),'overdue_count':metrics['overdue_count'],'proposal_count':metrics['overdue_count'],'write_actions':'仅展示拟执行动作；未创建报告或整改'},'duration_ms':round((time.monotonic()-started)*1000),'model_calls':0,'tokens':0,'limitations':['采用本地规则；不是实际模型质量评测','严格回归与压力评测按用户要求后置']}
            result['document_refs']=refs
            result['typed_variables']=variables
            ident=uid('debug')
            c.execute('INSERT INTO definition_debugs VALUES(?,?,?,?,?,?,?,?,?,?)',(ident,d['id'],v['version'],v['revision'],v['content_hash'],u['id'],pid,'SUCCEEDED',js(result),now()))
            self.host.platform.audit(c,u,'CONFIG_DEBUGGED',d['id'],{'version':v['version'],'debug_id':ident},pid)
            return {'id':ident,**result}
        if action=='publish':
            note=text(b.get('note'),'发布说明',1000)
            debug=c.execute("SELECT id FROM definition_debugs WHERE definition_id=? AND definition_version=? AND revision=? AND content_hash=? AND state='SUCCEEDED'",(d['id'],v['version'],v['revision'],v['content_hash'])).fetchone()
            require(debug is not None,'请先对当前草稿完成一次沙箱预览','DEBUG_REQUIRED',409)
            c.execute("UPDATE definition_versions SET state='PUBLISHED',change_note=?,published_at=? WHERE definition_id=? AND version=?",(note,now(),d['id'],v['version']))
            c.execute('UPDATE definitions SET active_version=?,enabled=1,version=version+1,updated_at=? WHERE id=?',(v['version'],now(),d['id']))
            c.execute('INSERT INTO definition_releases VALUES(?,?,?,?,?,?,?)',(uid('release'),d['id'],v['version'],'PUBLISH',u['id'],note,now()))
            self.host.platform.audit(c,u,'CONFIG_PUBLISHED',d['id'],{'version':v['version'],'note':note,'debug_id':debug['id']})
            return {'id':d['id'],'version':v['version']}
        raise BusinessError(404,'NOT_FOUND','配置操作不存在')

    def check_node(self,c,u,r,node):
        ident=NODE_TOOLS.get(node)
        if not ident:return None
        d=self.published(c,u['tenant_id'],ident)
        cfg=r['data'].get('configuration')
        if cfg and node!='PublishReport':
            require(ident in cfg['agent']['data']['tools'],'当前分析 Agent 未授权此工具','TOOL_DENIED',403)
            used=r['data'].get('tool_calls',0)
            require(used<cfg['agent']['data']['budget']['tool_calls'],'本次工具调用预算已耗尽','BUDGET_EXCEEDED',409)
        self.host.project(c,u,r['project_id'],{'service_runner'} if r['data'].get('schedule_id') else {'manager'})
        r['data']['tool_calls']=r['data'].get('tool_calls',0)+1
        return {'id':ident,'version':cfg['tools'].get(ident,{}).get('version',d['config_version']) if cfg else d['config_version']}

    def log_tool(self,c,u,r,node,tool,state,summary):
        if not tool:return
        c.execute('INSERT INTO tool_invocations VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(uid('call'),u['tenant_id'],r['project_id'],u['id'],r['id'],tool['id'],tool['version'],node,digest({'snapshot':r['snapshot_id'],'node':node}),state,summary[:500],r['id']+':'+node,r['data'].get('report_id'),now()))

    def check_capacity(self,c,u):
        limits=row(c,'SELECT * FROM governance_limits WHERE tenant_id=?',(u['tenant_id'],))
        active=sum(c.execute('SELECT count(*) FROM '+table+" r JOIN projects p ON p.id=r.project_id WHERE p.tenant_id=? AND r.state IN ('QUEUED','RUNNING')",(u['tenant_id'],)).fetchone()[0] for table in ['runs','analyses','questions','flow_runs'])
        require(active<limits['max_active_runs'],'运行队列已达到企业上限，请等待后重试','QUEUE_LIMIT',429)

    def operations(self,c,u,method,s,b,query):
        self.authorize(c,u)
        limits=row(c,'SELECT * FROM governance_limits WHERE tenant_id=?',(u['tenant_id'],))
        if s==['operations','limits'] and method=='POST':
            self.host.platform.authorize(c,u)
            self.host.version(limits,b)
            for key,lo,hi in [('daily_model_calls',0,10000),('max_active_runs',1,20)]:require(type(b.get(key)) is int and lo<=b[key]<=hi,key+' 超出允许范围')
            c.execute('UPDATE governance_limits SET daily_model_calls=?,max_active_runs=?,version=version+1 WHERE tenant_id=?',(b['daily_model_calls'],b['max_active_runs'],u['tenant_id']))
            self.host.platform.audit(c,u,'LIMITS_UPDATED',u['tenant_id'],{k:b[k] for k in ['daily_model_calls','max_active_runs']})
            return {'state':'SAVED'}
        require(method=='GET' and s==['operations','overview'],'接口不存在','NOT_FOUND',404)
        records=[]
        for r in rows(c,'SELECT r.*,p.name AS project_name FROM runs r JOIN projects p ON p.id=r.project_id WHERE p.tenant_id=? ORDER BY r.rowid DESC',(u['tenant_id'],)):
            try:self.host.run(c,u,r['id'])
            except BusinessError:continue
            data=json.loads(r.pop('data'));cfg=data.get('configuration',{}).get('workflow',{})
            if query.get('project_id',[''])[0] not in {'',r['project_id']}:continue
            if query.get('template_id',[''])[0] not in {'',cfg.get('id')}:continue
            if query.get('date_from',[''])[0] and r['created_at'][:10]<query['date_from'][0]:continue
            if query.get('date_to',[''])[0] and r['created_at'][:10]>query['date_to'][0]:continue
            attempts=rows(c,'SELECT * FROM attempts WHERE run_id=?',(r['id'],))
            generation=0;waiting=0
            for a in attempts:
                if not a['ended_at']:continue
                elapsed=max(0,(datetime.fromisoformat(a['ended_at'])-datetime.fromisoformat(a['started_at'])).total_seconds())
                if a['node']=='HumanReview':waiting+=elapsed
                else:generation+=elapsed
            records.append({**r,'template':cfg.get('name','项目进度汇总'),'template_id':cfg.get('id','wf_progress'),'template_version':cfg.get('version',1),'generation_seconds':generation,'review_wait_seconds':waiting,'tool_calls':data.get('tool_calls'),'model_calls':data.get('model_calls',0),'tokens':data.get('tokens',0),'error':data.get('error'),'node_calls':data.get('node_calls',0)})
            if 'active_seconds' in data:records[-1]['generation_seconds']=round(data['active_seconds'],3)
        for record in records:record.update(kind='PROGRESS',url='#/runs/'+record['id'])
        for table,kind,label,route in [('questions','QUESTION','可信知识问答','questions'),('analyses','ANALYSIS','开放风险分析','analyses'),('flow_runs','FLOW','可视化编排','flow-runs')]:
            for raw in rows(c,'SELECT r.*,p.name AS project_name FROM '+table+' r JOIN projects p ON p.id=r.project_id WHERE p.tenant_id=? ORDER BY r.rowid DESC',(u['tenant_id'],)):
                try:
                    self.host.project(c,u,raw['project_id'])
                    if kind=='QUESTION':
                        require(raw['actor_id']==u['id'],'个人问答受限','PERMISSION_DENIED',403);self.host.knowledge.assert_output(c,u,'question',raw['id'])
                    elif kind=='ANALYSIS':self.host.advanced.analysis(c,u,raw['id'])
                    else:self.host.flows.run(c,u,raw['id'])
                except BusinessError:continue
                data=json.loads(raw['data']);cfg=data.get('configuration',{}).get('workflow',{})
                template_id=cfg.get('id','wf_question' if kind=='QUESTION' else raw.get('flow_id',kind))
                if query.get('project_id',[''])[0] not in {'',raw['project_id']} or query.get('template_id',[''])[0] not in {'',template_id}:continue
                if query.get('date_from',[''])[0] and raw['created_at'][:10]<query['date_from'][0]:continue
                if query.get('date_to',[''])[0] and raw['created_at'][:10]>query['date_to'][0]:continue
                waiting=0
                if kind=='FLOW':
                    for attempt in rows(c,"SELECT * FROM flow_attempts WHERE run_id=? AND node_id NOT LIKE '%/%' AND state IN ('WAITING','SUCCEEDED')",(raw['id'],)):
                        if any(n['id']==attempt['node_id'] and n['type']=='REVIEW' for n in data['graph']['nodes']):waiting+=max(0,(datetime.fromisoformat(attempt['ended_at'] or now())-datetime.fromisoformat(attempt['started_at'])).total_seconds())
                records.append({k:raw[k] for k in ['id','project_id','project_name','state','created_at','updated_at']}|{'kind':kind,'url':'#/'+route+'/'+raw['id'],'template':label,'template_id':template_id,'template_version':cfg.get('version',raw.get('flow_version',1)),'generation_seconds':round(data['active_seconds'],3) if 'active_seconds' in data else None,'review_wait_seconds':waiting,'tool_calls':data.get('tool_calls'),'model_calls':data.get('model_calls',0),'tokens':data.get('tokens',0),'error':data.get('error'),'node_calls':c.execute('SELECT count(*) FROM '+('flow_attempts WHERE run_id=?' if kind=='FLOW' else 'analysis_steps WHERE analysis_id=?'),(raw['id'],)).fetchone()[0] if kind!='QUESTION' else None})
        if query.get('channel',[''])[0]:records=[r for r in records if r['kind']==query['channel'][0]]
        records.sort(key=lambda r:r['created_at'],reverse=True)
        for record in records:
            terminal=record['state'] in {'COMPLETED','FAILED','CANCELLED','REVIEW_REJECTED'}
            record['elapsed_seconds']=max(0,round((datetime.fromisoformat(record['updated_at'] if terminal else now())-datetime.fromisoformat(record['created_at'])).total_seconds(),2))
        ids={r['id'] for r in records}
        calls=rows(c,'SELECT * FROM tool_invocations WHERE tenant_id=? ORDER BY rowid DESC',(u['tenant_id'],))
        calls=[x for x in calls if x['run_id'] in ids]
        counts={state:sum(r['state']==state for r in records) for state in ['COMPLETED','FAILED','WAITING_REVIEW','REVIEW_REJECTED','CANCELLED','QUEUED','RUNNING']}
        return {'items':records,'counts':counts,'total':len(records),'calls':calls[:50],'tool_errors':sum(x['state']=='FAILED' for x in calls),'model_calls':sum(x['model_calls'] for x in records),'tokens':sum(x['tokens'] for x in records),'cost':None,'limits':limits,'worker_mode':'单机顺序队列；人工审核等待不占执行线程','budget_hits':sum((x['error'] or {}).get('code')=='BUDGET_EXCEEDED' for x in records),'templates':self.templates(c,u),'measurement_note':'真实本地运行记录；历史记录未采集的工具调用不追补为实测。耗时精度为秒。'}
