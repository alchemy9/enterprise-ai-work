SCHEMA='''
CREATE TABLE IF NOT EXISTS evaluation_sets(id TEXT NOT NULL,version INTEGER NOT NULL,tenant_id TEXT NOT NULL,project_id TEXT NOT NULL,name TEXT NOT NULL,data TEXT NOT NULL,content_hash TEXT NOT NULL,actor_id TEXT NOT NULL,created_at TEXT NOT NULL,PRIMARY KEY(id,version));
CREATE TABLE IF NOT EXISTS evaluation_runs(id TEXT PRIMARY KEY,tenant_id TEXT NOT NULL,project_id TEXT NOT NULL,actor_id TEXT NOT NULL,set_id TEXT NOT NULL,set_version INTEGER NOT NULL,definition_id TEXT NOT NULL,definition_version INTEGER NOT NULL,baseline_version INTEGER,state TEXT NOT NULL,version INTEGER NOT NULL DEFAULT 1,data TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS evaluation_reviews(id TEXT PRIMARY KEY,run_id TEXT NOT NULL,actor_id TEXT NOT NULL,decision TEXT NOT NULL,comment TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS evaluation_set_immutable BEFORE UPDATE ON evaluation_sets BEGIN SELECT RAISE(ABORT,'immutable evaluation set'); END;
'''
