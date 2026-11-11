SCHEMA='''
CREATE TABLE IF NOT EXISTS library_policies(library_id TEXT PRIMARY KEY,owner_id TEXT NOT NULL,default_valid_days INTEGER NOT NULL,acl_mode TEXT NOT NULL,roles TEXT NOT NULL,members TEXT NOT NULL,version INTEGER NOT NULL DEFAULT 1,updated_at TEXT NOT NULL);
'''
