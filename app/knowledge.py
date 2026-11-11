"""Persistent document lifecycle, ACL-filtered retrieval, and extractive Q&A."""
import base64
import binascii
import hashlib
import json
import math
import re
import time
from datetime import timedelta
from collections import Counter
from pathlib import Path
from .db import uid,js,digest,now,today
from .domain import BusinessError,require,text,parse_date
from .document_parser import extract_document,make_chunks


def row(c,query,args=()):
    value=c.execute(query,args).fetchone()
    require(value is not None,'资料不存在或不可访问','NOT_FOUND',404)
    return dict(value)


def rows(c,query,args=()):
    return [dict(x) for x in c.execute(query,args)]


def terms(value):
    value=re.sub(r'\s+','',value.lower())
    words=re.findall(r'[a-z0-9_-]{2,}',value)
    chinese=''.join(re.findall(r'[\u4e00-\u9fff]',value))
    stop={'什么','如何','怎么','哪些','是否','这个','项目','请问','一下','的验','标准'}
    return Counter(words+[chinese[i:i+2] for i in range(len(chinese)-1) if chinese[i:i+2] not in stop])


class Knowledge:
    def __init__(self,host):
        self.host,self.db=host,host.db
        self.fail_once=set()
        self.seed()

    def seed(self):
        with self.db.tx() as c:
            if c.execute("SELECT 1 FROM knowledge_libraries WHERE id='lib_demo'").fetchone():
                return
            if not c.execute("SELECT 1 FROM projects WHERE id='p_demo'").fetchone():
                return
            c.execute('INSERT INTO knowledge_libraries VALUES(?,?,?,?,?)',('lib_demo','p_demo','项目交付资料','虚构资料，用于演示知识问答和进度报告引用',now()))
            samples=[('doc_acceptance','项目验收标准','验收标准','# 项目验收标准\n\n验收要求：核心业务流程可以完整操作，权限检查生效，业务数字可核对，整改证据完整。\n\n验收证据：负责人应提供执行时间、检查结果与异常场景记录，由项目经理核对通过。\n\n整改流程：负责人开始处理、提交证据，项目经理可通过或退回；负责人不能自行验收。\n\n说明：本文件为虚构演示资料，不代表真实企业制度。'),('doc_minutes','项目联调会议纪要','会议纪要','# 联调会议纪要\n\nT-005 验收环境联调：会议记录显示，接口访问白名单尚待确认，需负责人核实后补充检查结果。该记录为原因线索，不代表已验证根因。\n\nT-006 历史数据补录：字段映射仍需核对，计划补充源字段说明与导入错误清单。\n\n下周期关注：完成联调与数据补录，保留处理证据，并由项目经理验收。\n\n说明：本纪要为虚构演示内容。'),('doc_workflow','汇总与审核操作说明','操作规范','# 汇总与审核操作说明\n\n汇总口径：完成率由已完成任务数除以有效任务总数；取消任务不计入分母，当天截止不算逾期。\n\n人工审核：审核绑定正文版本与 hash，正文变化后必须重新提交；审核通过仅批准报告发布。\n\n整改创建：另行选择风险，明确负责人、截止日和验收标准，核对清单后确认创建。\n\n说明：本说明为本地复刻演示资料。')]
            for ident,title,topic,content in samples:
                c.execute('INSERT INTO documents VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',(ident,'p_demo','lib_demo',title,topic,None,'ACTIVE','PROJECT','[]',1,'u_manager',now(),now()))
                raw=content.encode()
                c.execute('INSERT INTO document_versions(document_id,version,filename,content_hash,raw,status,index_version,effective_from,created_at) VALUES(?,?,?,?,?,?,?,?,?)',(ident,1,title+'.md',hashlib.sha256(raw).hexdigest(),raw,'UPLOADED','text-v1',today().isoformat(),now()))

    def document(self,c,u,did,manage=False):
        doc=row(c,'SELECT * FROM documents WHERE id=?',(did,))
        p=self.host.project(c,u,doc['project_id'],{'manager','knowledge_admin'} if manage else None)
        if not manage:
            require(self.library_allowed(c,u,doc['library_id']),'没有此资料范围的访问权限','PERMISSION_DENIED',403)
            require(doc['state']=='ACTIVE' and (doc['acl_mode']=='PROJECT' or u['id'] in json.loads(doc['acl'])),'没有可用的授权资料','PERMISSION_DENIED',403)
        return doc

    def library_policy(self,c,ident):
        library=row(c,'SELECT * FROM knowledge_libraries WHERE id=?',(ident,))
        policy=c.execute('SELECT * FROM library_policies WHERE library_id=?',(ident,)).fetchone()
        if policy:return {**dict(policy),'roles':json.loads(policy['roles']),'members':json.loads(policy['members'])}
        owner=c.execute("SELECT m.user_id FROM memberships m JOIN users u ON u.id=m.user_id WHERE m.project_id=? AND m.role='manager' AND u.active=1 ORDER BY m.rowid LIMIT 1",(library['project_id'],)).fetchone()
        return {'library_id':ident,'owner_id':owner['user_id'] if owner else None,'default_valid_days':0,'acl_mode':'PROJECT','roles':[],'members':[],'version':0,'updated_at':library['created_at']}

    def library_allowed(self,c,u,ident):
        library=row(c,'SELECT project_id FROM knowledge_libraries WHERE id=?',(ident,));p=self.host.project(c,u,library['project_id']);policy=self.library_policy(c,ident)
        return policy['acl_mode']=='PROJECT' or u['id'] in policy['members'] or p['role'] in policy['roles']

    def libraries(self,c,u,pid):
        return [{**x,'policy':self.library_policy(c,x['id'])} for x in rows(c,'SELECT * FROM knowledge_libraries WHERE project_id=? ORDER BY created_at',(pid,)) if self.library_allowed(c,u,x['id'])]

    def can_read(self,c,u,did):
        try:
            self.document(c,u,did)
            return True
        except BusinessError:
            return False

    def assert_refs(self,c,u,refs):
        for ref in refs:
            self.document(c,u,ref['document_id'])
            version=row(c,'SELECT status FROM document_versions WHERE document_id=? AND version=?',(ref['document_id'],ref['document_version']))
            require(version['status']=='AVAILABLE','来源版本已不可用','SOURCE_UNAVAILABLE',409)
            self.host.sources.assert_ref(c,u,ref)

    def output_allowed(self,c,u,kind,ident):
        refs=self.host.sources.scopes(c,kind,ident)
        try:
            self.assert_refs(c,u,refs)
            return True
        except BusinessError:
            return False

    def assert_output(self,c,u,kind,ident):
        require(self.output_allowed(c,u,kind,ident),'结果依赖的资料已撤权或不可用，当前不能查看其正文与摘要','PERMISSION_DENIED',403)

    def attach_sources(self,c,kind,ident,refs):
        for ref in refs:
            c.execute('INSERT OR IGNORE INTO output_sources VALUES(?,?,?,?)',(kind,ident,ref['document_id'],ref['document_version']))
            self.host.sources.attach(c,kind,ident,ref)

    def available_refs(self,c,u,pid,library_ids=None,at_date=None):
        self.host.project(c,u,pid)
        found=[]
        as_of=(at_date or today()).isoformat()
        for doc in rows(c,"SELECT d.*,v.effective_from,v.effective_to FROM documents d JOIN document_versions v ON v.document_id=d.id AND v.version=d.active_version WHERE d.project_id=? AND d.state='ACTIVE' AND v.status='AVAILABLE'",(pid,)):
            if library_ids is not None and doc['library_id'] not in library_ids:
                continue
            historical=c.execute("SELECT version,effective_to FROM document_versions WHERE document_id=? AND status='AVAILABLE' AND effective_from<=? ORDER BY version DESC LIMIT 1",(doc['id'],as_of)).fetchone()
            if not historical:continue
            if historical['effective_to'] and historical['effective_to']<as_of:continue
            if self.can_read(c,u,doc['id']):
                parents=self.host.sources.parent_ids(c,u,doc['id'],historical['version'])
                if parents:found.append({'document_id':doc['id'],'document_version':historical['version'],'parent_ids':parents})
        return found

    def evidence(self,c,u,refs,query=None,limit=8,profile=None,chunk_id=None):
        from .source_policies import DEFAULT
        settings=profile['data'] if profile else DEFAULT
        require(not profile or digest(settings)==profile['content_hash'],'检索配置快照校验失败','SOURCE_UNAVAILABLE',409)
        limit=min(limit,settings['candidate_limit'])
        self.assert_refs(c,u,refs)
        candidates=[]
        for ref in refs:
            doc=self.document(c,u,ref['document_id'])
            version=row(c,'SELECT * FROM document_versions WHERE document_id=? AND version=?',(doc['id'],ref['document_version']))
            for chunk in rows(c,'SELECT * FROM knowledge_chunks WHERE document_id=? AND document_version=? ORDER BY ordinal',(doc['id'],ref['document_version'])):
                if chunk_id is not None and chunk['id']!=chunk_id:continue
                if chunk['parent_id'] not in ref.get('parent_ids',[chunk['parent_id']]) or not self.host.sources.allowed(c,u,chunk['parent_id']):continue
                parent=c.execute('SELECT * FROM knowledge_parents WHERE id=? AND document_id=? AND document_version=?',(chunk['parent_id'],doc['id'],ref['document_version'])).fetchone()
                candidates.append({'evidence_id':'K-'+chunk['id'],'kind':'DOCUMENT','document_id':doc['id'],'document_version':ref['document_version'],'chunk_id':chunk['id'],'parent_id':chunk['parent_id'],'parent_text':parent['content'] if parent else None,'parent_truncated':bool(parent['truncated']) if parent else False,'title':doc['title'],'filename':version['filename'],'topic':doc['topic'],'locator':chunk['anchor'],'heading':chunk['heading'],'text':chunk['content'],'version':f"v{ref['document_version']}/{version['index_version']}",'updated_at':version['created_at']})
                candidates[-1].update(access_policy='当前项目/库/文档授权 ∩ 当前段落授权',retrieval_version=profile['version'] if profile else 0)
                if c.execute('SELECT 1 FROM fragment_policies WHERE document_id=? AND document_version=? LIMIT 1',(doc['id'],ref['document_version'])).fetchone():candidates[-1]['heading']='授权片段'
        if not query:
            return candidates[:limit]
        q=terms(query)
        ranked=[]
        for evidence in candidates:
            body=evidence['text'].strip()
            if body.startswith('#') and '\n' not in body:
                continue
            if body.startswith('说明：') and not any(word in query for word in ['演示','虚构','真实']):
                continue
            words=terms(body)
            overlap=set(q)&set(words)
            score=sum(min(q[w],words[w]) for w in overlap)/max(1,math.sqrt(sum(q.values())*sum(words.values())))
            if set(q)&set(terms(evidence['title'])):
                score*=settings['title_boost']
            if overlap and score>=settings['min_score']:
                ranked.append((score,evidence))
        ranked.sort(key=lambda x:x[0],reverse=True)
        return [e for _,e in ranked[:limit]]

    def list_documents(self,c,u,pid):
        result=[]
        for doc in rows(c,'SELECT d.*, (SELECT max(version) FROM document_versions v WHERE v.document_id=d.id) AS latest_version FROM documents d WHERE project_id=? ORDER BY created_at DESC',(pid,)):
            if not self.can_read(c,u,doc['id']):
                continue
            v=row(c,'SELECT filename,status,error_message,created_at FROM document_versions WHERE document_id=? AND version=?',(doc['id'],doc['latest_version']))
            result.append({**doc,'acl':json.loads(doc['acl']),'latest_status':v['status'],'filename':v['filename'],'error_message':v['error_message'],'available':doc['active_version'] is not None})
        return result

    def dispatch(self,c,u,method,path,b,query):
        s=path.strip('/').split('/')[1:]
        if len(s)>=3 and s[0]=='projects':
            pid=s[1]
            self.host.project(c,u,pid)
            if s[2]=='knowledge' and method=='GET':
                docs=self.list_documents(c,u,pid)
                libs=self.libraries(c,u,pid)
                for lib in libs:
                    lib['document_count']=sum(d['library_id']==lib['id'] for d in docs)
                return {'libraries':libs,'documents':docs,'retrieval_mode':'LOCAL_TEXT','generation_mode':'LOCAL_EXTRACTIVE'}
            if s[2]=='libraries' and len(s)==3 and method=='GET':
                self.host.project(c,u,pid,{'manager','knowledge_admin'});result=[]
                for lib in rows(c,'SELECT * FROM knowledge_libraries WHERE project_id=? ORDER BY created_at',(pid,)):
                    allowed=self.library_allowed(c,u,lib['id'])
                    result.append({'id':lib['id'],'name':lib['name'] if allowed else '受限知识库','policy':self.library_policy(c,lib['id']),'document_count':sum(d['library_id']==lib['id'] for d in self.list_documents(c,u,pid)) if allowed else '受限'})
                return {'libraries':result}
            if s[2]=='libraries' and len(s)==5 and s[4]=='policy':
                self.host.project(c,u,pid,{'manager','knowledge_admin'})
                library=row(c,'SELECT * FROM knowledge_libraries WHERE id=? AND project_id=?',(s[3],pid));policy=self.library_policy(c,library['id'])
                if method=='GET':return policy
                self.host.project(c,u,pid,{'manager','knowledge_admin'},True);self.host.version(policy,b)
                self.host.member(c,pid,b.get('owner_id'),{'manager','knowledge_admin'})
                days=b.get('default_valid_days');require(type(days) is int and 0<=days<=3650,'默认有效期为 0～3650 天，0 表示不默认到期')
                roles=b.get('roles');members=b.get('members');mode=b.get('acl_mode')
                require(mode in {'PROJECT','CUSTOM'} and isinstance(roles,list) and set(roles)<={'manager','member','reviewer','knowledge_admin','service_runner'} and isinstance(members,list) and len(members)<=200,'知识库授权配置无效')
                for member in members:self.host.member(c,pid,member)
                require(mode=='PROJECT' or roles or members,'指定范围不能为空')
                c.execute('INSERT INTO library_policies VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(library_id) DO UPDATE SET owner_id=excluded.owner_id,default_valid_days=excluded.default_valid_days,acl_mode=excluded.acl_mode,roles=excluded.roles,members=excluded.members,version=excluded.version,updated_at=excluded.updated_at',(library['id'],b['owner_id'],days,mode,js(roles),js(members),policy['version']+1,now()))
                self.host.event(c,u,pid,'LIBRARY_POLICY_UPDATED',library['id'],{'before':policy,'after':{k:b[k] for k in ['owner_id','default_valid_days','acl_mode','roles','members']}})
                return {'id':library['id'],'version':policy['version']+1}
            if s[2]=='libraries' and method=='POST':
                self.host.project(c,u,pid,{'manager','knowledge_admin'},True)
                ident=uid('lib')
                c.execute('INSERT INTO knowledge_libraries VALUES(?,?,?,?,?)',(ident,pid,text(b.get('name'),'知识库名称',100),b.get('description','')[:2000],now()))
                self.host.event(c,u,pid,'LIBRARY_CREATED',ident)
                return {'id':ident}
            if s[2]=='documents' and method=='POST':
                return self.upload(c,u,pid,b)
            if s[2]=='questions' and method=='GET':
                results=[]
                for q in rows(c,'SELECT id,question,state,answer_status,version,created_at FROM questions WHERE project_id=? AND actor_id=? ORDER BY rowid DESC LIMIT 100',(pid,u['id'])):
                    if self.output_allowed(c,u,'question',q['id']):
                        results.append(q)
                return {'items':results}
            if s[2]=='feedback' and method=='GET':
                self.host.project(c,u,pid,{'manager','knowledge_admin'})
                result=[]
                for f in rows(c,"SELECT f.*,u.name AS actor_name,q.question,q.data AS question_data,coalesce(r.state,'OPEN') AS state,coalesce(r.note,'') AS resolution_note,coalesce(r.version,0) AS resolution_version,r.updated_at AS resolved_at FROM question_feedback f JOIN questions q ON q.id=f.question_id JOIN users u ON u.id=f.actor_id LEFT JOIN feedback_resolutions r ON r.feedback_id=f.id WHERE q.project_id=? ORDER BY f.rowid DESC LIMIT 200",(pid,)):
                    if not self.output_allowed(c,u,'question',f['question_id']):continue
                    data=json.loads(f.pop('question_data'))
                    f['answer']=data.get('answer','');f['facts']=data.get('facts',[]);f['evidence']=data.get('evidence',[])
                    result.append(f)
                return {'items':result}
            if s[2]=='feedback' and len(s)==4 and method=='POST':
                self.host.project(c,u,pid,{'manager','knowledge_admin'})
                f=row(c,'SELECT f.id,f.question_id FROM question_feedback f JOIN questions q ON q.id=f.question_id WHERE f.id=? AND q.project_id=?',(s[3],pid))
                self.assert_output(c,u,'question',f['question_id'])
                old=c.execute('SELECT * FROM feedback_resolutions WHERE feedback_id=?',(f['id'],)).fetchone()
                require(b.get('expected_version')==(old['version'] if old else 0),'反馈处理状态已更新，请刷新','VERSION_CONFLICT',409)
                require(b.get('state') in {'OPEN','PROCESSING','RESOLVED','DISMISSED'},'处理状态无效')
                note=text(b.get('note'),'处理说明',2000)
                c.execute('INSERT INTO feedback_resolutions VALUES(?,?,?,?,?,?) ON CONFLICT(feedback_id) DO UPDATE SET state=excluded.state,note=excluded.note,actor_id=excluded.actor_id,version=feedback_resolutions.version+1,updated_at=excluded.updated_at',(f['id'],b['state'],note,u['id'],1,now()))
                self.host.event(c,u,pid,'FEEDBACK_HANDLED',f['id'],{'state':b['state'],'note':note})
                return {'id':f['id']}
        if len(s)>=2 and s[0]=='documents':
            did=s[1]
            if len(s)==2 and method=='GET':
                doc=self.document(c,u,did)
                versions=rows(c,'SELECT version,filename,content_hash,status,index_version,error_code,error_message,effective_from,effective_to,created_at FROM document_versions WHERE document_id=? ORDER BY version DESC',(did,))
                requested=int(query.get('version',[doc['active_version'] or versions[0]['version']])[0])
                v=row(c,'SELECT version,content,pages,status FROM document_versions WHERE document_id=? AND version=?',(did,requested))
                parents=rows(c,'SELECT * FROM knowledge_parents WHERE document_id=? AND document_version=? ORDER BY rowid',(did,requested))
                permitted=[p for p in parents if self.host.sources.allowed(c,u,p['id'])]
                if len(permitted)<len(parents):
                    v['content']='\n\n'.join(p['content'] for p in permitted);v['pages']=js([{'anchor':p['anchor'],'text':p['content']} for p in permitted]);v['partial_access']=True
                return {**doc,'acl':json.loads(doc['acl']),'versions':versions,'current':{**v,'pages':json.loads(v['pages'])},'attempts':rows(c,'SELECT stage,attempt,status,started_at,ended_at,summary FROM knowledge_attempts WHERE document_id=? ORDER BY rowid',(did,))}
            if len(s)==3 and method=='POST':
                doc=self.document(c,u,did,manage=True)
                if s[2]=='versions':
                    self.host.version(doc,b)
                    return self.upload(c,u,doc['project_id'],{**b,'document_id':did,'library_id':doc['library_id']})
                self.host.version(doc,b)
                if s[2]=='acl':
                    acl=b.get('members',[])
                    mode=b.get('acl_mode','PROJECT')
                    require(mode in {'PROJECT','MEMBERS'} and isinstance(acl,list),'资料授权格式无效')
                    require(mode=='PROJECT' or len(acl)>0,'指定成员授权不能为空')
                    for person in acl:
                        self.host.member(c,doc['project_id'],person)
                    c.execute('UPDATE documents SET acl_mode=?,acl=?,version=version+1,updated_at=? WHERE id=?',(mode,js(acl),now(),did))
                    self.host.event(c,u,doc['project_id'],'DOCUMENT_ACL_CHANGED',did,{'mode':mode,'members':acl})
                    return {'id':did,'version':doc['version']+1}
                if s[2]=='remove':
                    c.execute("UPDATE documents SET state='REMOVED',version=version+1,updated_at=? WHERE id=?",(now(),did))
                    self.host.event(c,u,doc['project_id'],'DOCUMENT_REMOVED',did)
                    return {'id':did,'state':'REMOVED'}
                if s[2]=='retry':
                    v=b.get('document_version')
                    version=row(c,'SELECT * FROM document_versions WHERE document_id=? AND version=?',(did,v))
                    require(version['status']=='FAILED','只有处理失败的文件版本可以重试')
                    c.execute('UPDATE document_versions SET status=?,error_code=NULL,error_message=NULL WHERE document_id=? AND version=?',('INDEXING' if version['content'] else 'UPLOADED',did,v))
                    return {'id':did,'document_version':v,'state':'QUEUED'}
        if s==['questions'] and method=='POST':
            return self.ask(c,u,b)
        if len(s)>=2 and s[0]=='questions':
            q=row(c,'SELECT * FROM questions WHERE id=?',(s[1],))
            self.host.project(c,u,q['project_id'])
            require(q['actor_id']==u['id'],'不能访问其他用户的问答记录','PERMISSION_DENIED',403)
            self.assert_output(c,u,'question',q['id'])
            if len(s)==2 and method=='GET':
                return {**q,'data':self.host.governance.public_data(c,u,json.loads(q['data']))}
            if len(s)==3 and method=='POST' and s[2]=='cancel':
                if q['state'] in {'COMPLETED','FAILED','CANCELLED'}:
                    return {'id':q['id'],'state':q['state']}
                self.host.version(q,b)
                c.execute("UPDATE questions SET state='CANCELLED',version=version+1,updated_at=? WHERE id=?",(now(),q['id']))
                return {'id':q['id'],'state':'CANCELLED'}
            if len(s)==3 and method=='POST' and s[2]=='feedback':
                kind=b.get('kind')
                require(kind in {'HELPFUL','WRONG_ANSWER','WRONG_CITATION','OUTDATED','OTHER'},'反馈类型无效')
                comment=b.get('comment','')
                require(isinstance(comment,str) and len(comment)<=2000,'反馈内容过长')
                scope='feedback:'+q['id']+':'+u['id']
                old=self.host.receipt(c,scope,b)
                if old:
                    return old
                ident=uid('feedback')
                c.execute('INSERT INTO question_feedback VALUES(?,?,?,?,?,?,?)',(ident,q['id'],u['id'],kind,comment,b['event_key'],now()))
                self.host.event(c,u,q['project_id'],'QUESTION_FEEDBACK',q['id'],{'kind':kind,'comment':comment})
                return self.host.save_receipt(c,scope,b,{'id':ident,'saved':True})
        if len(s)==2 and s[0]=='evidence' and method=='GET':
            chunk=row(c,'SELECT * FROM knowledge_chunks WHERE id=?',(s[1].removeprefix('K-'),))
            doc=self.document(c,u,chunk['document_id'])
            require(self.host.sources.allowed(c,u,chunk['parent_id']),'此来源片段当前不可访问','PERMISSION_DENIED',403)
            ev=self.evidence(c,u,[{'document_id':doc['id'],'document_version':chunk['document_version'],'parent_ids':[chunk['parent_id']]}],limit=1,chunk_id=chunk['id'])
            found=next(e for e in ev if e['chunk_id']==chunk['id'])
            self.host.event(c,u,doc['project_id'],'EVIDENCE_READ',doc['id'],{'document_version':chunk['document_version'],'chunk_id':chunk['id']})
            return found
        raise BusinessError(404,'NOT_FOUND','知识模块接口不存在')

    def upload(self,c,u,pid,b):
        self.host.project(c,u,pid,{'manager','knowledge_admin'},True)
        library=row(c,'SELECT * FROM knowledge_libraries WHERE id=? AND project_id=?',(b.get('library_id'),pid))
        require(self.library_allowed(c,u,library['id']),'没有此知识库的内容访问权限','PERMISSION_DENIED',403)
        scope='upload:'+pid+':'+u['id']
        old=self.host.receipt(c,scope,b)
        if old:
            return old
        files=b.get('files') or [b]
        require(isinstance(files,list) and 1<=len(files)<=20,'每批支持 1～20 个文件')
        result=[]
        for file in files:
            filename=text(file.get('filename'),'文件名',200)
            require(Path(filename).name==filename and Path(filename).suffix.lower() in {'.txt','.md','.pdf','.docx'},'文件名或格式不支持')
            try:
                raw=base64.b64decode(file.get('content_base64',''),validate=True)
            except (binascii.Error,ValueError,TypeError):
                raise BusinessError(400,'INPUT_INVALID','文件内容编码无效')
            require(0<len(raw)<=50*1024*1024,'每文件最大 50 MB 且不能为空')
            hashed=hashlib.sha256(raw).hexdigest()
            did=b.get('document_id')
            if did:
                doc=self.document(c,u,did,manage=True)
                require(doc['project_id']==pid and doc['library_id']==library['id'],'新版本必须沿用原项目与知识库')
                require(doc['state']=='ACTIVE','已下架资料不能上传新版本')
                version=c.execute('SELECT coalesce(max(version),0)+1 FROM document_versions WHERE document_id=?',(did,)).fetchone()[0]
                c.execute('UPDATE documents SET version=version+1,updated_at=? WHERE id=?',(now(),did))
            else:
                duplicate=c.execute('SELECT d.id FROM documents d JOIN document_versions v ON v.document_id=d.id WHERE d.library_id=? AND d.state=\'ACTIVE\' AND v.content_hash=? LIMIT 1',(library['id'],hashed)).fetchone()
                require(duplicate is None,'该知识库已有相同文件。请在原资料详情明确上传新版本。','DUPLICATE_DOCUMENT',409)
                did,version=uid('doc'),1
                title=text(file.get('title') or Path(filename).stem,'资料标题',100)
                topic=text(file.get('topic') or '项目资料','资料主题',100)
                c.execute('INSERT INTO documents VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',(did,pid,library['id'],title,topic,None,'ACTIVE','MEMBERS',js([u['id']]),1,u['id'],now(),now()))
            start=b.get('effective_from') or today().isoformat()
            policy=self.library_policy(c,library['id'])
            end=b.get('effective_to') or ((parse_date(start)+timedelta(days=policy['default_valid_days'])).isoformat() if policy['default_valid_days'] else None)
            parse_date(start)
            require(not end or parse_date(end)>=parse_date(start),'失效日期不能早于生效日期')
            c.execute('INSERT INTO document_versions(document_id,version,filename,content_hash,raw,status,index_version,effective_from,effective_to,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)',(did,version,filename,hashed,raw,'UPLOADED','text-v1',start,end,now()))
            self.host.event(c,u,pid,'DOCUMENT_UPLOADED',did,{'version':version,'filename':filename})
            result.append({'id':did,'document_version':version,'status':'UPLOADED'})
        return self.host.save_receipt(c,scope,b,{'documents':result})

    def ask(self,c,u,b):
        pid=b.get('project_id')
        self.host.project(c,u,pid)
        question=text(b.get('question'),'问题',4000)
        key=text(b.get('submission_key'),'提交键',200)
        old=c.execute('SELECT * FROM questions WHERE project_id=? AND actor_id=? AND submission_key=?',(pid,u['id'],key)).fetchone()
        if old:
            require(old['request_hash']==digest(b),'相同提交键的问题参数已变化','IDEMPOTENCY_CONFLICT',409)
            return {'id':old['id'],'state':old['state']}
        self.host.governance.check_capacity(c,u)
        libs=b.get('library_ids')
        if libs is not None:
            require(isinstance(libs,list) and bool(libs),'请选择至少一个知识库')
            for lib in libs:
                row(c,'SELECT id FROM knowledge_libraries WHERE id=? AND project_id=?',(lib,pid))
        ident=uid('question')
        data={'library_ids':libs,'mode':'LOCAL_EXTRACTIVE','retrieval_mode':'LOCAL_TEXT','evidence':[],'facts':[],'missing_information':[]}
        data['retrieval_profile']=self.host.sources.profile(c,pid)
        parent_id=b.get('parent_question_id')
        data['turn']=1;data['thread_id']=ident
        if parent_id:
            parent=row(c,'SELECT * FROM questions WHERE id=? AND project_id=? AND actor_id=?',(parent_id,pid,u['id']))
            require(parent['state']=='COMPLETED','上轮尚未完成，请等待后追问或开始新问题','STATE_CONFLICT',409)
            self.assert_output(c,u,'question',parent_id)
            previous=json.loads(parent['data']);data['turn']=previous.get('turn',1)+1
            require(data['turn']<=8,'当前会话已达到 8 轮，请开始新问题','CONTEXT_LIMIT',409)
            data['thread_id']=previous.get('thread_id',parent_id);data['parent_question_id']=parent_id
            data['previous_question']=parent['question']
        data['configuration']=self.host.governance.bind(c,u,pid,'wf_question',scene='QUESTION')
        c.execute('INSERT INTO questions VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(ident,pid,u['id'],key,digest(b),question,'QUEUED',None,1,js(data),now(),now()))
        self.host.event(c,u,pid,'QUESTION_CREATED',ident,{},ident)
        return {'id':ident,'state':'QUEUED'}

    def recover(self):
        with self.db.tx() as c:
            c.execute("UPDATE document_versions SET status='UPLOADED' WHERE status='PARSING'")
            c.execute("UPDATE knowledge_attempts SET status='FAILED',ended_at=?,summary='服务重启，处理将从持久输入恢复' WHERE status='RUNNING'",(now(),))
            c.execute("UPDATE questions SET state='QUEUED',version=version+1 WHERE state='RUNNING'")
            for v in rows(c,"SELECT v.document_id,v.version,v.pages FROM document_versions v WHERE v.status='AVAILABLE' AND EXISTS(SELECT 1 FROM knowledge_chunks k WHERE k.document_id=v.document_id AND k.document_version=v.version AND k.parent_id IS NULL)"):
                chunks=make_chunks(json.loads(v['pages']))
                for old in rows(c,'SELECT * FROM knowledge_chunks WHERE document_id=? AND document_version=? ORDER BY ordinal',(v['document_id'],v['version'])):
                    if old['ordinal']<len(chunks):self.save_parent(c,v['document_id'],v['version'],old['id'],chunks[old['ordinal']])

    def save_parent(self,c,did,version,cid,chunk):
        parent=digest([did,version,'parent',chunk['anchor']])[:24]
        c.execute('INSERT OR IGNORE INTO knowledge_parents VALUES(?,?,?,?,?,?,?)',(parent,did,version,chunk['anchor'],chunk['heading'],chunk['parent_content'],int(chunk['parent_truncated'])))
        c.execute('UPDATE knowledge_chunks SET parent_id=? WHERE id=?',(parent,cid))

    def process_next(self):
        work=None
        with self.db.tx() as c:
            version=c.execute("SELECT v.* FROM document_versions v JOIN documents d ON d.id=v.document_id WHERE v.status IN ('UPLOADED','INDEXING') AND d.state='ACTIVE' ORDER BY v.rowid LIMIT 1").fetchone()
            if version:
                v=dict(version)
                stage='PARSE' if v['status']=='UPLOADED' else 'INDEX'
                number=c.execute('SELECT count(*)+1 FROM knowledge_attempts WHERE document_id=? AND document_version=? AND stage=?',(v['document_id'],v['version'],stage)).fetchone()[0]
                aid=uid('kattempt')
                c.execute('INSERT INTO knowledge_attempts VALUES(?,?,?,?,?,?,?,?,?)',(aid,v['document_id'],v['version'],stage,number,'RUNNING',now(),None,'正在解析文本' if stage=='PARSE' else '正在建立索引'))
                if stage=='PARSE':
                    c.execute("UPDATE document_versions SET status='PARSING' WHERE document_id=? AND version=?",(v['document_id'],v['version']))
                work=(v,stage,aid)
        if work:
            v,stage,aid=work
            try:
                if stage in self.fail_once:
                    self.fail_once.remove(stage)
                    raise BusinessError(503,'RETRIEVAL_FAILED','资料处理暂不可用，请重试')
                content,pages=extract_document(v['filename'],v['raw']) if stage=='PARSE' else (v['content'],json.loads(v['pages']))
                with self.db.tx() as c:
                    active=row(c,'SELECT state FROM documents WHERE id=?',(v['document_id'],))
                    require(active['state']=='ACTIVE','资料已下架，处理停止','SOURCE_UNAVAILABLE',409)
                    if stage=='PARSE':
                        c.execute("UPDATE document_versions SET content=?,pages=?,status='INDEXING' WHERE document_id=? AND version=?",(content,js(pages),v['document_id'],v['version']))
                    else:
                        c.execute('DELETE FROM knowledge_chunks WHERE document_id=? AND document_version=?',(v['document_id'],v['version']))
                        for i,chunk in enumerate(make_chunks(pages)):
                            cid=digest([v['document_id'],v['version'],i])[:24]
                            c.execute('INSERT INTO knowledge_chunks VALUES(?,?,?,?,?,?,?,?)',(cid,v['document_id'],v['version'],i,None,chunk['anchor'],chunk['heading'],chunk['content']))
                            self.save_parent(c,v['document_id'],v['version'],cid,chunk)
                        prior=rows(c,"SELECT members FROM fragment_policies WHERE document_id=? AND document_version=(SELECT max(version) FROM document_versions WHERE document_id=? AND version<? AND status='AVAILABLE')",(v['document_id'],v['document_id'],v['version']))
                        if prior:
                            allowed=set(json.loads(prior[0]['members']))
                            for policy in prior[1:]:allowed&=set(json.loads(policy['members']))
                            for parent in rows(c,'SELECT id FROM knowledge_parents WHERE document_id=? AND document_version=?',(v['document_id'],v['version'])):
                                c.execute('INSERT OR IGNORE INTO fragment_policies VALUES(?,?,?,?,?,?)',(parent['id'],v['document_id'],v['version'],js(sorted(allowed)),'system:permission-inheritance',now()))
                        c.execute("UPDATE document_versions SET status='AVAILABLE',error_code=NULL,error_message=NULL WHERE document_id=? AND version=?",(v['document_id'],v['version']))
                        c.execute('UPDATE documents SET active_version=?,version=version+1,updated_at=? WHERE id=? AND (active_version IS NULL OR active_version<?)',(v['version'],now(),v['document_id'],v['version']))
                    c.execute("UPDATE knowledge_attempts SET status='SUCCEEDED',ended_at=?,summary=? WHERE id=?",(now(),'文本解析完成' if stage=='PARSE' else '索引完成，当前有效版本已原子切换',aid))
            except Exception as exc:
                code=exc.code if isinstance(exc,BusinessError) else 'PARSE_FAILED'
                message=exc.message if isinstance(exc,BusinessError) else '资料处理失败，请检查文件并重试'
                with self.db.tx() as c:
                    c.execute("UPDATE document_versions SET status='FAILED',error_code=?,error_message=? WHERE document_id=? AND version=?",(code,message,v['document_id'],v['version']))
                    c.execute("UPDATE knowledge_attempts SET status='FAILED',ended_at=?,summary=? WHERE id=?",(now(),message,aid))
            return True
        with self.db.tx() as c:
            q=c.execute("SELECT * FROM questions WHERE state='QUEUED' ORDER BY rowid LIMIT 1").fetchone()
            if not q:
                return False
            q=dict(q);call=None;active_started=time.monotonic()
            try:
                u=row(c,'SELECT * FROM users WHERE id=? AND active=1',(q['actor_id'],))
                self.host.project(c,u,q['project_id'])
                data=json.loads(q['data'])
                if data.get('parent_question_id'):
                    parent=row(c,'SELECT * FROM questions WHERE id=? AND project_id=? AND actor_id=?',(data['parent_question_id'],q['project_id'],q['actor_id']))
                    self.assert_output(c,u,'question',parent['id'])
                refs=self.available_refs(c,u,q['project_id'],data.get('library_ids'))
                tool=self.host.governance.published(c,u['tenant_id'],'tool_knowledge')
                cfg=data['configuration'];require('tool_knowledge' in cfg['agent']['data']['tools'],'问答 Agent 未授权检索工具','TOOL_DENIED',403)
                call=uid('call');data['tool_calls']=1
                c.execute('INSERT INTO tool_invocations VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(call,u['tenant_id'],q['project_id'],u['id'],q['id'],'tool_knowledge',cfg['tools']['tool_knowledge']['version'],'RetrieveEvidence',digest({'question_id':q['id']}),'RUNNING','问答检索已发起',q['id']+':RetrieveEvidence',None,now()))
                if 'RETRIEVE' in self.fail_once:
                    self.fail_once.remove('RETRIEVE')
                    raise BusinessError(503,'RETRIEVAL_FAILED','暂时无法检索企业资料，请稍后重试')
                retrieval_question=q['question']
                if data.get('previous_question'):retrieval_question=data['previous_question']+' '+retrieval_question
                evidence=self.evidence(c,u,refs,retrieval_question,limit=6,profile=data.get('retrieval_profile'))
                data['document_refs']=refs;data['source_captured_at']=now()
                state='INSUFFICIENT' if not evidence else 'SUPPORTED'
                from .variables import resolve
                data['analysis_context']=resolve(data['configuration']['workflow']['data'],{'evidence':evidence},'GenerateAnswer',question=q['question'])
                # Conservative conflict signal: same topic has different explicit key/value facts.
                claims={}
                conflict=False
                for ev in evidence:
                    for key,value in re.findall(r'([^\n：:。]{2,30})[：:]([^\n。]{2,200})',ev['text']):
                        k=(ev['topic'],key.lstrip('# ').strip())
                        if k in claims and claims[k][0]!=value.strip() and claims[k][1]!=ev['document_id']:
                            conflict=True
                        claims[k]=(value.strip(),ev['document_id'])
                if conflict:
                    state='CONFLICT'
                data.update(evidence=evidence,facts=[{'text':ev['text'],'evidence_ids':[ev['evidence_id']]} for ev in evidence[:4]],answer='未找到支持该问题的授权资料，请补充相关制度或会议纪要。' if not evidence else '发现同主题资料存在不同表述，请核实生效范围后再采用。' if conflict else '以下内容摘录自当前授权资料，请结合来源版本核对。',interpretation='本次为本地检索与原文摘录，未调用真实 LLM。',suggestions=['核对来源版本与适用范围','需要执行的事项仍由人确认'],missing_information=['缺少可用依据'] if not evidence else ['冲突资料需人工确认'] if conflict else [])
                used=self.host.sources.evidence_refs(evidence)
                if data.get('parent_question_id'):used+=self.host.sources.scopes(c,'question',data['parent_question_id'])
                self.attach_sources(c,'question',q['id'],used)
                data['active_seconds']=round(time.monotonic()-active_started,5)
                c.execute("UPDATE tool_invocations SET state='SUCCEEDED',summary='问答授权检索已完成' WHERE id=?",(call,))
                c.execute("UPDATE questions SET state='COMPLETED',answer_status=?,version=version+1,data=?,updated_at=? WHERE id=?",(state,js(data),now(),q['id']))
                self.host.event(c,u,q['project_id'],'QUESTION_COMPLETED',q['id'],{'answer_status':state,'evidence_count':len(evidence)},q['id'])
            except Exception as exc:
                data=json.loads(q['data'])
                if call:
                    data['tool_calls']=1;c.execute("UPDATE tool_invocations SET state='FAILED',summary='问答检索未完成，未产生业务写入' WHERE id=?",(call,))
                data['active_seconds']=round(time.monotonic()-active_started,5)
                data['error']={'code':exc.code if isinstance(exc,BusinessError) else 'RETRIEVAL_FAILED','message':exc.message if isinstance(exc,BusinessError) else '检索失败，请稍后重试','trace_id':q['id']}
                c.execute("UPDATE questions SET state='FAILED',version=version+1,data=?,updated_at=? WHERE id=?",(js(data),now(),q['id']))
            return True
