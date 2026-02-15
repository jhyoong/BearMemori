-- Migration 006: Update llm_jobs table to match API schema
-- Add user_id field and rename error to error_message

-- Create new table with correct schema
CREATE TABLE llm_jobs_new (
    id              TEXT PRIMARY KEY,
    job_type        TEXT NOT NULL,
    payload         TEXT NOT NULL,
    user_id         INTEGER,
    status          TEXT NOT NULL DEFAULT 'queued',
    result          TEXT,
    error_message   TEXT,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- Copy data from old table to new table
INSERT INTO llm_jobs_new (id, job_type, payload, user_id, status, result, error_message, created_at, updated_at)
SELECT id, job_type, payload, NULL, status, result, error, created_at, updated_at
FROM llm_jobs;

-- Drop old table
DROP TABLE llm_jobs;

-- Rename new table to llm_jobs
ALTER TABLE llm_jobs_new RENAME TO llm_jobs;

-- Create indexes
CREATE INDEX idx_llm_jobs_status ON llm_jobs(status);
CREATE INDEX idx_llm_jobs_user_id ON llm_jobs(user_id) WHERE user_id IS NOT NULL;
CREATE INDEX idx_llm_jobs_job_type ON llm_jobs(job_type);
