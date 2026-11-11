"""Durable exports and content-retention metadata; no business data replacement."""
SCHEMA='''
CREATE TABLE IF NOT EXISTS export_jobs(id TEXT PRIMARY KEY,tenant_id TEXT NOT NULL,project_id TEXT NOT NULL,report_id TEXT NOT NULL,report_version INTEGER NOT NULL,actor_id TEXT NOT NULL,format TEXT NOT NULL,state TEXT NOT NULL,version INTEGER NOT NULL DEFAULT 1,data TEXT NOT NULL,body BLOB,error TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS download_tokens(token_hash TEXT PRIMARY KEY,export_id TEXT NOT NULL,actor_id TEXT NOT NULL,expires_at TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS retention_jobs(document_id TEXT PRIMARY KEY,project_id TEXT NOT NULL,actor_id TEXT NOT NULL,state TEXT NOT NULL,purge_after TEXT NOT NULL,reason TEXT NOT NULL,created_at TEXT NOT NULL,completed_at TEXT);
DROP TRIGGER IF EXISTS document_source_immutable;
CREATE TRIGGER document_source_immutable BEFORE UPDATE ON document_versions WHEN NEW.content_hash!=OLD.content_hash OR NEW.filename!=OLD.filename OR (NEW.raw!=OLD.raw AND NOT (length(NEW.raw)=0 AND EXISTS(SELECT 1 FROM retention_jobs WHERE document_id=OLD.document_id AND state='PURGING'))) BEGIN SELECT RAISE(ABORT,'immutable document source'); END;
'''
