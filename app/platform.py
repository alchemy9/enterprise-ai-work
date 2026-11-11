"""Server-authorized account/project administration and persistent notifications."""
import json
import re
import secrets
from .db import uid,js,now,password_hash
from .domain import BusinessError,require,text,parse_date
from .knowledge import row,rows

SYSTEM_ROLES={'enterprise_admin','operations','tool_admin','audit'}


class Platform:
    def __init__(self,host):
        self.host,self.db=host,host.db
        with self.db.tx() as c:
            # Demo project manager explicitly also holds platform capabilities.
            if c.execute("SELECT 1 FROM users WHERE id='u_manager'").fetchone():
                c.execute('INSERT OR IGNORE INTO system_roles VALUES(?,?,?)',('u_manager',js(sorted(SYSTEM_ROLES)),1))
            for u in rows(c,'SELECT id FROM users'):
                c.execute('INSERT OR IGNORE INTO system_roles VALUES(?,?,1)',(u['id'],'[]'))

    def roles(self,c,u):
        found=c.execute('SELECT roles FROM system_roles WHERE user_id=?',(u['id'],)).fetchone()
        return json.loads(found['roles']) if found else []

    def authorize(self,c,u,role='enterprise_admin'):
        require(role in self.roles(c,u),'当前账号没有此管理权限','PERMISSION_DENIED',403)

    def audit(self,c,u,action,ident,data=None,pid=''):
        c.execute('INSERT INTO platform_audit VALUES(?,?,?,?,?,?,?,?)',(uid('audit'),u['tenant_id'],pid,u['id'],action,ident,js(data or {}),now()))

    def user_list(self,c,u):
        return [{**item,'roles':json.loads(item['roles'] or '[]')} for item in rows(c,'SELECT u.id,u.username,u.name,u.active,r.roles,coalesce(r.version,1) AS version FROM users u LEFT JOIN system_roles r ON r.user_id=u.id WHERE u.tenant_id=? ORDER BY u.rowid',(u['tenant_id'],))]

    def artifacts(self,c,u):
        result=[]
        for project in rows(c,'SELECT p.id,p.name,m.role FROM memberships m JOIN projects p ON p.id=m.project_id WHERE m.user_id=? AND p.tenant_id=?',(u['id'],u['tenant_id'])):
            for report in rows(c,'SELECT r.*,w.created_at,v.author_id,u.name AS author_name FROM reports r JOIN runs w ON w.id=r.run_id JOIN report_versions v ON v.report_id=r.id AND v.version=r.current_version JOIN users u ON u.id=v.author_id WHERE r.project_id=?',(project['id'],)):
                if report['status'] not in {'PUBLISHED','SUPERSEDED'} and project['role'] not in {'manager','reviewer'}:continue
                if not self.host.knowledge.output_allowed(c,u,'report',report['id']):continue
                result.append({'id':report['id'],'type':'REPORT','title':'项目进度汇总','project_id':project['id'],'project_name':project['name'],'author_id':report['author_id'],'author_name':report['author_name'],'state':report['status'],'version':report['current_version'],'created_at':report['created_at'],'url':'#/reports/'+report['id']})
            for q in rows(c,"SELECT id,question,answer_status,created_at FROM questions WHERE project_id=? AND actor_id=? AND state='COMPLETED'",(project['id'],u['id'])):
                if self.host.knowledge.output_allowed(c,u,'question',q['id']):result.append({'id':q['id'],'type':'QUESTION','title':q['question'],'project_id':project['id'],'project_name':project['name'],'author_id':u['id'],'author_name':u['name'],'state':q['answer_status'],'version':1,'created_at':q['created_at'],'url':'#/questions/'+q['id']})
        for item in result:
            item['bookmarked']=bool(c.execute('SELECT 1 FROM bookmarks WHERE user_id=? AND object_type=? AND object_id=?',(u['id'],item['type'],item['id'])).fetchone())
        return sorted(result,key=lambda x:x['created_at'],reverse=True)

    def dispatch(self,c,u,method,path,b,query):
        s=path.strip('/').split('/')[1:]
        if s==['artifacts'] and method=='GET':
            result=self.artifacts(c,u)
            for field,key in [('project_id','project_id'),('type','type'),('state','state')]:
                value=query.get(field,[''])[0]
                if value:result=[x for x in result if x[key]==value]
            search=query.get('search',[''])[0]
            if search:result=[x for x in result if search.lower() in x['title'].lower()]
            author=query.get('author',[''])[0]
            if author:result=[x for x in result if author.lower() in (x['author_name']+' '+x['author_id']).lower()]
            for datefield in ['date_from','date_to']:
                datevalue=query.get(datefield,[''])[0]
                if datevalue:
                    parse_date(datevalue);result=[x for x in result if (x['created_at'][:10]>=datevalue if datefield=='date_from' else x['created_at'][:10]<=datevalue)]
            if query.get('bookmarked',[''])[0]=='1':result=[x for x in result if x['bookmarked']]
            try:page=max(1,int(query.get('page',['1'])[0]))
            except ValueError:raise BusinessError(400,'INPUT_INVALID','页码无效')
            return {'items':result[(page-1)*20:page*20],'total':len(result),'page':page,'page_size':20}
        if s==['bookmarks'] and method=='POST':
            require(type(b.get('bookmarked')) is bool,'收藏状态无效')
            item=next((x for x in self.artifacts(c,u) if x['id']==b.get('object_id') and x['type']==b.get('object_type')),None)
            require(item is not None,'成果不存在或不可访问','PERMISSION_DENIED',403)
            if b['bookmarked']:c.execute('INSERT OR IGNORE INTO bookmarks VALUES(?,?,?,?)',(u['id'],item['type'],item['id'],now()))
            else:c.execute('DELETE FROM bookmarks WHERE user_id=? AND object_type=? AND object_id=?',(u['id'],item['type'],item['id']))
            return {'id':item['id'],'bookmarked':b['bookmarked']}
        if s==['admin','overview'] and method=='GET':
            self.authorize(c,u)
            return {'users':self.user_list(c,u),'projects':rows(c,'SELECT p.*,(SELECT name FROM users u JOIN memberships m ON m.user_id=u.id WHERE m.project_id=p.id AND m.role=\'manager\' LIMIT 1) AS manager_name,(SELECT count(*) FROM memberships m WHERE m.project_id=p.id) AS member_count FROM projects p WHERE tenant_id=? ORDER BY rowid DESC',(u['tenant_id'],)),'roles':sorted(SYSTEM_ROLES)}
        if len(s)==4 and s[:2]==['admin','projects'] and s[3]=='members':
            self.authorize(c,u)
            project=row(c,'SELECT id FROM projects WHERE id=? AND tenant_id=?',(s[2],u['tenant_id']))
            if method=='GET':
                return {'members':rows(c,'SELECT u.id,u.username,u.name,u.active,m.role FROM memberships m JOIN users u ON u.id=m.user_id WHERE m.project_id=?',(project['id'],)),'available_users':self.user_list(c,u)}
            target=row(c,'SELECT id FROM users WHERE id=? AND tenant_id=? AND active=1',(b.get('user_id'),u['tenant_id']))
            role=b.get('role')
            require(role in {'manager','member','reviewer','knowledge_admin'},'项目角色无效')
            old=c.execute('SELECT role FROM memberships WHERE project_id=? AND user_id=?',(project['id'],target['id'])).fetchone()
            if old and old['role']=='manager' and role!='manager':
                other=c.execute("SELECT count(*) FROM memberships m JOIN users u ON u.id=m.user_id WHERE m.project_id=? AND m.role='manager' AND u.active=1 AND m.user_id!=?",(project['id'],target['id'])).fetchone()[0]
                require(other>0,'请先指定另一位有效项目经理')
            c.execute('INSERT INTO memberships VALUES(?,?,?) ON CONFLICT(project_id,user_id) DO UPDATE SET role=excluded.role',(project['id'],target['id'],role))
            self.audit(c,u,'PROJECT_MEMBER_AUTHORIZED',target['id'],{'project_id':project['id'],'role':role})
            return {'id':target['id'],'role':role}
        if len(s)>=2 and s[:2]==['admin','users']:
            self.authorize(c,u)
            if len(s)==2 and method=='POST':
                username=text(b.get('username'),'账号',40)
                require(re.fullmatch(r'[a-zA-Z][a-zA-Z0-9_.-]{2,39}',username),'账号需以字母开头，3～40 位字母、数字或 ._-')
                name=text(b.get('name'),'显示名',100)
                password=text(b.get('password'),'密码',200)
                require(len(password)>=8,'密码至少 8 位')
                require(not c.execute('SELECT 1 FROM users WHERE username=?',(username,)).fetchone(),'账号已存在','DUPLICATE_USER',409)
                roles=b.get('roles',[])
                require(isinstance(roles,list) and set(roles)<=SYSTEM_ROLES,'系统角色无效')
                ident,salt=uid('user'),secrets.token_hex(16)
                c.execute('INSERT INTO users VALUES(?,?,?,?,?,?,1)',(ident,u['tenant_id'],username,name,salt,password_hash(password,salt)))
                c.execute('INSERT INTO system_roles VALUES(?,?,1)',(ident,js(roles)))
                self.audit(c,u,'USER_CREATED',ident,{'username':username,'roles':roles})
                return {'id':ident}
            if len(s)==3 and method=='POST':
                target=row(c,'SELECT u.*,coalesce(r.version,1) AS version,r.roles FROM users u LEFT JOIN system_roles r ON r.user_id=u.id WHERE u.id=? AND u.tenant_id=?',(s[2],u['tenant_id']))
                self.host.version(target,b)
                active=b.get('active',bool(target['active']))
                require(type(active) is bool,'账号状态必须为布尔值')
                roles=b.get('roles',json.loads(target['roles'] or '[]'))
                require(isinstance(roles,list) and set(roles)<=SYSTEM_ROLES,'系统角色无效')
                if 'enterprise_admin' in json.loads(target['roles'] or '[]') and (not active or 'enterprise_admin' not in roles):
                    other=[x for x in self.user_list(c,u) if x['id']!=target['id'] and x['active'] and 'enterprise_admin' in x['roles']]
                    require(bool(other),'最后一位有效企业管理员不能被停用或移除管理权限','LAST_ADMIN',409)
                name=text(b.get('name',target['name']),'显示名',100)
                c.execute('UPDATE users SET name=?,active=? WHERE id=?',(name,int(active),target['id']))
                c.execute('INSERT INTO system_roles VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET roles=excluded.roles,version=system_roles.version+1',(target['id'],js(roles),target['version']+1))
                if not active:
                    c.execute('DELETE FROM sessions WHERE user_id=?',(target['id'],))
                self.host.collaboration.next_check=0
                self.audit(c,u,'USER_UPDATED',target['id'],{'active':active,'roles':roles})
                return {'id':target['id'],'version':target['version']+1}
        if s==['projects'] and method=='POST':
            self.authorize(c,u)
            name=text(b.get('name'),'项目名称',100)
            code=text(b.get('code'),'项目编号',40)
            description=b.get('description','')
            require(isinstance(description,str) and len(description)<=2000,'项目说明最多 2000 字')
            manager=row(c,'SELECT id FROM users WHERE id=? AND tenant_id=? AND active=1',(b.get('manager_id'),u['tenant_id']))
            require(not c.execute('SELECT 1 FROM projects WHERE tenant_id=? AND code=?',(u['tenant_id'],code)).fetchone(),'项目编号已存在','DUPLICATE_PROJECT',409)
            ident=uid('project')
            c.execute('INSERT INTO projects(id,tenant_id,name,code,description) VALUES(?,?,?,?,?)',(ident,u['tenant_id'],name,code,description))
            c.execute('INSERT INTO memberships VALUES(?,?,?)',(ident,manager['id'],'manager'))
            c.execute('INSERT INTO knowledge_libraries VALUES(?,?,?,?,?)',(uid('lib'),ident,'项目资料','默认项目知识库',now()))
            self.audit(c,u,'PROJECT_CREATED',ident,{'manager_id':manager['id'],'code':code})
            return {'id':ident}
        if len(s)==3 and s[0]=='projects' and s[2]=='settings':
            pid=s[1]
            p=self.host.project(c,u,pid,{'manager'})
            stored=c.execute('SELECT data FROM project_settings WHERE project_id=?',(pid,)).fetchone()
            settings=json.loads(stored['data']) if stored else {'timezone':'Asia/Shanghai','planned_start':'','planned_end':''}
            if method=='GET':return {'project':p,'settings':settings}
            self.host.version(p,b)
            name=text(b.get('name'),'项目名称',100);code=text(b.get('code'),'项目编号',40)
            description=b.get('description','')
            require(isinstance(description,str) and len(description)<=2000,'项目说明最多 2000 字')
            require(not c.execute('SELECT 1 FROM projects WHERE tenant_id=? AND code=? AND id!=?',(u['tenant_id'],code,pid)).fetchone(),'项目编号已存在','DUPLICATE_PROJECT',409)
            start=b.get('planned_start','');end=b.get('planned_end','')
            if start:parse_date(start)
            if end:parse_date(end)
            require(not start or not end or start<=end,'计划结束日期不能早于开始日期')
            c.execute('UPDATE projects SET name=?,code=?,description=?,version=version+1 WHERE id=?',(name,code,description,pid))
            settings={'timezone':'Asia/Shanghai','planned_start':start,'planned_end':end}
            c.execute('INSERT INTO project_settings VALUES(?,?) ON CONFLICT(project_id) DO UPDATE SET data=excluded.data',(pid,js(settings)))
            self.host.event(c,u,pid,'PROJECT_UPDATED',pid,{'name':name,'code':code})
            return {'id':pid,'version':p['version']+1}
        if len(s)>=3 and s[0]=='projects' and s[2]=='members':
            pid=s[1]
            self.host.project(c,u,pid,{'manager'})
            if method=='GET':
                return {'members':rows(c,'SELECT u.id,u.username,u.name,u.active,m.role FROM memberships m JOIN users u ON u.id=m.user_id WHERE m.project_id=?',(pid,)),'available_users':[{'id':x['id'],'name':x['name'],'username':x['username']} for x in self.user_list(c,u) if x['active']]}
            if method=='POST' and len(s)==3:
                target=row(c,'SELECT id FROM users WHERE id=? AND tenant_id=? AND active=1',(b.get('user_id'),u['tenant_id']))
                role=b.get('role')
                require(role in {'manager','member','reviewer','knowledge_admin'},'项目角色无效')
                current=c.execute('SELECT role FROM memberships WHERE project_id=? AND user_id=?',(pid,target['id'])).fetchone()
                if current and current['role']=='manager' and role!='manager':
                    require(c.execute("SELECT count(*) FROM memberships m JOIN users u ON u.id=m.user_id WHERE m.project_id=? AND m.role='manager' AND u.active=1",(pid,)).fetchone()[0]>1,'请先指定另一位项目经理')
                c.execute('INSERT INTO memberships VALUES(?,?,?) ON CONFLICT(project_id,user_id) DO UPDATE SET role=excluded.role',(pid,target['id'],role))
                self.host.event(c,u,pid,'MEMBER_GRANTED',target['id'],{'role':role})
                return {'id':target['id'],'role':role}
            if method=='POST' and len(s)==5 and s[4]=='remove':
                target=row(c,'SELECT u.id,u.name,u.active,m.role FROM users u JOIN memberships m ON m.user_id=u.id JOIN projects p ON p.id=m.project_id WHERE m.project_id=? AND u.id=? AND u.tenant_id=p.tenant_id',(pid,s[3]))
                if target['role']=='manager':
                    require(c.execute("SELECT count(*) FROM memberships m JOIN users u ON u.id=m.user_id WHERE m.project_id=? AND m.role='manager' AND u.active=1 AND u.id!=?",(pid,target['id'])).fetchone()[0]>=1,'不能移除最后一位有效项目经理')
                pending=rows(c,"SELECT * FROM rectifications WHERE project_id=? AND owner_id=? AND state NOT IN ('ACCEPTED','CANCELLED')",(pid,target['id']))
                approvals=rows(c,"SELECT a.* FROM approvals a JOIN reports r ON r.id=a.report_id WHERE r.project_id=? AND a.reviewer_id=? AND a.state='PENDING'",(pid,target['id']))
                if pending or approvals:
                    successor=b.get('transfer_to')
                    require(successor and successor!=target['id'],'该成员有未完成事项，请指定有效移交人','HANDOFF_REQUIRED',409,{'rectifications':len(pending),'approvals':len(approvals)})
                    person=self.host.member(c,pid,successor,{'manager','member','reviewer','knowledge_admin'})
                    if approvals:
                        require(person['role'] in {'manager','reviewer'},'移交人必须具有审核权限')
                    for task in pending:
                        target_user=row(c,'SELECT * FROM users WHERE id=?',(successor,))
                        self.host.knowledge.assert_output(c,target_user,'report',task['report_id'])
                        data=json.loads(task['data']);data['owner_id']=successor
                        for field in ['needs_assignment','assignment_reason','assignment_detected_at']:data.pop(field,None)
                        c.execute('UPDATE rectifications SET owner_id=?,data=?,version=version+1,updated_at=? WHERE id=?',(successor,js(data),now(),task['id']))
                        self.host.event(c,u,pid,'RECTIFICATION_REASSIGN',task['id'],{'old_owner':target['id'],'new_owner':successor,'comment':'成员退出项目，明确移交'})
                    for approval in approvals:
                        target_user=row(c,'SELECT * FROM users WHERE id=?',(successor,))
                        self.host.knowledge.assert_output(c,target_user,'report',approval['report_id'])
                        ad=json.loads(approval['data'])
                        for field in ['needs_transfer','transfer_reason','transfer_detected_at']:ad.pop(field,None)
                        c.execute('UPDATE approvals SET reviewer_id=?,data=?,version=version+1 WHERE id=?',(successor,js(ad),approval['id']))
                        self.host.event(c,u,pid,'REVIEW_TRANSFERRED',approval['report_id'],{'reviewer_id':successor,'reason':'成员退出项目'})
                c.execute('DELETE FROM memberships WHERE project_id=? AND user_id=?',(pid,target['id']))
                self.host.event(c,u,pid,'MEMBER_REMOVED',target['id'])
                return {'id':target['id'],'removed':True}
        if len(s)==3 and s[0]=='approvals' and s[2]=='transfer' and method=='POST':
            approval=row(c,'SELECT * FROM approvals WHERE id=?',(s[1],))
            report=self.host.report(c,u,approval['report_id'])
            self.host.project(c,u,report['project_id'],{'manager'})
            self.host.version(approval,b)
            require(approval['state']=='PENDING','审核单已结束，不能转交','STATE_CONFLICT',409)
            self.host.member(c,report['project_id'],b.get('reviewer_id'),{'manager','reviewer'})
            target=row(c,'SELECT * FROM users WHERE id=?',(b['reviewer_id'],))
            self.host.knowledge.assert_output(c,target,'report',report['id'])
            reason=text(b.get('reason'),'转交原因')
            ad=json.loads(approval['data'])
            for field in ['needs_transfer','transfer_reason','transfer_detected_at']:ad.pop(field,None)
            c.execute('UPDATE approvals SET reviewer_id=?,data=?,version=version+1 WHERE id=?',(b['reviewer_id'],js(ad),approval['id']))
            self.host.event(c,u,report['project_id'],'REVIEW_TRANSFERRED',report['id'],{'reviewer_id':b['reviewer_id'],'reason':reason})
            return {'id':approval['id'],'reviewer_id':b['reviewer_id']}
        if s==['todos'] and method=='GET':
            result=[]
            for project in rows(c,'SELECT p.id,p.name,m.role FROM memberships m JOIN projects p ON p.id=m.project_id WHERE m.user_id=? AND p.tenant_id=?',(u['id'],u['tenant_id'])):
                pid=project['id']
                for fr in rows(c,"SELECT id FROM flow_runs WHERE project_id=? AND reviewer_id=? AND state='WAITING_REVIEW'",(pid,u['id'])):
                    try:self.host.flows.run(c,u,fr['id'])
                    except BusinessError:continue
                    result.append({'id':fr['id'],'kind':'FLOW_REVIEW','title':'核对编排分析成果','project_id':pid,'project_name':project['name'],'url':'#/flow-runs/'+fr['id'],'state':'待确认'})
                for a in rows(c,"SELECT a.id,a.data,r.id AS report_id,r.current_version FROM approvals a JOIN reports r ON r.id=a.report_id WHERE r.project_id=? AND a.reviewer_id=? AND a.state='PENDING' AND r.approval_id=a.id",(pid,u['id'])):
                    if json.loads(a['data']).get('needs_transfer'):continue
                    if self.host.knowledge.output_allowed(c,u,'report',a['report_id']):result.append({'id':a['id'],'kind':'REVIEW','title':f"审核项目进度报告 v{a['current_version']}",'project_id':pid,'project_name':project['name'],'url':'#/reports/'+a['report_id'],'state':'待审核'})
                if project['role']=='manager':
                    for fr in rows(c,"SELECT id,data FROM flow_runs WHERE project_id=? AND state='WAITING_REVIEW'",(pid,)):
                        if json.loads(fr['data']).get('needs_transfer'):
                            try:self.host.flows.run(c,u,fr['id'])
                            except BusinessError:continue
                            result.append({'id':fr['id'],'kind':'REVIEW_HANDOFF','title':'编排确认人失效，请转交','project_id':pid,'project_name':project['name'],'url':'#/flow-runs/'+fr['id'],'state':'待转交'})
                    for a in rows(c,"SELECT a.id,a.data,r.id AS report_id FROM approvals a JOIN reports r ON r.id=a.report_id WHERE r.project_id=? AND a.state='PENDING' AND r.approval_id=a.id",(pid,)):
                        if json.loads(a['data']).get('needs_transfer') and self.host.knowledge.output_allowed(c,u,'report',a['report_id']):result.append({'id':a['id'],'kind':'REVIEW_HANDOFF','title':'审核人失效，请转交报告审核','project_id':pid,'project_name':project['name'],'url':'#/reports/'+a['report_id'],'state':'待转交'})
                for f in rows(c,"SELECT * FROM rectifications WHERE project_id=? AND state NOT IN ('ACCEPTED','CANCELLED')",(pid,)):
                    if not self.host.knowledge.output_allowed(c,u,'report',f['report_id']):continue
                    if project['role']=='manager' and json.loads(f['data']).get('needs_assignment'):
                        result.append({'id':f['id'],'kind':'RECTIFICATION_HANDOFF','title':'负责人失效，整改等待改派','project_id':pid,'project_name':project['name'],'url':'#/fixes/'+f['id'],'state':'待分配'});continue
                    if f['owner_id']==u['id'] or project['role']=='manager' and f['state']=='PENDING_ACCEPTANCE':
                        data=json.loads(f['data'])
                        result.append({'id':f['id'],'kind':'ACCEPTANCE' if f['state']=='PENDING_ACCEPTANCE' and f['owner_id']!=u['id'] else 'RECTIFICATION','title':data['title'],'project_id':pid,'project_name':project['name'],'url':'#/fixes/'+f['id'],'state':f['state'],'due_date':data['due_date']})
            return {'items':result}
        if s==['notifications'] and method=='GET':
            result=[]
            for item in rows(c,'SELECT * FROM notifications WHERE user_id=? ORDER BY rowid DESC LIMIT 200',(u['id'],)):
                accessible=True
                try:
                    self.host.project(c,u,item['project_id'])
                    if item['object_type']=='report':self.host.report(c,u,item['object_id'])
                    if item['object_type']=='run':self.host.run(c,u,item['object_id'])
                    if item['object_type']=='document':self.host.knowledge.document(c,u,item['object_id'])
                    if item['object_type']=='analysis':self.host.advanced.analysis(c,u,item['object_id'])
                    if item['object_type']=='connection':self.host.advanced.connection(c,u,item['object_id'])
                    if item['object_type']=='schedule':self.host.advanced.schedule(c,u,item['object_id'])
                    if item['object_type']=='flow':self.host.flows.run(c,u,item['object_id'])
                    if item['object_type']=='fix':
                        fix=row(c,'SELECT report_id FROM rectifications WHERE id=?',(item['object_id'],))
                        self.host.knowledge.assert_output(c,u,'report',fix['report_id'])
                except BusinessError:accessible=False
                result.append({**item,'accessible':accessible,'title':item['title'] if accessible else '事项已不可访问'})
            return {'items':result,'unread':sum(x['read_at'] is None for x in result)}
        if len(s)==3 and s[0]=='notifications' and s[2]=='read' and method=='POST':
            notice=row(c,'SELECT id FROM notifications WHERE id=? AND user_id=?',(s[1],u['id']))
            c.execute('UPDATE notifications SET read_at=coalesce(read_at,?) WHERE id=?',(now(),notice['id']))
            return {'id':notice['id'],'read':True}
        if s==['admin','audit'] and method=='GET':
            self.authorize(c,u,'audit')
            records=[]
            where=['a.tenant_id=?'];params=[u['tenant_id']]
            for key,column in [('project_id','a.project_id'),('actor_id','a.actor_id'),('object_id','a.object_id')]:
                value=query.get(key,[''])[0]
                if value:where.append(column+'=?');params.append(value)
            action=query.get('action',[''])[0]
            if action:where.append('instr(a.action,?)>0');params.append(action)
            for key,op in [('date_from','>='),('date_to','<=')]:
                value=query.get(key,[''])[0]
                if value:parse_date(value);where.append('substr(a.created_at,1,10)'+op+'?');params.append(value)
            for item in rows(c,'SELECT a.*,u.name AS actor_name FROM platform_audit a JOIN users u ON u.id=a.actor_id WHERE '+' AND '.join(where)+' ORDER BY a.rowid DESC LIMIT 500',tuple(params)):
                data=json.loads(item['data'])
                if item['project_id']:
                    try:
                        self.host.project(c,u,item['project_id'])
                        if item['action'].startswith(('DOCUMENT_','EVIDENCE_')):
                            require(self.host.knowledge.can_read(c,u,item['object_id']),'资料受限')
                        report=c.execute('SELECT id FROM reports WHERE id=?',(item['object_id'],)).fetchone()
                        fix=c.execute('SELECT report_id FROM rectifications WHERE id=?',(item['object_id'],)).fetchone()
                        if report:self.host.knowledge.assert_output(c,u,'report',report['id'])
                        if fix:self.host.knowledge.assert_output(c,u,'report',fix['report_id'])
                        question=c.execute('SELECT id FROM questions WHERE id=?',(item['object_id'],)).fetchone()
                        feedback=c.execute('SELECT question_id FROM question_feedback WHERE id=?',(item['object_id'],)).fetchone()
                        analysis=c.execute('SELECT id FROM analyses WHERE id=?',(item['object_id'],)).fetchone()
                        if question:self.host.knowledge.assert_output(c,u,'question',question['id'])
                        if feedback:self.host.knowledge.assert_output(c,u,'question',feedback['question_id'])
                        if analysis:self.host.advanced.analysis(c,u,analysis['id'])
                    except BusinessError:data={'restricted':True}
                item['data']=data;records.append(item)
            return {'items':records}
        raise BusinessError(404,'NOT_FOUND','管理接口不存在')

    def on_event(self,c,u,pid,action,obj,data,eid):
        tenant=row(c,'SELECT tenant_id FROM projects WHERE id=?',(pid,))['tenant_id']
        c.execute('INSERT OR IGNORE INTO platform_audit VALUES(?,?,?,?,?,?,?,?)',(eid,tenant,pid,u['id'],action,obj,js(data),now()))
        c.execute("INSERT OR IGNORE INTO notification_outbox(event_id,project_id,actor_id,action,object_id,data,state,next_at,created_at,updated_at) VALUES(?,?,?,?,?,?,'QUEUED',?,?,?)",(eid,pid,u['id'],action,obj,js(data),now(),now(),now()))

    def deliver_event(self,c,event):
        pid,u,action,obj,eid=event['project_id'],{'id':event['actor_id']},event['action'],event['object_id'],event['event_id']
        data=json.loads(event['data'])
        targets=[];kind='report';title='项目事项有更新'
        if action in {'REVIEW_SUBMITTED','REVIEW_TRANSFERRED'}:
            targets=[data.get('reviewer_id')];title='有报告等待审核'
        elif action=='FLOW_REVIEW_REQUESTED':
            kind='flow';targets=[data.get('reviewer_id')];title='编排分析成果等待核对'
        elif action in {'FIX_NEEDS_ASSIGNMENT','FLOW_NEEDS_TRANSFER'}:
            kind='fix' if action=='FIX_NEEDS_ASSIGNMENT' else 'flow';targets=[x['user_id'] for x in rows(c,"SELECT user_id FROM memberships WHERE project_id=? AND role='manager'",(pid,))];title='整改负责人失效，请改派' if kind=='fix' else '编排确认人失效，请转交'
        elif action in {'FLOW_COMPLETED','FLOW_FAILED'}:
            kind='flow';targets=[row(c,'SELECT actor_id FROM flow_runs WHERE id=?',(obj,))['actor_id']];title='编排分析成果已确认归档' if action=='FLOW_COMPLETED' else '编排运行未完整完成，请查看节点记录'
        elif action=='REVIEW_NEEDS_TRANSFER':
            approval=row(c,'SELECT a.* FROM approvals a JOIN reports r ON r.approval_id=a.id WHERE r.id=?',(obj,))
            if approval['state']=='PENDING' and json.loads(approval['data']).get('needs_transfer'):
                targets=[x['user_id'] for x in rows(c,"SELECT user_id FROM memberships WHERE project_id=? AND role='manager'",(pid,))];title='审核人已失效，报告等待转交'
        elif action=='REVIEW_REMINDER':
            approval=row(c,'SELECT a.* FROM approvals a JOIN reports r ON r.approval_id=a.id WHERE r.id=?',(obj,))
            if approval['state']=='PENDING' and not json.loads(approval['data']).get('needs_transfer') and approval['id']==data.get('approval_id'):
                targets=[approval['reviewer_id']];title='报告等待审核，请核对处理'
                if data.get('long_wait'):
                    targets+=[x['user_id'] for x in rows(c,"SELECT user_id FROM memberships WHERE project_id=? AND role='manager'",(pid,))];title='报告已等待超过七天，请检查或转交'
        elif action=='FIX_REMINDER':
            kind='fix';task=row(c,'SELECT * FROM rectifications WHERE id=?',(obj,))
            if task['state']=='PENDING_ACCEPTANCE' and data.get('waiting_acceptance'):
                targets=[x['user_id'] for x in rows(c,"SELECT user_id FROM memberships WHERE project_id=? AND role='manager' AND user_id!=?",(pid,task['owner_id']))];title='整改等待验收，请检查处理证据'
            elif task['state'] in {'TODO','IN_PROGRESS','REWORK'}:
                targets=[task['owner_id']];title='整改已逾期，请更新处理进展'
        elif action=='DOCUMENT_PARSE_FAILED':
            kind='document'
            version=c.execute('SELECT status FROM document_versions WHERE document_id=? AND version=?',(obj,data.get('document_version'))).fetchone()
            if version and version['status']=='FAILED':targets=[x['user_id'] for x in rows(c,"SELECT user_id FROM memberships WHERE project_id=? AND role IN ('manager','knowledge_admin')",(pid,))];title='资料解析失败，请检查文件并重试'
        elif action=='REPORT_REJECTED':
            target=row(c,'SELECT w.actor_id FROM reports r JOIN runs w ON w.id=r.run_id WHERE r.id=?',(obj,))
            targets=[target['actor_id']];title='报告已退回，请修订'
        elif action=='REPORT_PUBLISHED':
            targets=[x['user_id'] for x in rows(c,'SELECT user_id FROM memberships WHERE project_id=?',(pid,))];title='项目报告已发布'
        elif action.startswith('RECTIFICATION_'):
            kind='fix';task=row(c,'SELECT owner_id FROM rectifications WHERE id=?',(obj,))
            labels={'RECTIFICATION_CREATED':'你有新的整改事项','RECTIFICATION_RETURN':'整改被退回，请补充处理','RECTIFICATION_ACCEPT':'整改已通过验收','RECTIFICATION_REASSIGN':'整改负责人已调整'}
            if action in labels:targets=[task['owner_id']];title=labels[action]
            if action=='RECTIFICATION_SUBMIT':targets=[x['user_id'] for x in rows(c,"SELECT user_id FROM memberships WHERE project_id=? AND role='manager' AND user_id!=?",(pid,task['owner_id']))];title='整改已提交，请验收'
        elif action=='RUN_FAILED':
            kind='run';targets=[u['id']];title='汇总运行失败，可查看原因并恢复'
        elif action=='CONNECTION_SYNC_FAILED':
            kind='connection';targets=[row(c,'SELECT created_by FROM connections WHERE id=?',(obj,))['created_by']];title='数据同步失败，最近有效快照已保留'
        elif action=='SCHEDULE_TRIGGERED' and data.get('state')=='PAUSED':
            kind='schedule';targets=[row(c,'SELECT created_by FROM schedules WHERE id=?',(obj,))['created_by']];title='定时计划已暂停，请检查身份与授权'
        elif action=='ANALYSIS_COMPLETED':
            kind='analysis';targets=[u['id']];title='风险分析已完成，请核对证据与缺口'
        elif action=='ANALYSIS_FAILED':
            kind='analysis';targets=[u['id']];title='风险分析未完整完成，已有结果已保留'
        for target in set(targets):
            member=c.execute('SELECT u.id,m.role FROM users u JOIN memberships m ON m.user_id=u.id WHERE u.id=? AND m.project_id=? AND u.active=1',(target,pid)).fetchone()
            pref=c.execute('SELECT kinds FROM notice_preferences WHERE project_id=? AND user_id=?',(pid,target)).fetchone()
            if member and member['role']!='service_runner' and (not pref or kind in json.loads(pref['kinds'])):
                c.execute('INSERT OR IGNORE INTO notifications VALUES(?,?,?,?,?,?,?,?,?,?)',(uid('notice'),eid,target,pid,action,kind,obj,title,None,now()))
