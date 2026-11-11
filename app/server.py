"""Local server; start.sh prepares the document parsing/export dependencies."""
import argparse
import hashlib
import hmac
import json
import secrets
import threading
from datetime import datetime, timedelta
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
from .db import Database, TZ, now, js, password_hash
from .domain import BusinessError, require
from .service import Service

ROOT = Path(__file__).resolve().parent.parent


class AppServer(ThreadingHTTPServer):
    daemon_threads=True
    allow_reuse_address=True

    def __init__(self, address, db_path, worker=True):
        self.db=Database(db_path)
        self.service=Service(self.db)
        self.service.recover()
        self.stop_worker=threading.Event()
        super().__init__(address,Handler)
        if worker:
            threading.Thread(target=self.work,daemon=True,name='eaw-workflow').start()

    def work(self):
        while not self.stop_worker.is_set():
            try:
                busy=self.service.process_next()
            except Exception:
                import traceback
                traceback.print_exc()
                busy=False
            if not busy:
                self.stop_worker.wait(.15)

    def server_close(self):
        self.stop_worker.set()
        super().server_close()


class Handler(BaseHTTPRequestHandler):
    server_version='EnterpriseAIWork/0.1'

    def log_message(self, fmt, *args):
        # URL paths and status only; no bodies, cookies or passwords.
        if '/api/' not in str(args[0]) or ' 500' in str(args):
            super().log_message(fmt,*args)

    def send(self,status,data,mime='application/json; charset=utf-8',headers=None):
        raw=(js(data).encode() if mime.startswith('application/json') else data.encode() if isinstance(data,str) else data)
        self.send_response(status)
        self.send_header('Content-Type',mime)
        self.send_header('Content-Length',str(len(raw)))
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Referrer-Policy','no-referrer')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        for k,v in (headers or {}).items():
            self.send_header(k,v)
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        self.handle_request('GET')

    def do_POST(self):
        self.handle_request('POST')

    def handle_request(self,method):
        trace='http_'+secrets.token_hex(8)
        u=None;path=''
        try:
            host=self.headers.get('Host','')
            allowed={f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}'}
            require(host in allowed,'仅支持本地 localhost/127.0.0.1 访问','PERMISSION_DENIED',403)
            path=urlsplit(self.path).path
            if method=='GET' and path=='/api/health':
                return self.send(200,{'status':'ok','mode':'DEMO_RULES','storage':'sqlite','schema_version':14})
            if method=='GET' and not path.startswith('/api/'):
                files={'/':('index.html','text/html; charset=utf-8'),'/app.js':('app.js','application/javascript; charset=utf-8'),'/knowledge.js':('knowledge.js','application/javascript; charset=utf-8'),'/platform.js':('platform.js','application/javascript; charset=utf-8'),'/governance.js':('governance.js','application/javascript; charset=utf-8'),'/advanced.js':('advanced.js','application/javascript; charset=utf-8'),'/reporting.js':('reporting.js','application/javascript; charset=utf-8'),'/flows.js':('flows.js','application/javascript; charset=utf-8'),'/delivery.js':('delivery.js','application/javascript; charset=utf-8'),'/evaluations.js':('evaluations.js','application/javascript; charset=utf-8'),'/source_policies.js':('source_policies.js','application/javascript; charset=utf-8'),'/style.css':('style.css','text/css; charset=utf-8')}
                require(path in files,'页面不存在','NOT_FOUND',404)
                file,mime=files[path]
                return self.send(200,(ROOT/'static'/file).read_bytes(),mime)
            b={}
            if method=='POST':
                require(self.headers.get('X-EAW-Request')=='1','请求缺少来源校验标识','PERMISSION_DENIED',403)
                origin=self.headers.get('Origin')
                require(not origin or origin in {f'http://{h}' for h in allowed},'跨站请求已拒绝','PERMISSION_DENIED',403)
                require(self.headers.get('Content-Type','').split(';')[0]=='application/json','请使用 application/json')
                try:
                    length=int(self.headers.get('Content-Length','0'))
                    require(0<length<=(72_000_000 if path.endswith('/documents') or path.endswith('/versions') else 5_000_000),'请求体为空或过大')
                    b=json.loads(self.rfile.read(length))
                except (ValueError,UnicodeDecodeError):
                    raise BusinessError(400,'INPUT_INVALID','请求 JSON 无效')
                require(isinstance(b,dict),'请求必须为 JSON 对象')
            with self.server.db.tx() as c:
                if path=='/api/auth/login' and method=='POST':
                    username,password=b.get('username'),b.get('password')
                    require(isinstance(username,str) and isinstance(password,str) and len(password)<=200,'账号或密码无效','AUTH_REQUIRED',401)
                    u=c.execute('SELECT * FROM users WHERE username=? AND active=1',(username,)).fetchone()
                    # Constant-cost unknown-user path prevents cheap account enumeration.
                    actual=password_hash(password,u['salt'] if u else 'unknown-account-salt')
                    require(u is not None and hmac.compare_digest(actual,u['password_hash']),'账号、密码错误或账号已停用','AUTH_REQUIRED',401)
                    token=secrets.token_urlsafe(32)
                    expiry=(datetime.now(TZ)+timedelta(hours=12)).isoformat(timespec='seconds')
                    c.execute('INSERT INTO sessions VALUES(?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),u['id'],expiry))
                    self.server.service.platform.audit(c,dict(u),'LOGIN',u['id'])
                    result={'id':u['id'],'name':u['name']}
                    response_cookie=f'eaw_session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=43200'
                else:
                    jar=cookies.SimpleCookie()
                    try:
                        jar.load(self.headers.get('Cookie',''))
                    except cookies.CookieError:
                        pass
                    token=jar['eaw_session'].value if 'eaw_session' in jar else ''
                    token_hash=hashlib.sha256(token.encode()).hexdigest()
                    row=c.execute('SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND s.expires_at>? AND u.active=1',(token_hash,now())).fetchone()
                    require(row is not None,'请登录后继续','AUTH_REQUIRED',401)
                    u=dict(row)
                    response_cookie=None
                    if path=='/api/auth/logout' and method=='POST':
                        self.server.service.platform.audit(c,u,'LOGOUT',u['id'])
                        c.execute('DELETE FROM sessions WHERE token_hash=?',(token_hash,))
                        result={'ok':True}
                        response_cookie='eaw_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0'
                    elif method=='GET' and path.startswith('/api/downloads/'):
                        body,download_mime,download_name=self.server.service.delivery.download(c,u,path.split('/')[-1]);result=None
                    elif method=='GET' and path.endswith(('/export.md','/export.docx')):
                        rid=path.split('/')[-2]
                        result=self.server.service.delivery.dispatch(c,u,'POST','/api/exports',{'report_id':rid,'format':'docx' if path.endswith('/export.docx') else 'md','event_key':secrets.token_hex(16)},{})
                    else:
                        result=self.server.service.dispatch(c,u,method,path,b,parse_qs(urlsplit(self.path).query))
            if method=='GET' and path.startswith('/api/downloads/'):
                return self.send(200,body,download_mime,{'Content-Disposition':'attachment; filename="'+download_name+'"'})
            if method=='GET' and path.endswith(('/export.md','/export.docx')):
                return self.send(303,'','text/plain; charset=utf-8',{'Location':'/#/downloads/'+result['id']})
            return self.send(202 if path=='/api/runs' and method=='POST' else 200,result,headers={'Set-Cookie':response_cookie} if response_cookie else None)
        except BusinessError as exc:
            if u is not None and exc.status in {403,409,429}:
                try:
                    with self.server.db.tx() as audit_connection:
                        self.server.service.platform.audit(audit_connection,dict(u),'REQUEST_REJECTED',hashlib.sha256(path.encode()).hexdigest()[:24],{'request_id':trace,'result':exc.code,'status':exc.status,'method':method,'endpoint':path.split('/')[2] if path.startswith('/api/') else 'local'})
                except Exception:
                    pass
            self.send(exc.status,{'error':exc.code,'message':exc.message,'details':exc.details,'trace_id':trace})
        except (BrokenPipeError,ConnectionResetError):
            pass
        except Exception:
            import traceback
            traceback.print_exc()
            self.send(500,{'error':'INTERNAL_ERROR','message':'服务异常，操作未提交。请重试并提供排障编号。','trace_id':trace})

    @staticmethod
    def export_md(report,u):
        from .exports import report_markdown
        return report_markdown(report,u)


def main():
    parser=argparse.ArgumentParser(description='Enterprise AI Work local R1 MVP')
    parser.add_argument('--port',type=int,default=8765)
    parser.add_argument('--db',default=str(ROOT/'var'/'eaw.sqlite3'))
    args=parser.parse_args()
    server=AppServer(('127.0.0.1',args.port),args.db)
    print(f'Enterprise AI Work: http://127.0.0.1:{server.server_port} (DEMO_RULES)',flush=True)
    try:
        server.serve_forever(poll_interval=.2)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__=='__main__':
    main()
