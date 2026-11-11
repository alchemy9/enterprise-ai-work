"""Project administration, platform capabilities, inbox and audit metadata."""
SCHEMA='''
CREATE TABLE IF NOT EXISTS system_roles(user_id TEXT PRIMARY KEY REFERENCES users(id),roles TEXT NOT NULL,version INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS project_settings(project_id TEXT PRIMARY KEY REFERENCES projects(id),data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS notifications(id TEXT PRIMARY KEY,event_id TEXT NOT NULL,user_id TEXT NOT NULL,project_id TEXT NOT NULL,kind TEXT NOT NULL,object_type TEXT NOT NULL,object_id TEXT NOT NULL,title TEXT NOT NULL,read_at TEXT,created_at TEXT NOT NULL,UNIQUE(event_id,user_id));
CREATE TABLE IF NOT EXISTS platform_audit(id TEXT PRIMARY KEY,tenant_id TEXT NOT NULL,project_id TEXT NOT NULL,actor_id TEXT NOT NULL,action TEXT NOT NULL,object_id TEXT NOT NULL,data TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS bookmarks(user_id TEXT NOT NULL,object_type TEXT NOT NULL,object_id TEXT NOT NULL,created_at TEXT NOT NULL,PRIMARY KEY(user_id,object_type,object_id));
CREATE INDEX IF NOT EXISTS notifications_user ON notifications(user_id,created_at);
CREATE UNIQUE INDEX IF NOT EXISTS project_code_tenant ON projects(tenant_id,code);
'''
