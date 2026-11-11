"""Local inbox subscriptions, reminders, handoff detection and reliable delivery."""
import json
import time
from datetime import datetime,timedelta
from .db import uid,js,now,today,TZ
from .domain import require,BusinessError
from .knowledge import row,rows

KINDS=['report','fix','document','run','analysis','connection','schedule','flow']


class CollaborationFeatures:
    def __init__(self,host):
        self.host,self.db=host,host.db;self.next_check=0

    def settings(self,c,pid):
        found=c.execute('SELECT * FROM reminder_settings WHERE project_id=?',(pid,)).fetchone()
        return dict(found) if found else {'project_id':pid,'review_hours':24,'acceptance_hours':24,'version':0}

    def dispatch(self,c,u,method,path,b,query):
        s=path.strip('/').split('/')[1:];pid=s[1];project=self.host.project(c,u,pid)
        pref=c.execute('SELECT * FROM notice_preferences WHERE project_id=? AND user_id=?',(pid,u['id'])).fetchone()
        preferences={'kinds':json.loads(pref['kinds']) if pref else KINDS,'version':pref['version'] if pref else 0}
        if method=='GET':
            handoffs=[];outbox=[]
            if project['role']=='manager':
                for a in rows(c,"SELECT a.*,r.id AS report_id FROM approvals a JOIN reports r ON r.id=a.report_id WHERE r.project_id=? AND a.state='PENDING' AND r.approval_id=a.id",(pid,)):
                    data=json.loads(a['data'])
                    if data.get('needs_transfer') and self.host.knowledge.output_allowed(c,u,'report',a['report_id']):handoffs.append({'approval_id':a['id'],'report_id':a['report_id'],'reviewer_id':a['reviewer_id'],'reason':data['transfer_reason'],'detected_at':data['transfer_detected_at']})
                outbox=rows(c,'SELECT event_id,action,object_id,state,attempts,next_at,error,created_at FROM notification_outbox WHERE project_id=? ORDER BY rowid DESC LIMIT 30',(pid,))
            return {'settings':self.settings(c,pid),'preferences':preferences,'kinds':KINDS,'handoffs':handoffs,'outbox':outbox,'can_manage':project['role']=='manager'}
        if len(s)==3:
            require(b.get('expected_version')==preferences['version'],'订阅设置已更新，请刷新','VERSION_CONFLICT',409)
            kinds=b.get('kinds');require(isinstance(kinds,list) and set(kinds)<=set(KINDS),'订阅类型无效')
            c.execute('INSERT INTO notice_preferences VALUES(?,?,?,1) ON CONFLICT(project_id,user_id) DO UPDATE SET kinds=excluded.kinds,version=notice_preferences.version+1',(pid,u['id'],js(kinds)))
            self.host.event(c,u,pid,'NOTICE_PREFERENCES_UPDATED',u['id'],{'kinds':kinds});return {'state':'SAVED'}
        self.host.project(c,u,pid,{'manager'})
        if s[3]=='settings':
            settings=self.settings(c,pid);self.host.version(settings,b)
            for field in ['review_hours','acceptance_hours']:require(type(b.get(field)) is int and 1<=b[field]<=168,'提醒等待时长应为 1～168 小时')
            c.execute('INSERT INTO reminder_settings VALUES(?,?,?,1) ON CONFLICT(project_id) DO UPDATE SET review_hours=excluded.review_hours,acceptance_hours=excluded.acceptance_hours,version=reminder_settings.version+1',(pid,b['review_hours'],b['acceptance_hours']))
            self.host.event(c,u,pid,'REMINDER_SETTINGS_UPDATED',pid,{k:b[k] for k in ['review_hours','acceptance_hours']});self.next_check=0;return {'state':'SAVED'}
        if s[3]=='check':
            self.check_project(c,pid);return {'state':'CHECKED'}
        if s[3]=='retry' and len(s)==5:
            job=row(c,"SELECT * FROM notification_outbox WHERE event_id=? AND project_id=? AND state='FAILED'",(s[4],pid))
            c.execute("UPDATE notification_outbox SET state='QUEUED',next_at=?,error=NULL WHERE event_id=?",(now(),job['event_id']));return {'state':'QUEUED'}
        raise BusinessError(404,'NOT_FOUND','提醒接口不存在')

    def mark(self,c,u,pid,rule,objkey,action,obj,data):
        bucket=today().isoformat()
        if c.execute('SELECT 1 FROM reminder_marks WHERE project_id=? AND rule=? AND object_key=? AND bucket=?',(pid,rule,objkey,bucket)).fetchone():return
        marker=uid('reminder')
        c.execute('INSERT INTO reminder_marks VALUES(?,?,?,?,?,?)',(pid,rule,objkey,bucket,marker,now()))
        self.host.event(c,u,pid,action,obj,{**data,'reminder_id':marker,'rule':rule})

    def check_project(self,c,pid):
        settings=self.settings(c,pid)
        managers=rows(c,"SELECT u.* FROM users u JOIN memberships m ON m.user_id=u.id WHERE m.project_id=? AND m.role='manager' AND u.active=1",(pid,))
        if not managers:return
        operator=managers[0]
        for a in rows(c,"SELECT a.*,r.id AS report_id FROM approvals a JOIN reports r ON r.id=a.report_id WHERE r.project_id=? AND r.approval_id=a.id AND a.state='PENDING'",(pid,)):
            data=json.loads(a['data']);valid=True
            try:
                self.host.member(c,pid,a['reviewer_id'],{'manager','reviewer'})
                reviewer=row(c,'SELECT * FROM users WHERE id=?',(a['reviewer_id'],));self.host.knowledge.assert_output(c,reviewer,'report',a['report_id'])
            except BusinessError:valid=False
            if not valid and not data.get('needs_transfer'):
                data.update(needs_transfer=True,transfer_reason='指定审核人的账号、项目角色或来源访问权已失效',transfer_detected_at=now())
                c.execute('UPDATE approvals SET data=?,version=version+1 WHERE id=?',(js(data),a['id']))
                self.host.event(c,operator,pid,'REVIEW_NEEDS_TRANSFER',a['report_id'],{'approval_id':a['id']})
            if not valid or data.get('needs_transfer'):continue
            transferred=c.execute("SELECT created_at FROM events WHERE object_id=? AND action='REVIEW_TRANSFERRED' ORDER BY rowid DESC LIMIT 1",(a['report_id'],)).fetchone()
            since=transferred['created_at'] if transferred else a['created_at']
            age=(datetime.now(TZ)-datetime.fromisoformat(since)).total_seconds()/3600
            if age>=settings['review_hours']:self.mark(c,operator,pid,'REVIEW_DUE',a['id']+':'+a['reviewer_id'],'REVIEW_REMINDER',a['report_id'],{'approval_id':a['id'],'long_wait':False})
            if age>=168:self.mark(c,operator,pid,'REVIEW_LONG',a['id']+':'+a['reviewer_id'],'REVIEW_REMINDER',a['report_id'],{'approval_id':a['id'],'long_wait':True})
        for task in rows(c,"SELECT * FROM rectifications WHERE project_id=? AND state NOT IN ('ACCEPTED','CANCELLED')",(pid,)):
            data=json.loads(task['data'])
            valid=True
            try:
                self.host.member(c,pid,task['owner_id'],{'manager','member','reviewer','knowledge_admin'})
                owner=row(c,'SELECT * FROM users WHERE id=?',(task['owner_id'],));self.host.knowledge.assert_output(c,owner,'report',task['report_id'])
            except BusinessError:valid=False
            if not valid and not data.get('needs_assignment'):
                data.update(needs_assignment=True,assignment_reason='负责人账号、项目身份或来源访问权限已失效',assignment_detected_at=now())
                c.execute('UPDATE rectifications SET data=?,version=version+1,updated_at=? WHERE id=?',(js(data),now(),task['id']))
                self.host.event(c,operator,pid,'FIX_NEEDS_ASSIGNMENT',task['id'],{'reason':data['assignment_reason']})
            if task['state'] in {'TODO','IN_PROGRESS','REWORK'} and data['due_date']<today().isoformat():self.mark(c,operator,pid,'FIX_OVERDUE',task['id'],'FIX_REMINDER',task['id'],{'waiting_acceptance':False})
            if task['state']=='PENDING_ACCEPTANCE':
                submitted=c.execute("SELECT created_at FROM events WHERE object_id=? AND action='RECTIFICATION_SUBMIT' ORDER BY rowid DESC LIMIT 1",(task['id'],)).fetchone()
                if submitted and datetime.now(TZ)-datetime.fromisoformat(submitted['created_at'])>=timedelta(hours=settings['acceptance_hours']):self.mark(c,operator,pid,'ACCEPTANCE_DUE',task['id'],'FIX_REMINDER',task['id'],{'waiting_acceptance':True})
        for v in rows(c,"SELECT v.document_id,v.version,d.created_by FROM document_versions v JOIN documents d ON d.id=v.document_id WHERE d.project_id=? AND d.state='ACTIVE' AND v.status='FAILED'",(pid,)):
            self.mark(c,operator,pid,'PARSE_FAILED',v['document_id']+':'+str(v['version']),'DOCUMENT_PARSE_FAILED',v['document_id'],{'document_version':v['version']})
        for flow in rows(c,"SELECT * FROM flow_runs WHERE project_id=? AND state='WAITING_REVIEW'",(pid,)):
            data=json.loads(flow['data']);valid=True
            try:
                self.host.member(c,pid,flow['reviewer_id'],{'manager','reviewer'});reviewer=row(c,'SELECT * FROM users WHERE id=?',(flow['reviewer_id'],));self.host.knowledge.assert_refs(c,reviewer,data['document_refs'])
            except BusinessError:valid=False
            if not valid and not data.get('needs_transfer'):
                data['needs_transfer']=True;c.execute('UPDATE flow_runs SET data=?,version=version+1,updated_at=? WHERE id=?',(js(data),now(),flow['id']))
                self.host.event(c,operator,pid,'FLOW_NEEDS_TRANSFER',flow['id'],{})

    def process_next(self):
        if time.monotonic()>=self.next_check:
            self.next_check=time.monotonic()+30
            with self.db.tx() as c:
                for p in rows(c,'SELECT id FROM projects'):self.check_project(c,p['id'])
        with self.db.tx() as c:
            job=c.execute("SELECT * FROM notification_outbox WHERE state='QUEUED' AND next_at<=? ORDER BY rowid LIMIT 1",(now(),)).fetchone()
            if not job:return False
            job=dict(job);c.execute('SAVEPOINT deliver_notice')
            try:
                self.host.platform.deliver_event(c,job)
                c.execute('RELEASE deliver_notice')
                c.execute("UPDATE notification_outbox SET state='DELIVERED',attempts=attempts+1,error=NULL,updated_at=? WHERE event_id=?",(now(),job['event_id']))
            except Exception:
                c.execute('ROLLBACK TO deliver_notice');c.execute('RELEASE deliver_notice')
                attempts=job['attempts']+1
                next_at=(datetime.now(TZ)+timedelta(seconds=2 if attempts==1 else 5 if attempts==2 else 30)).isoformat(timespec='seconds')
                c.execute('UPDATE notification_outbox SET state=?,attempts=?,next_at=?,error=?,updated_at=? WHERE event_id=?',('FAILED' if attempts>=5 else 'QUEUED',attempts,next_at,'通知暂未送达，业务状态已保留；可由项目经理重投',now(),job['event_id']))
            return True
