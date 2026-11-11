SCHEMA='''
CREATE TABLE IF NOT EXISTS fragment_policies(parent_id TEXT PRIMARY KEY,document_id TEXT NOT NULL,document_version INTEGER NOT NULL,members TEXT NOT NULL,actor_id TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS output_scopes(output_type TEXT NOT NULL,output_id TEXT NOT NULL,document_id TEXT NOT NULL,document_version INTEGER NOT NULL,scope TEXT NOT NULL,PRIMARY KEY(output_type,output_id,document_id,document_version));
CREATE TABLE IF NOT EXISTS retrieval_profiles(project_id TEXT NOT NULL,version INTEGER NOT NULL,data TEXT NOT NULL,content_hash TEXT NOT NULL,actor_id TEXT NOT NULL,note TEXT NOT NULL,created_at TEXT NOT NULL,PRIMARY KEY(project_id,version));
CREATE TRIGGER IF NOT EXISTS retrieval_profile_immutable BEFORE UPDATE ON retrieval_profiles BEGIN SELECT RAISE(ABORT,'immutable retrieval profile'); END;
'''
