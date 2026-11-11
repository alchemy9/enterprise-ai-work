"""Notification delivery is independent of committed business events."""
SCHEMA='''
CREATE TABLE IF NOT EXISTS notification_outbox(event_id TEXT PRIMARY KEY,project_id TEXT NOT NULL,actor_id TEXT NOT NULL,action TEXT NOT NULL,object_id TEXT NOT NULL,data TEXT NOT NULL,state TEXT NOT NULL,attempts INTEGER NOT NULL DEFAULT 0,next_at TEXT NOT NULL,error TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS reminder_settings(project_id TEXT PRIMARY KEY,review_hours INTEGER NOT NULL DEFAULT 24,acceptance_hours INTEGER NOT NULL DEFAULT 24,version INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS notice_preferences(project_id TEXT NOT NULL,user_id TEXT NOT NULL,kinds TEXT NOT NULL,version INTEGER NOT NULL DEFAULT 1,PRIMARY KEY(project_id,user_id));
CREATE TABLE IF NOT EXISTS reminder_marks(project_id TEXT NOT NULL,rule TEXT NOT NULL,object_key TEXT NOT NULL,bucket TEXT NOT NULL,event_id TEXT NOT NULL,created_at TEXT NOT NULL,PRIMARY KEY(project_id,rule,object_key,bucket));
CREATE INDEX IF NOT EXISTS notification_outbox_queue ON notification_outbox(state,next_at);
'''
