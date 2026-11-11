"""Persisted demo connectors, scheduled drafts and bounded analysis plans."""
SCHEMA='''
CREATE TABLE IF NOT EXISTS connections(id TEXT PRIMARY KEY,tenant_id TEXT NOT NULL,project_id TEXT NOT NULL REFERENCES projects(id),name TEXT NOT NULL,state TEXT NOT NULL,version INTEGER NOT NULL DEFAULT 1,config TEXT NOT NULL,last_snapshot_id TEXT,last_success_at TEXT,watermark INTEGER NOT NULL DEFAULT 0,created_by TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS connection_snapshots(id TEXT PRIMARY KEY,connection_id TEXT NOT NULL REFERENCES connections(id),content_hash TEXT NOT NULL,rows TEXT NOT NULL,watermark INTEGER NOT NULL,captured_at TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS connection_snapshot_immutable_update BEFORE UPDATE ON connection_snapshots BEGIN SELECT RAISE(ABORT,'immutable connection snapshot'); END;
CREATE TRIGGER IF NOT EXISTS connection_snapshot_immutable_delete BEFORE DELETE ON connection_snapshots BEGIN SELECT RAISE(ABORT,'immutable connection snapshot'); END;
CREATE TABLE IF NOT EXISTS sync_jobs(id TEXT PRIMARY KEY,connection_id TEXT NOT NULL REFERENCES connections(id),actor_id TEXT NOT NULL,state TEXT NOT NULL,data TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS connection_events(id TEXT PRIMARY KEY,connection_id TEXT NOT NULL,actor_id TEXT NOT NULL,action TEXT NOT NULL,state TEXT NOT NULL,data TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS schedules(id TEXT PRIMARY KEY,tenant_id TEXT NOT NULL,project_id TEXT NOT NULL,created_by TEXT NOT NULL,execution_user_id TEXT NOT NULL,state TEXT NOT NULL,version INTEGER NOT NULL DEFAULT 1,data TEXT NOT NULL,next_at TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS schedule_fires(id TEXT PRIMARY KEY,schedule_id TEXT NOT NULL REFERENCES schedules(id),scheduled_at TEXT NOT NULL,trigger_type TEXT NOT NULL,state TEXT NOT NULL,run_id TEXT,data TEXT NOT NULL,created_at TEXT NOT NULL,UNIQUE(schedule_id,scheduled_at));
CREATE TABLE IF NOT EXISTS analyses(id TEXT PRIMARY KEY,tenant_id TEXT NOT NULL,project_id TEXT NOT NULL,actor_id TEXT NOT NULL,submission_key TEXT NOT NULL,request_hash TEXT NOT NULL,state TEXT NOT NULL,version INTEGER NOT NULL DEFAULT 1,data TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,UNIQUE(project_id,actor_id,submission_key));
CREATE TABLE IF NOT EXISTS analysis_plans(analysis_id TEXT NOT NULL REFERENCES analyses(id),version INTEGER NOT NULL,content_hash TEXT NOT NULL,data TEXT NOT NULL,created_at TEXT NOT NULL,PRIMARY KEY(analysis_id,version));
CREATE TRIGGER IF NOT EXISTS analysis_plan_immutable_update BEFORE UPDATE ON analysis_plans BEGIN SELECT RAISE(ABORT,'immutable analysis plan'); END;
CREATE TRIGGER IF NOT EXISTS analysis_plan_immutable_delete BEFORE DELETE ON analysis_plans BEGIN SELECT RAISE(ABORT,'immutable analysis plan'); END;
CREATE TABLE IF NOT EXISTS analysis_steps(id TEXT PRIMARY KEY,analysis_id TEXT NOT NULL REFERENCES analyses(id),ordinal INTEGER NOT NULL,tool_id TEXT NOT NULL,state TEXT NOT NULL,params TEXT NOT NULL,result TEXT NOT NULL,started_at TEXT NOT NULL,ended_at TEXT NOT NULL,UNIQUE(analysis_id,ordinal));
CREATE INDEX IF NOT EXISTS sync_jobs_queue ON sync_jobs(state,created_at);
CREATE INDEX IF NOT EXISTS schedules_due ON schedules(state,next_at);
CREATE INDEX IF NOT EXISTS analyses_queue ON analyses(state,updated_at);
'''
