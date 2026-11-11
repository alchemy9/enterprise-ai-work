"""Versioned read-only graph demos with durable node attempts and review."""
SCHEMA='''
CREATE TABLE IF NOT EXISTS flow_definitions(id TEXT PRIMARY KEY,tenant_id TEXT NOT NULL,name TEXT NOT NULL,purpose TEXT NOT NULL,active_version INTEGER,enabled INTEGER NOT NULL DEFAULT 1,version INTEGER NOT NULL DEFAULT 1,created_by TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS flow_versions(flow_id TEXT NOT NULL REFERENCES flow_definitions(id),version INTEGER NOT NULL,state TEXT NOT NULL,revision INTEGER NOT NULL DEFAULT 1,content_hash TEXT NOT NULL,data TEXT NOT NULL,note TEXT NOT NULL,created_by TEXT NOT NULL,created_at TEXT NOT NULL,PRIMARY KEY(flow_id,version));
CREATE TRIGGER IF NOT EXISTS flow_published_immutable BEFORE UPDATE ON flow_versions WHEN OLD.state='PUBLISHED' AND (NEW.data!=OLD.data OR NEW.content_hash!=OLD.content_hash) BEGIN SELECT RAISE(ABORT,'immutable flow version'); END;
CREATE TABLE IF NOT EXISTS flow_runs(id TEXT PRIMARY KEY,tenant_id TEXT NOT NULL,project_id TEXT NOT NULL,flow_id TEXT NOT NULL,flow_version INTEGER NOT NULL,actor_id TEXT NOT NULL,reviewer_id TEXT NOT NULL,state TEXT NOT NULL,version INTEGER NOT NULL DEFAULT 1,data TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS flow_attempts(id TEXT PRIMARY KEY,run_id TEXT NOT NULL REFERENCES flow_runs(id),node_id TEXT NOT NULL,attempt INTEGER NOT NULL,state TEXT NOT NULL,data TEXT NOT NULL,started_at TEXT NOT NULL,ended_at TEXT,UNIQUE(run_id,node_id,attempt));
CREATE INDEX IF NOT EXISTS flow_queue ON flow_runs(state,created_at);
'''
