"""Parent context and maintainers' feedback handling."""
SCHEMA='''
CREATE TABLE IF NOT EXISTS knowledge_parents(id TEXT PRIMARY KEY,document_id TEXT NOT NULL,document_version INTEGER NOT NULL,anchor TEXT NOT NULL,heading TEXT NOT NULL,content TEXT NOT NULL,truncated INTEGER NOT NULL DEFAULT 0,FOREIGN KEY(document_id,document_version) REFERENCES document_versions(document_id,version));
CREATE TABLE IF NOT EXISTS feedback_resolutions(feedback_id TEXT PRIMARY KEY REFERENCES question_feedback(id),state TEXT NOT NULL,note TEXT NOT NULL,actor_id TEXT NOT NULL,version INTEGER NOT NULL DEFAULT 1,updated_at TEXT NOT NULL);
'''
