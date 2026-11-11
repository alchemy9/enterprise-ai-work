"""Reviewable action extensions, authenticated export jobs and soft-delete purge."""
import hashlib
import json
import secrets
from datetime import datetime,timedelta
from .db import uid,js,digest,now,today,TZ
from .domain import require,text,parse_date,BusinessError
from .knowledge import row,rows

MIME={'md':'text/markdown; charset=utf-8','docx':'application/vnd.openxmlformats-officedocument.wordprocessingml.document','pdf':'application/pdf'}


class Delivery:
    def __init__(self,host):
        self.host,self.db=host,host.db
        with self.db.tx() as c:
            for job in rows(c,"SELECT * FROM export_jobs WHERE format='pdf' AND state='SUCCEEDED'"):
                if json.loads(job['data']).get('renderer_version')!='pdf-ttf-v1':
                    c.execute("UPDATE export_jobs SET state='FAILED',error='旧 PDF 字体未嵌入，请重新生成兼容版本',version=version+1,updated_at=? WHERE id=?",(now(),job['id']))

    def export(self,c,u,ident):
        job=row(c,'SELECT * FROM export_jobs WHERE id=? AND tenant_id=? AND actor_id=?',(ident,u['tenant_id'],u['id']))
        self.host.report(c,u,job['report_id'])
        return job

    def detail(self,job):
        return {k:v for k,v in job.items() if k!='body'}|{'data':json.loads(job['data'])}

    def dispatch(self,c,u,method,path,b,query):
        s=path.strip('/').split('/')[1:]
        if s[0]=='exports':
            if len(s)==1:
                if method=='GET':
                    visible=[]
                    for j in rows(c,'SELECT id FROM export_jobs WHERE actor_id=? AND tenant_id=? ORDER BY rowid DESC LIMIT 100',(u['id'],u['tenant_id'])):
                        try:visible.append(self.detail(self.export(c,u,j['id'])))
                        except BusinessError:pass
                    return {'items':visible}
                report=self.host.report_detail(c,u,b.get('report_id'));fmt=b.get('format')
                require(fmt in MIME,'请选择 Markdown、Word 或 PDF')
                replay=self.host.receipt(c,'export:'+u['id'],b)
                if replay:return replay
                require(c.execute("SELECT count(*) FROM export_jobs WHERE actor_id=? AND state IN ('QUEUED','RUNNING')",(u['id'],)).fetchone()[0]<5,'导出队列已满，请等待现有任务完成','QUEUE_LIMIT',429)
                ident=uid('export');data={'title':report['current']['data']['title'],'status_at_request':report['status'],'source_hash':report['current']['content_hash']}
                c.execute('INSERT INTO export_jobs VALUES(?,?,?,?,?,?,?,?,1,?,NULL,NULL,?,?)',(ident,u['tenant_id'],report['project_id'],report['id'],report['current_version'],u['id'],fmt,'QUEUED',js(data),now(),now()))
                self.host.event(c,u,report['project_id'],'EXPORT_REQUESTED',report['id'],{'export_id':ident,'version':report['current_version'],'format':fmt})
                return self.host.save_receipt(c,'export:'+u['id'],b,{'id':ident,'state':'QUEUED'})
            job=self.export(c,u,s[1])
            if method=='GET':return self.detail(job)
            if s[2]=='retry':
                self.host.version(job,b);require(job['state']=='FAILED','仅失败导出可重试','STATE_CONFLICT',409)
                c.execute("UPDATE export_jobs SET state='QUEUED',error=NULL,version=version+1,updated_at=? WHERE id=?",(now(),job['id']));return {'id':job['id']}
            require(s[2]=='link' and job['state']=='SUCCEEDED','导出尚未完成','STATE_CONFLICT',409)
            token=secrets.token_urlsafe(32);expires=(datetime.now(TZ)+timedelta(minutes=10)).isoformat(timespec='seconds')
            c.execute('INSERT INTO download_tokens VALUES(?,?,?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),job['id'],u['id'],expires,now()))
            self.host.event(c,u,job['project_id'],'EXPORT_LINK_CREATED',job['report_id'],{'export_id':job['id'],'expires_at':expires})
            return {'url':'/api/downloads/'+token,'expires_at':expires}
        if s[0]=='rectifications':
            f=row(c,'SELECT * FROM rectifications WHERE id=?',(s[1],));f['data']=json.loads(f['data'])
            p=self.host.project(c,u,f['project_id']);self.host.knowledge.assert_output(c,u,'report',f['report_id'])
            if s[2]=='related' and method=='GET':return {'items':rows(c,"SELECT id,state,data FROM rectifications WHERE project_id=? AND json_extract(data,'$.parent_fix_id')=?",(f['project_id'],f['id']))}
            scope='fix-extra:'+f['id'];replay=self.host.receipt(c,scope,b)
            if replay:return replay
            self.host.version(f,b)
            if s[2]=='communication':
                require(p['role']=='manager' or f['owner_id']==u['id'],'仅负责人或项目经理可补录沟通','PERMISSION_DENIED',403)
                summary=text(b.get('summary'),'沟通摘要',4000);channel=text(b.get('channel'),'沟通方式',80)
                self.host.event(c,u,f['project_id'],'RECTIFICATION_COMMUNICATION',f['id'],{'comment':summary,'channel':channel,'state_unchanged':f['state']})
                c.execute('UPDATE rectifications SET version=version+1,updated_at=? WHERE id=?',(now(),f['id']))
                return self.host.save_receipt(c,scope,b,{'id':f['id'],'state':f['state']})
            self.host.project(c,u,f['project_id'],{'manager'},True)
            relation=b.get('relation');require(relation in {'SPLIT','FOLLOWUP'},'关联方式无效')
            require(f['state']=='ACCEPTED' if relation=='FOLLOWUP' else f['state'] not in {'ACCEPTED','CANCELLED'},'已验收事项请创建关联跟进；已取消事项不能拆分','STATE_CONFLICT',409)
            reason=text(b.get('reason'),'拆分/跟进说明',2000)
            self.host.member(c,f['project_id'],b.get('owner_id'),{'manager','member','reviewer','knowledge_admin'})
            owner=row(c,'SELECT * FROM users WHERE id=?',(b['owner_id'],));self.host.knowledge.assert_output(c,owner,'report',f['report_id'])
            require(parse_date(b.get('due_date'))>=today(),'截止日期不能早于今天')
            require(b.get('priority') in {'HIGH','MEDIUM','LOW'},'优先级无效')
            item={k:text(b.get(k),label,limit) for k,label,limit in [('title','标题',100),('description','问题描述',2000),('acceptance','验收标准',2000)]}
            item.update(risk_id=f['risk_id'],owner_id=b['owner_id'],due_date=b['due_date'],priority=b['priority'],action_id=digest([u['tenant_id'],f['id'],relation,b['event_key']]),parent_fix_id=f['id'],relation=relation,relation_reason=reason)
            ident=uid('confirm');expires=(datetime.now(TZ)+timedelta(minutes=30)).isoformat(timespec='seconds')
            c.execute('INSERT INTO confirmations VALUES(?,?,?,?,?,?,?,?,?)',(ident,f['project_id'],f['report_id'],f['report_version'],u['id'],digest([item]),js([item]),expires,now()))
            self.host.event(c,u,f['project_id'],'ACTION_PREPARED',f['id'],{'confirmation_id':ident,'relation':relation,'reason':reason})
            return self.host.save_receipt(c,scope,b,{'id':ident,'params_hash':digest([item]),'items':[item],'expires_at':expires,'report_id':f['report_id'],'report_version':f['report_version']})
        if s[0]=='retention':
            pid=query.get('project_id',[''])[0] if method=='GET' else b.get('project_id');self.host.project(c,u,pid,{'manager','knowledge_admin'})
            if method=='GET':return {'items':rows(c,'SELECT d.id,d.title,d.state,r.state AS retention_state,r.purge_after,r.reason,r.completed_at FROM documents d LEFT JOIN retention_jobs r ON r.document_id=d.id WHERE d.project_id=? ORDER BY d.rowid DESC',(pid,)),'default_days':30}
            doc=self.host.knowledge.document(c,u,b.get('document_id'),manage=True)
            require(doc['project_id']==pid and doc['state']=='REMOVED','先下架资料，再安排内容清理','STATE_CONFLICT',409)
            previous=c.execute('SELECT * FROM retention_jobs WHERE document_id=?',(doc['id'],)).fetchone()
            require(not previous or previous['state']=='SCHEDULED','内容已进入清理，不能修改保留计划','STATE_CONFLICT',409)
            days=b.get('days',30);require(type(days) is int and 1<=days<=365,'演示保留期为 1～365 天，不支持立即销毁')
            reason=text(b.get('reason'),'保留/清理原因',2000);cutoff=(datetime.now(TZ)+timedelta(days=days)).isoformat(timespec='seconds')
            c.execute('INSERT INTO retention_jobs VALUES(?,?,?,\'SCHEDULED\',?,?,?,NULL) ON CONFLICT(document_id) DO UPDATE SET actor_id=excluded.actor_id,purge_after=excluded.purge_after,reason=excluded.reason',(doc['id'],pid,u['id'],cutoff,reason,now()))
            self.host.event(c,u,pid,'DOCUMENT_RETENTION_SCHEDULED',doc['id'],{'days':days,'reason':reason,'purge_after':cutoff})
            return {'id':doc['id'],'state':'SCHEDULED','purge_after':cutoff}
        raise BusinessError(404,'NOT_FOUND','接口不存在')

    def download(self,c,u,token):
        t=row(c,'SELECT * FROM download_tokens WHERE token_hash=? AND actor_id=?',(hashlib.sha256(token.encode()).hexdigest(),u['id']))
        require(t['expires_at']>now(),'下载地址已过期，请重新生成','DOWNLOAD_EXPIRED',410)
        j=self.export(c,u,t['export_id']);require(j['state']=='SUCCEEDED' and j['body'] is not None,'导出内容暂不可用','STATE_CONFLICT',409)
        self.host.event(c,u,j['project_id'],'REPORT_EXPORTED',j['report_id'],{'export_id':j['id'],'version':j['report_version'],'format':j['format']})
        return bytes(j['body']),MIME[j['format']],'progress-report.'+j['format']

    def recover(self):
        with self.db.tx() as c:c.execute("UPDATE export_jobs SET state='QUEUED',version=version+1 WHERE state='RUNNING'")

    def process_next(self):
        with self.db.tx() as c:
            removed=c.execute("SELECT d.* FROM documents d WHERE d.state='REMOVED' AND NOT EXISTS(SELECT 1 FROM retention_jobs r WHERE r.document_id=d.id) LIMIT 1").fetchone()
            if removed:
                d=dict(removed);cutoff=(datetime.fromisoformat(d['updated_at'])+timedelta(days=30)).isoformat(timespec='seconds')
                c.execute('INSERT INTO retention_jobs VALUES(?,?,?,\'SCHEDULED\',?,?,?,NULL)',(d['id'],d['project_id'],d['created_by'],cutoff,'下架后默认保留 30 天',now()))
            purge=c.execute("SELECT * FROM retention_jobs WHERE state='SCHEDULED' AND purge_after<=? LIMIT 1",(now(),)).fetchone()
            if purge:
                require(row(c,'SELECT state FROM documents WHERE id=?',(purge['document_id'],))['state']=='REMOVED','清理对象状态已变化','STATE_CONFLICT',409)
                c.execute("UPDATE retention_jobs SET state='PURGING' WHERE document_id=?",(purge['document_id'],))
                c.execute('DELETE FROM knowledge_parents WHERE document_id=?',(purge['document_id'],));c.execute('DELETE FROM knowledge_chunks WHERE document_id=?',(purge['document_id'],))
                c.execute("UPDATE document_versions SET raw=X'',content='',pages='[]',status='PURGED' WHERE document_id=?",(purge['document_id'],))
                c.execute("UPDATE retention_jobs SET state='PURGED',completed_at=? WHERE document_id=?",(now(),purge['document_id']))
                self.host.event(c,{'id':purge['actor_id']},purge['project_id'],'DOCUMENT_CONTENT_PURGED',purge['document_id'],{'metadata_retained':True});return True
            job=c.execute("SELECT * FROM export_jobs WHERE state='QUEUED' ORDER BY rowid LIMIT 1").fetchone()
            if not job:return False
            job=dict(job)
            try:
                u=row(c,'SELECT * FROM users WHERE id=? AND active=1',(job['actor_id'],));r=self.host.report_detail(c,u,job['report_id'])
                selected=next(v for v in r['versions'] if v['version']==job['report_version']);require(selected['content_hash']==json.loads(job['data'])['source_hash'],'导出版本校验失败','VERSION_CONFLICT',409)
                r.update(current=selected,current_version=job['report_version'],status=json.loads(job['data'])['status_at_request'])
                from .exports import report_markdown,report_docx,report_pdf
                body=report_markdown(r,u);body=report_docx(body) if job['format']=='docx' else report_pdf(body) if job['format']=='pdf' else body.encode()
                metadata=json.loads(job['data']);metadata['renderer_version']='pdf-ttf-v1' if job['format']=='pdf' else 'text-v1'
                c.execute("UPDATE export_jobs SET state='SUCCEEDED',body=?,data=?,version=version+1,updated_at=? WHERE id=?",(body,js(metadata),now(),job['id']))
            except Exception as exc:
                message=exc.message if isinstance(exc,BusinessError) else '生成文件失败，已保留导出任务，可重试'
                c.execute("UPDATE export_jobs SET state='FAILED',error=?,version=version+1,updated_at=? WHERE id=?",(message,now(),job['id']))
            return True
