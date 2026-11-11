"""Small, explicit demo sample comparisons, distinct from model-quality claims."""
import json
import time
from datetime import timedelta
from .db import uid,js,digest,now,today
from .domain import require,text,parse_date,compute_metrics,BusinessError
from .knowledge import row,rows


class Evaluations:
    def __init__(self,host):self.host,self.db=host,host.db

    def authorize(self,c,u,pid):
        self.host.governance.authorize(c,u);self.host.project(c,u,pid,{'manager','reviewer'})

    def validate(self,cases):
        require(isinstance(cases,list) and 1<=len(cases)<=30,'每个演示样本集包含 1～30 条')
        ids=set()
        for case in cases:
            require(isinstance(case,dict) and set(case)=={'id','name','kind','input','gold','allowed_actions'},'样本字段须包含 id、name、kind、input、gold、allowed_actions')
            ident=text(case['id'],'样本编号',80);require(ident not in ids,'样本编号重复');ids.add(ident);text(case['name'],'样本名称',100)
            require(case['kind'] in {'RULES','QUESTION'} and isinstance(case['input'],dict) and isinstance(case['gold'],dict),'样本类型或输入无效')
            require(case['allowed_actions']==['READ_ONLY'],'演示样本只允许只读执行')
            if case['kind']=='RULES':
                inp=case['input'];require(set(inp)=={'rows','cutoff','period_start','period_end'} and isinstance(inp['rows'],list) and len(inp['rows'])<=100,'规则样本需明确台账和周期，每条不超过 100 行')
                cutoff=parse_date(inp['cutoff']);start=parse_date(inp['period_start']);end=parse_date(inp['period_end']);require(start<=end<=cutoff,'样本周期无效')
                taskids=set()
                for task in inp['rows']:
                    require(isinstance(task,dict) and {'task_id','title','status'}<=set(task),'样本任务缺少必填字段')
                    text(task['task_id'],'样本任务编号',80);text(task['title'],'样本任务标题',200);require(task['task_id'] not in taskids,'样本任务重复');taskids.add(task['task_id'])
                    require(task['status'] in {'TODO','IN_PROGRESS','DONE','CANCELLED'},'样本状态无效')
                    for key in ['due_date','planned_start','completed_at']:
                        if task.get(key):parse_date(task[key])
                require(set(case['gold'])<={'total','completed','completion_rate','period_completed','overdue_count','completed_late'} and case['gold'],'Gold 统计字段无效')
                require(all(v is None or type(v) in {int,float} for v in case['gold'].values()),'Gold 指标须为数字或 null')
            else:
                require(set(case['input'])=={'question'} and set(case['gold'])=={'answer_status','contains','min_evidence'},'问答样本须填写问题、预期状态、原文关键词与最少证据数')
                text(case['input']['question'],'样本问题',2000);g=case['gold']
                require(g['answer_status'] in {'SUPPORTED','INSUFFICIENT'} and isinstance(g['contains'],list) and all(isinstance(s,str) and 0<len(s)<=200 for s in g['contains']) and type(g['min_evidence']) is int and 0<=g['min_evidence']<=6,'问答 Gold 格式无效')

    def visible(self,c,u,ident):
        r=row(c,'SELECT * FROM evaluation_runs WHERE id=? AND tenant_id=?',(ident,u['tenant_id']));self.authorize(c,u,r['project_id']);r['data']=json.loads(r['data']);self.host.knowledge.assert_refs(c,u,r['data'].get('document_refs',[]));return r

    def dispatch(self,c,u,method,path,b,query):
        s=path.strip('/').split('/')[1:]
        if len(s)==1:
            pid=query.get('project_id',[''])[0] if method=='GET' else b.get('project_id');self.authorize(c,u,pid)
            if method=='GET':
                definitions=rows(c,"SELECT d.id,d.name,v.version,v.state,v.revision,v.content_hash FROM definitions d JOIN definition_versions v ON v.definition_id=d.id WHERE d.tenant_id=? AND d.kind='WORKFLOW' ORDER BY d.id,v.version DESC",(u['tenant_id'],))
                return {'sets':[{**x,'data':json.loads(x['data'])} for x in rows(c,'SELECT * FROM evaluation_sets WHERE project_id=? AND tenant_id=? ORDER BY rowid DESC',(pid,u['tenant_id']))],'runs':[{'id':r['id'],'state':r['state'],'created_at':r['created_at'],'definition_id':r['definition_id'],'definition_version':r['definition_version'],'set_version':r['set_version']} for r in rows(c,'SELECT * FROM evaluation_runs WHERE project_id=? AND tenant_id=? ORDER BY rowid DESC LIMIT 50',(pid,u['tenant_id'])) if self.allowed(c,u,r['id'])],'definitions':definitions}
            cases=b.get('cases');self.validate(cases);ident=b.get('set_id') or uid('evalset')
            prior=c.execute('SELECT * FROM evaluation_sets WHERE id=? ORDER BY version DESC LIMIT 1',(ident,)).fetchone()
            if prior:require(prior['project_id']==pid and prior['tenant_id']==u['tenant_id'],'样本集不可跨项目修改','PERMISSION_DENIED',403)
            version=prior['version']+1 if prior else 1;name=text(b.get('name'),'样本集名称',100)
            c.execute('INSERT INTO evaluation_sets VALUES(?,?,?,?,?,?,?,?,?)',(ident,version,u['tenant_id'],pid,name,js(cases),digest(cases),u['id'],now()))
            self.host.event(c,u,pid,'EVALUATION_SET_SAVED',ident,{'version':version,'cases':len(cases)})
            return {'id':ident,'version':version}
        if s[1]=='run':
            dataset=row(c,'SELECT * FROM evaluation_sets WHERE id=? AND version=? AND tenant_id=?',(b.get('set_id'),b.get('set_version'),u['tenant_id']));self.authorize(c,u,dataset['project_id'])
            replay=self.host.receipt(c,'evaluation:'+u['id'],b)
            if replay:return replay
            definition=self.host.governance.definition(c,u,b.get('definition_id'));require(definition['kind']=='WORKFLOW','请选择 Workflow 配置')
            configs=[]
            for version in [b.get('definition_version'),b.get('baseline_version')]:
                if version is None:configs.append(None);continue
                v=row(c,'SELECT * FROM definition_versions WHERE definition_id=? AND version=?',(definition['id'],version));cfg=json.loads(v['data']);self.host.governance.validate(c,u,'WORKFLOW',cfg);require(not cfg['allowed_projects'] or dataset['project_id'] in cfg['allowed_projects'],'模板不适用于样本项目','PERMISSION_DENIED',403);configs.append({'version':version,'revision':v['revision'],'hash':v['content_hash'],'data':cfg})
            require(configs[0] is not None,'请选择待比较配置')
            cases=json.loads(dataset['data']);scene=configs[0]['data']['scene'];require(all(x['kind']==('RULES' if scene=='PROGRESS' else 'QUESTION') for x in cases),'规则样本选择进度模板，问答样本选择问答模板')
            require(not configs[1] or configs[1]['data']['scene']==scene,'基准与候选模板场景必须一致')
            refs=self.host.knowledge.available_refs(c,u,dataset['project_id']) if scene=='QUESTION' else []
            data={'dataset_hash':dataset['content_hash'],'cases':cases,'candidate':configs[0],'baseline':configs[1],'document_refs':refs,'mode':'LOCAL_DEMO_COMPARISON','model_calls':0,'tokens':0,'business_writes':0,'limitations':['仅比较声明的演示样本，不代表真实模型准确率','未执行权限、并发、恢复或压力测试','发布门槛由运营人员人工评审，不以本地分数替代生产验收']}
            data['retrieval_profile']=self.host.sources.profile(c,dataset['project_id'])
            ident=uid('evalrun');c.execute('INSERT INTO evaluation_runs VALUES(?,?,?,?,?,?,?,?,?,\'QUEUED\',1,?,?,?)',(ident,u['tenant_id'],dataset['project_id'],u['id'],dataset['id'],dataset['version'],definition['id'],configs[0]['version'],configs[1]['version'] if configs[1] else None,js(data),now(),now()))
            self.host.event(c,u,dataset['project_id'],'EVALUATION_STARTED',ident,{'set_version':dataset['version'],'candidate_version':configs[0]['version']})
            return self.host.save_receipt(c,'evaluation:'+u['id'],b,{'id':ident})
        r=self.visible(c,u,s[1])
        if method=='GET':return {**r,'reviews':rows(c,'SELECT * FROM evaluation_reviews WHERE run_id=? ORDER BY rowid DESC',(r['id'],))}
        require(len(s)==3 and s[2]=='review' and r['state']=='COMPLETED','仅完成比较后可评审','STATE_CONFLICT',409)
        replay=self.host.receipt(c,'eval-review:'+r['id'],b)
        if replay:return replay
        self.host.version(r,b);require(b.get('decision') in {'ACCEPT_DEMO','NEEDS_CHANGE'},'评审结论无效');comment=text(b.get('comment'),'评审说明',4000)
        ident=uid('evalreview');c.execute('INSERT INTO evaluation_reviews VALUES(?,?,?,?,?,?)',(ident,r['id'],u['id'],b['decision'],comment,now()))
        c.execute('UPDATE evaluation_runs SET version=version+1,updated_at=? WHERE id=?',(now(),r['id']))
        self.host.event(c,u,r['project_id'],'EVALUATION_REVIEWED',r['id'],{'decision':b['decision'],'comment':comment})
        return self.host.save_receipt(c,'eval-review:'+r['id'],b,{'id':r['id'],'review_id':ident})

    def allowed(self,c,u,ident):
        try:self.visible(c,u,ident);return True
        except BusinessError:return False

    def compare(self,c,u,r,cfg):
        from .variables import resolve
        results=[]
        for case in r['data']['cases']:
            if case['kind']=='RULES':
                inp=case['input'];metrics=compute_metrics(inp['rows'],parse_date(inp['cutoff']),parse_date(inp['period_start']),parse_date(inp['period_end']))
                variables=resolve(cfg['data'],{'metrics':metrics,'period_end':inp['period_end'],'evidence':[]},'AnalyzeAgent',snapshot_id='evaluation:'+r['id'])
                checks=[{'field':key,'expected':gold,'actual':metrics[key],'matched':metrics[key]==gold} for key,gold in case['gold'].items()]
                actual={'metrics':{k:metrics[k] for k in ['total','completed','completion_rate','overdue_count','period_completed','completed_late']},'focus_tasks':[t['task_id'] for t in metrics['overdue_tasks'] if t['overdue_days']>=cfg['data']['rules']['followup_days']],'prefix':cfg['data']['narrative_prefix'],'variables':variables}
            else:
                evidence=self.host.knowledge.evidence(c,u,r['data']['document_refs'],case['input']['question'],limit=6,profile=r['data'].get('retrieval_profile'));body='\n'.join(e['text'] for e in evidence);g=case['gold'];status='SUPPORTED' if evidence else 'INSUFFICIENT'
                checks=[{'field':'answer_status','expected':g['answer_status'],'actual':status,'matched':g['answer_status']==status},{'field':'min_evidence','expected':g['min_evidence'],'actual':len(evidence),'matched':len(evidence)>=g['min_evidence']}]+[{'field':'contains','expected':part,'actual':part if part in body else None,'matched':part in body} for part in g['contains']]
                actual={'answer_status':status,'evidence':evidence,'model_calls':0}
            results.append({'id':case['id'],'name':case['name'],'checks':checks,'passed':all(x['matched'] for x in checks),'actual':actual,'allowed_actions':case['allowed_actions'],'business_writes':0})
        return {'results':results,'passed':sum(x['passed'] for x in results),'total':len(results),'check_matched':sum(c['matched'] for x in results for c in x['checks']),'check_total':sum(len(x['checks']) for x in results)}

    def process_next(self):
        with self.db.tx() as c:
            raw=c.execute("SELECT * FROM evaluation_runs WHERE state='QUEUED' ORDER BY rowid LIMIT 1").fetchone()
            if not raw:return False
            r=dict(raw);r['data']=json.loads(r['data']);start=time.monotonic()
            try:
                u=row(c,'SELECT * FROM users WHERE id=? AND active=1',(r['actor_id'],));self.authorize(c,u,r['project_id']);self.host.knowledge.assert_refs(c,u,r['data']['document_refs'])
                require(digest(r['data']['cases'])==r['data']['dataset_hash'],'样本集校验失败','VERSION_CONFLICT',409)
                for name in ['candidate','baseline']:
                    cfg=r['data'][name]
                    if cfg:
                        require(digest(cfg['data'])==cfg['hash'],'配置快照校验失败','VERSION_CONFLICT',409);self.host.governance.validate(c,u,'WORKFLOW',cfg['data']);r['data'][name+'_result']=self.compare(c,u,r,cfg)
                state='COMPLETED'
            except Exception as exc:
                state='FAILED';r['data']['error']=exc.message if isinstance(exc,BusinessError) else '样本比较未完成，请核对配置与样本后新建比较'
            r['data']['duration_ms']=round((time.monotonic()-start)*1000,2)
            c.execute('UPDATE evaluation_runs SET state=?,data=?,version=version+1,updated_at=? WHERE id=?',(state,js(r['data']),now(),r['id']))
            self.host.event(c,{'id':r['actor_id']},r['project_id'],'EVALUATION_'+state,r['id'],{'mode':'LOCAL_DEMO_COMPARISON'});return True
