-- Migration 007: Create backup_jobs table
-- This table tracks backup job status for users

CREATE TABLE backup_jobs (
    backup_id       TEXT PRIMARY KEY,
    user_id         INTEGER NOT NULL,
    started_at      TEXT NOT NULL,
    completed_at    TEXT,
    status          TEXT NOT NULL,
    file_path       TEXT,
    error_message   TEXT
);

-- Index for efficient lookup by user_id and started_at
CREATE INDEX idx_backup_jobs_user_started ON backup_jobs(user_id, started_at DESC);
