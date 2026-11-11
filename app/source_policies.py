"""Paragraph-level narrowing and immutable local-retrieval parameter profiles."""
import json
import math
from .db import js,digest,now
from .domain import require,text,BusinessError
from .knowledge import row,rows

DEFAULT={'mode':'LOCAL_KEYWORD','candidate_limit':30,'min_score':0.025,'title_boost':1.25}


class SourcePolicies:
    def __init__(self,host):self.host,self.db=host,host.db

    def profile(self,c,pid,version=None):
        found=c.execute('SELECT * FROM retrieval_profiles WHERE project_id=?'+(' AND version=?' if version is not None else '')+' ORDER BY version DESC LIMIT 1',(pid,version) if version is not None else (pid,)).fetchone()
        if found:return {**dict(found),'data':json.loads(found['data'])}
        require(version in {None,0},'检索配置版本不存在','NOT_FOUND',404)
        return {'project_id':pid,'version':0,'data':dict(DEFAULT),'content_hash':digest(DEFAULT),'note':'内置本地关键词检索参数','created_at':None}

    def allowed(self,c,u,parent):
        policy=c.execute('SELECT members FROM fragment_policies WHERE parent_id=?',(parent,)).fetchone()
        return not policy or u['id'] in json.loads(policy['members'])

    def parent_ids(self,c,u,did,version):
        return [r['id'] for r in rows(c,'SELECT id FROM knowledge_parents WHERE document_id=? AND document_version=? ORDER BY rowid',(did,version)) if self.allowed(c,u,r['id'])]

    def assert_ref(self,c,u,ref):
        parents=[r['id'] for r in rows(c,'SELECT id FROM knowledge_parents WHERE document_id=? AND document_version=?',(ref['document_id'],ref['document_version']))]
        selected=ref.get('parent_ids',parents)
        require(isinstance(selected,list) and all(p in parents and self.allowed(c,u,p) for p in selected),'来源片段的当前权限已变化，结果暂不可访问','PERMISSION_DENIED',403)

    def scopes(self,c,kind,ident):
        result=[]
        for ref in rows(c,'SELECT document_id,document_version FROM output_sources WHERE output_type=? AND output_id=?',(kind,ident)):
            scope=c.execute('SELECT scope FROM output_scopes WHERE output_type=? AND output_id=? AND document_id=? AND document_version=?',(kind,ident,ref['document_id'],ref['document_version'])).fetchone()
            if scope:
                value=json.loads(scope['scope'])
                if value is not None:ref['parent_ids']=value
            result.append(ref)
        return result

    def attach(self,c,kind,ident,ref):
        old=c.execute('SELECT scope FROM output_scopes WHERE output_type=? AND output_id=? AND document_id=? AND document_version=?',(kind,ident,ref['document_id'],ref['document_version'])).fetchone()
        selected=ref.get('parent_ids')
        if old:
            previous=json.loads(old['scope']);selected=sorted(set(previous+selected)) if previous is not None and selected is not None else None
        c.execute('INSERT INTO output_scopes VALUES(?,?,?,?,?) ON CONFLICT(output_type,output_id,document_id,document_version) DO UPDATE SET scope=excluded.scope',(kind,ident,ref['document_id'],ref['document_version'],js(selected)))

    def evidence_refs(self,evidence):
        grouped={}
        for ev in evidence:
            if ev.get('kind')!='DOCUMENT':continue
            key=(ev['document_id'],ev['document_version']);ref=grouped.setdefault(key,{'document_id':key[0],'document_version':key[1],'parent_ids':[]})
            if ev.get('parent_id') and ev['parent_id'] not in ref['parent_ids']:ref['parent_ids'].append(ev['parent_id'])
        return list(grouped.values())

    def dispatch(self,c,u,method,path,b,query):
        s=path.strip('/').split('/')[1:]
        if s[0]=='retrieval':
            pid=query.get('project_id',[''])[0] if method=='GET' else b.get('project_id');self.host.project(c,u,pid,{'manager','knowledge_admin'})
            profile=self.profile(c,pid)
            if method=='GET':return {'current':profile,'versions':[{**r,'data':json.loads(r['data'])} for r in rows(c,'SELECT * FROM retrieval_profiles WHERE project_id=? ORDER BY version DESC',(pid,))]}
            self.host.project(c,u,pid,{'manager','knowledge_admin'},True);self.host.version(profile,b)
            data=b.get('data');require(isinstance(data,dict) and set(data)==set(DEFAULT) and data['mode']=='LOCAL_KEYWORD','检索配置字段无效')
            require(type(data['candidate_limit']) is int and 1<=data['candidate_limit']<=30,'候选上限为 1～30')
            for key,lo,hi in [('min_score',0,1),('title_boost',1,2)]:require(type(data[key]) in {int,float} and math.isfinite(data[key]) and lo<=data[key]<=hi,key+' 超出允许范围')
            version=profile['version']+1;note=text(b.get('note'),'检索配置说明',2000)
            c.execute('INSERT INTO retrieval_profiles VALUES(?,?,?,?,?,?,?)',(pid,version,js(data),digest(data),u['id'],note,now()))
            self.host.event(c,u,pid,'RETRIEVAL_PROFILE_PUBLISHED',pid,{'version':version,'hash':digest(data),'note':note});return {'version':version}
        doc=self.host.knowledge.document(c,u,s[1],manage=True)
        require(self.host.knowledge.library_allowed(c,u,doc['library_id']),'没有此知识库的访问权限','PERMISSION_DENIED',403)
        version=int(query.get('version',[doc['active_version'] or 0])[0]) if method=='GET' else b.get('document_version')
        v=row(c,'SELECT status FROM document_versions WHERE document_id=? AND version=?',(doc['id'],version));require(v['status']=='AVAILABLE','仅可为可用索引配置片段权限')
        if method=='GET':
            base_allowed=self.host.knowledge.can_read(c,u,doc['id'])
            return {'id':doc['id'],'title':doc['title'] if base_allowed else '受限资料','project_id':doc['project_id'],'version':doc['version'],'document_version':version,'items':[{**p,'content':p['content'] if base_allowed and self.allowed(c,u,p['id']) else '受限片段：当前账号不能阅读正文','heading':'授权片段','members':json.loads(policy['members']) if (policy:=c.execute('SELECT members FROM fragment_policies WHERE parent_id=?',(p['id'],)).fetchone()) else None,'can_read':base_allowed and self.allowed(c,u,p['id'])} for p in rows(c,'SELECT * FROM knowledge_parents WHERE document_id=? AND document_version=? ORDER BY rowid',(doc['id'],version))]}
        self.host.project(c,u,doc['project_id'],{'manager','knowledge_admin'},True);self.host.version(doc,b)
        parent=row(c,'SELECT id FROM knowledge_parents WHERE id=? AND document_id=? AND document_version=?',(b.get('parent_id'),doc['id'],version))
        mode=b.get('mode');require(mode in {'INHERIT','MEMBERS'},'片段授权方式无效');reason=text(b.get('reason'),'片段授权说明',2000)
        members=b.get('members',[]);require(isinstance(members,list) and len(members)<=200 and all(isinstance(x,str) for x in members),'片段成员范围无效')
        for member in members:self.host.member(c,doc['project_id'],member)
        if mode=='INHERIT':c.execute('DELETE FROM fragment_policies WHERE parent_id=?',(parent['id'],))
        else:
            require(members,'指定片段成员不能为空')
            c.execute('INSERT INTO fragment_policies VALUES(?,?,?,?,?,?) ON CONFLICT(parent_id) DO UPDATE SET members=excluded.members,actor_id=excluded.actor_id,updated_at=excluded.updated_at',(parent['id'],doc['id'],version,js(sorted(set(members))),u['id'],now()))
        c.execute('UPDATE documents SET version=version+1,updated_at=? WHERE id=?',(now(),doc['id']))
        self.host.collaboration.next_check=0
        self.host.event(c,u,doc['project_id'],'FRAGMENT_POLICY_UPDATED',doc['id'],{'parent_id':parent['id'],'document_version':version,'mode':mode,'members':members if mode=='MEMBERS' else [],'reason':reason})
        return {'id':doc['id'],'version':doc['version']+1}
