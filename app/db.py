"""Local SQLite storage. One connection per transaction, durable object/event writes."""
import hashlib
import json
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo('Asia/Shanghai')


def now():
    return datetime.now(TZ).isoformat(timespec='seconds')


def today():
    return datetime.now(TZ).date()


def js(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def digest(value):
    return hashlib.sha256(js(value).encode()).hexdigest()


def uid(prefix):
    return prefix + '_' + secrets.token_hex(8)


def password_hash(password, salt):
    return hashlib.scrypt(password.encode(), salt=salt.encode(), n=16384, r=8, p=1).hex()


SCHEMA = '''
CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, username TEXT UNIQUE NOT NULL, name TEXT NOT NULL, salt TEXT NOT NULL, password_hash TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), expires_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, name TEXT NOT NULL, code TEXT NOT NULL, description TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'ACTIVE', version INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS memberships(project_id TEXT REFERENCES projects(id), user_id TEXT REFERENCES users(id), role TEXT NOT NULL, PRIMARY KEY(project_id,user_id));
CREATE TABLE IF NOT EXISTS ledger(project_id TEXT REFERENCES projects(id), task_id TEXT NOT NULL, data TEXT NOT NULL, PRIMARY KEY(project_id,task_id));
CREATE TABLE IF NOT EXISTS imports(id TEXT PRIMARY KEY, project_id TEXT NOT NULL, actor_id TEXT NOT NULL, content_hash TEXT NOT NULL, rows TEXT NOT NULL, errors TEXT NOT NULL, state TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS snapshots(id TEXT PRIMARY KEY, project_id TEXT NOT NULL, captured_at TEXT NOT NULL, content_hash TEXT NOT NULL, rows TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS snapshot_immutable_update BEFORE UPDATE ON snapshots BEGIN SELECT RAISE(ABORT,'immutable snapshot'); END;
CREATE TRIGGER IF NOT EXISTS snapshot_immutable_delete BEFORE DELETE ON snapshots BEGIN SELECT RAISE(ABORT,'immutable snapshot'); END;
CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, project_id TEXT NOT NULL, actor_id TEXT NOT NULL, snapshot_id TEXT NOT NULL REFERENCES snapshots(id), submission_key TEXT NOT NULL, request_hash TEXT NOT NULL, state TEXT NOT NULL, phase TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1, data TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE(project_id,actor_id,submission_key));
CREATE TABLE IF NOT EXISTS attempts(id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id), node TEXT NOT NULL, attempt INTEGER NOT NULL, status TEXT NOT NULL, started_at TEXT NOT NULL, ended_at TEXT, summary TEXT NOT NULL, UNIQUE(run_id,node,attempt));
CREATE TABLE IF NOT EXISTS reports(id TEXT PRIMARY KEY, run_id TEXT UNIQUE NOT NULL REFERENCES runs(id), project_id TEXT NOT NULL, current_version INTEGER NOT NULL, status TEXT NOT NULL, approval_id TEXT);
CREATE TABLE IF NOT EXISTS report_versions(report_id TEXT NOT NULL REFERENCES reports(id), version INTEGER NOT NULL, content_hash TEXT NOT NULL, data TEXT NOT NULL, author_id TEXT NOT NULL, reason TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY(report_id,version));
CREATE TRIGGER IF NOT EXISTS report_immutable_update BEFORE UPDATE ON report_versions BEGIN SELECT RAISE(ABORT,'immutable report version'); END;
CREATE TRIGGER IF NOT EXISTS report_immutable_delete BEFORE DELETE ON report_versions BEGIN SELECT RAISE(ABORT,'immutable report version'); END;
CREATE TABLE IF NOT EXISTS approvals(id TEXT PRIMARY KEY, report_id TEXT NOT NULL, report_version INTEGER NOT NULL, content_hash TEXT NOT NULL, reviewer_id TEXT NOT NULL, state TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1, data TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS confirmations(id TEXT PRIMARY KEY, project_id TEXT NOT NULL, report_id TEXT NOT NULL, report_version INTEGER NOT NULL, actor_id TEXT NOT NULL, params_hash TEXT NOT NULL, items TEXT NOT NULL, expires_at TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS rectifications(id TEXT PRIMARY KEY, action_id TEXT UNIQUE NOT NULL, project_id TEXT NOT NULL, report_id TEXT NOT NULL, report_version INTEGER NOT NULL, risk_id TEXT NOT NULL, owner_id TEXT NOT NULL, state TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1, params_hash TEXT NOT NULL, data TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS receipts(scope TEXT NOT NULL, event_key TEXT NOT NULL, request_hash TEXT NOT NULL, result TEXT NOT NULL, PRIMARY KEY(scope,event_key));
CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY, project_id TEXT NOT NULL, actor_id TEXT NOT NULL, action TEXT NOT NULL, object_id TEXT NOT NULL, data TEXT NOT NULL, trace_id TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS runs_queue ON runs(state,created_at);
CREATE INDEX IF NOT EXISTS events_object ON events(object_id,created_at);
'''


class Database:
    def __init__(self, path):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        c = self.connect()
        try:
            c.execute('PRAGMA journal_mode=WAL')
            c.executescript(SCHEMA)
            c.execute('INSERT OR IGNORE INTO schema_migrations VALUES(1,?)', (now(),))
            if not c.execute('SELECT 1 FROM schema_migrations WHERE version=2').fetchone():
                self.migrate_review_attempts(c)
                c.execute('INSERT INTO schema_migrations VALUES(2,?)', (now(),))
            from .knowledge_schema import SCHEMA as knowledge_schema
            c.executescript(knowledge_schema)
            c.execute('INSERT OR IGNORE INTO schema_migrations VALUES(3,?)', (now(),))
            from .platform_schema import SCHEMA as platform_schema
            c.executescript(platform_schema)
            c.execute('INSERT OR IGNORE INTO schema_migrations VALUES(4,?)', (now(),))
            from .governance_schema import SCHEMA as governance_schema
            c.executescript(governance_schema)
            c.execute('INSERT OR IGNORE INTO schema_migrations VALUES(5,?)', (now(),))
            from .advanced_schema import SCHEMA as advanced_schema
            c.executescript(advanced_schema)
            c.execute('INSERT OR IGNORE INTO schema_migrations VALUES(6,?)', (now(),))
            from .knowledge_extra_schema import SCHEMA as knowledge_extra_schema
            c.executescript(knowledge_extra_schema)
            c.execute('INSERT OR IGNORE INTO schema_migrations VALUES(7,?)', (now(),))
            from .reporting_schema import SCHEMA as reporting_schema
            c.executescript(reporting_schema)
            c.execute('INSERT OR IGNORE INTO schema_migrations VALUES(8,?)', (now(),))
            from .collaboration_schema import SCHEMA as collaboration_schema
            c.executescript(collaboration_schema)
            c.execute('INSERT OR IGNORE INTO schema_migrations VALUES(9,?)', (now(),))
            from .flow_schema import SCHEMA as flow_schema
            c.executescript(flow_schema)
            c.execute('INSERT OR IGNORE INTO schema_migrations VALUES(10,?)', (now(),))
            from .delivery_schema import SCHEMA as delivery_schema
            c.executescript(delivery_schema)
            c.execute('INSERT OR IGNORE INTO schema_migrations VALUES(11,?)', (now(),))
            from .evaluation_schema import SCHEMA as evaluation_schema
            c.executescript(evaluation_schema)
            c.execute('INSERT OR IGNORE INTO schema_migrations VALUES(12,?)', (now(),))
            from .library_schema import SCHEMA as library_schema
            c.executescript(library_schema)
            c.execute('INSERT OR IGNORE INTO schema_migrations VALUES(13,?)', (now(),))
            from .source_policy_schema import SCHEMA as source_policy_schema
            c.executescript(source_policy_schema)
            c.execute('INSERT OR IGNORE INTO schema_migrations VALUES(14,?)', (now(),))
            c.commit()
        finally:
            c.close()
        self.seed()

    @staticmethod
    def migrate_review_attempts(c):
        """Reconcile early MVP review traces using persisted approvals/events only.

        Business decisions and report content are never changed. Missing historical
        end times stay unknown rather than being fabricated from the migration time.
        """
        for report in c.execute('SELECT id,run_id FROM reports').fetchall():
            approvals=c.execute('SELECT * FROM approvals WHERE report_id=? ORDER BY rowid',(report['id'],)).fetchall()
            attempts=c.execute("SELECT * FROM attempts WHERE run_id=? AND node='HumanReview' AND status!='FAILED' ORDER BY attempt",(report['run_id'],)).fetchall()
            events=c.execute('SELECT * FROM events WHERE object_id IN (?,?) ORDER BY rowid',(report['id'],report['run_id'])).fetchall()
            for index, approval in enumerate(approvals):
                state=approval['state']
                status={'PENDING':'WAITING','APPROVED':'SUCCEEDED','REJECTED':'SUCCEEDED','VOID':'CANCELLED'}[state]
                data=json.loads(approval['data'])
                ended=data.get('decided_at')
                if state=='VOID':
                    ended=next((e['created_at'] for e in events if e['action']=='RUN_CANCELLED' or e['action']=='REVIEW_WITHDRAWN' and json.loads(e['data']).get('version')==approval['report_version']),None)
                summary={'PENDING':'等待人工审核','APPROVED':'人工审核已通过','REJECTED':'人工审核已退回','VOID':'审核已撤回或取消'}[state]+f"（正文 v{approval['report_version']}）"
                if index<len(attempts):
                    c.execute('UPDATE attempts SET status=?,ended_at=?,summary=? WHERE id=?',(status,ended,summary,attempts[index]['id']))
                else:
                    number=c.execute("SELECT coalesce(max(attempt),0)+1 FROM attempts WHERE run_id=? AND node='HumanReview'",(report['run_id'],)).fetchone()[0]
                    c.execute('INSERT INTO attempts VALUES(?,?,?,?,?,?,?,?)',(uid('attempt'),report['run_id'],'HumanReview',number,status,approval['created_at'],ended,summary))

    def connect(self):
        c = sqlite3.connect(self.path, timeout=15)
        c.row_factory = sqlite3.Row
        c.execute('PRAGMA foreign_keys=ON')
        c.execute('PRAGMA busy_timeout=15000')
        return c

    @contextmanager
    def tx(self):
        c = self.connect()
        try:
            c.execute('BEGIN IMMEDIATE')
            yield c
            c.commit()
        except BaseException:
            c.rollback()
            raise
        finally:
            c.close()

    def seed(self):
        with self.tx() as c:
            if c.execute('SELECT 1 FROM users LIMIT 1').fetchone():
                return
            for ident, tenant, username, name in [('u_manager','tenant_demo','manager','王天陆'), ('u_owner','tenant_demo','owner','陈晓'), ('u_reviewer','tenant_demo','reviewer','林悦'), ('u_other','tenant_other','outsider','隔离测试账号')]:
                salt = secrets.token_hex(16)
                c.execute('INSERT INTO users(id,tenant_id,username,name,salt,password_hash) VALUES(?,?,?,?,?,?)', (ident,tenant,username,name,salt,password_hash('EawDemo!2026',salt)))
            c.execute('INSERT INTO projects(id,tenant_id,name,code,description) VALUES(?,?,?,?,?)', ('p_demo','tenant_demo','企业协同平台 · 一期交付','EAW-001','从项目事实出发，让每一项风险都有处理结果。'))
            c.execute('INSERT INTO projects(id,tenant_id,name,code,description) VALUES(?,?,?,?,?)', ('p_other','tenant_other','隔离项目','SEC-002','仅用于租户隔离验证'))
            c.executemany('INSERT INTO memberships VALUES(?,?,?)', [('p_demo','u_manager','manager'),('p_demo','u_owner','member'),('p_demo','u_reviewer','reviewer'),('p_other','u_other','manager')])
            names = ['需求范围与验收口径确认','项目空间与账号搭建','业务台账字段对齐','任务权限规则评审','验收环境联调','历史数据补录','汇总报告模板配置','整改处理与验收联调','项目交付文档整理','试点用户操作培训']
            d = today()
            for i, title in enumerate(names, 1):
                due = d + timedelta(days=(-6+i if i <= 4 else -2 if i == 5 else -1 if i == 6 else i-7))
                row = dict(task_id=f'T-{i:03}', title=title, owner_id='u_owner' if i%2 else 'u_manager', status='DONE' if i<=4 else 'IN_PROGRESS' if i<=8 else 'TODO', planned_start=(d-timedelta(days=10)).isoformat(), due_date=due.isoformat(), completed_at=(d-timedelta(days=1)).isoformat() if i<=4 else '', milestone_id='', updated_at=now())
                c.execute('INSERT INTO ledger VALUES(?,?,?)', ('p_demo',row['task_id'],js(row)))
