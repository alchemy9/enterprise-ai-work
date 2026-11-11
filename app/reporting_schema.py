"""Historical inputs, milestones and explicit report revision chains."""
SCHEMA='''
CREATE TABLE IF NOT EXISTS period_snapshots(id TEXT PRIMARY KEY REFERENCES snapshots(id),project_id TEXT NOT NULL,period_end TEXT NOT NULL,kind TEXT NOT NULL,note TEXT NOT NULL,actor_id TEXT NOT NULL,data TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS period_snapshots_date ON period_snapshots(project_id,period_end);
CREATE TABLE IF NOT EXISTS milestones(id TEXT PRIMARY KEY,project_id TEXT NOT NULL,name TEXT NOT NULL,due_date TEXT NOT NULL,critical INTEGER NOT NULL,version INTEGER NOT NULL DEFAULT 1,data TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS report_relations(child_report_id TEXT PRIMARY KEY REFERENCES reports(id),parent_report_id TEXT NOT NULL REFERENCES reports(id),parent_version INTEGER NOT NULL,kind TEXT NOT NULL,reason TEXT NOT NULL,created_by TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS run_relations(child_run_id TEXT PRIMARY KEY REFERENCES runs(id),parent_run_id TEXT NOT NULL REFERENCES runs(id),kind TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS report_publications(report_id TEXT PRIMARY KEY REFERENCES reports(id),report_version INTEGER NOT NULL,actor_id TEXT NOT NULL,published_at TEXT NOT NULL,superseded_by TEXT);
'''
