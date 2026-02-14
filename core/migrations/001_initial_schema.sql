-- Initial database schema for Life Organiser
-- Migration 001: Create all tables, indexes, and FTS5 virtual table

-- Users table
CREATE TABLE users (
    telegram_user_id  INTEGER PRIMARY KEY,
    display_name      TEXT NOT NULL,
    is_allowed        INTEGER NOT NULL DEFAULT 0,
    created_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- User settings table
CREATE TABLE user_settings (
    telegram_user_id      INTEGER PRIMARY KEY REFERENCES users(telegram_user_id),
    default_reminder_time TEXT NOT NULL DEFAULT '09:00',
    timezone              TEXT NOT NULL DEFAULT 'Asia/Singapore'
);

-- Memories table (core entity)
CREATE TABLE memories (
    id                  TEXT PRIMARY KEY,
    owner_user_id       INTEGER NOT NULL REFERENCES users(telegram_user_id),
    source_chat_id      INTEGER,
    source_message_id   INTEGER,
    content             TEXT,
    media_type          TEXT,
    media_file_id       TEXT,
    media_local_path    TEXT,
    status              TEXT NOT NULL DEFAULT 'confirmed',
    pending_expires_at  TEXT,
    is_pinned           INTEGER NOT NULL DEFAULT 0,
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- Memory tags table
CREATE TABLE memory_tags (
    memory_id   TEXT NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
    tag         TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'confirmed',
    suggested_at TEXT,
    confirmed_at TEXT,
    PRIMARY KEY (memory_id, tag)
);

-- Tasks table
CREATE TABLE tasks (
    id                  TEXT PRIMARY KEY,
    memory_id           TEXT NOT NULL REFERENCES memories(id),
    owner_user_id       INTEGER NOT NULL REFERENCES users(telegram_user_id),
    description         TEXT NOT NULL,
    state               TEXT NOT NULL DEFAULT 'NOT_DONE',
    due_at              TEXT,
    recurrence_minutes  INTEGER,
    completed_at        TEXT,
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- Reminders table
CREATE TABLE reminders (
    id                  TEXT PRIMARY KEY,
    memory_id           TEXT NOT NULL REFERENCES memories(id),
    owner_user_id       INTEGER NOT NULL REFERENCES users(telegram_user_id),
    fire_at             TEXT NOT NULL,
    recurrence_minutes  INTEGER,
    fired               INTEGER NOT NULL DEFAULT 0,
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- Events table
CREATE TABLE events (
    id                  TEXT PRIMARY KEY,
    memory_id           TEXT REFERENCES memories(id),
    owner_user_id       INTEGER NOT NULL REFERENCES users(telegram_user_id),
    description         TEXT NOT NULL,
    event_date          TEXT NOT NULL,
    source_type         TEXT NOT NULL,
    source_ref          TEXT,
    status              TEXT NOT NULL DEFAULT 'pending',
    pending_since       TEXT,
    reminder_id         TEXT REFERENCES reminders(id),
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- Audit log table
CREATE TABLE audit_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT NOT NULL,
    entity_id   TEXT NOT NULL,
    action      TEXT NOT NULL,
    actor       TEXT NOT NULL,
    detail      TEXT,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- LLM jobs table
CREATE TABLE llm_jobs (
    id              TEXT PRIMARY KEY,
    job_type        TEXT NOT NULL,
    payload         TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'queued',
    attempts        INTEGER NOT NULL DEFAULT 0,
    max_attempts    INTEGER NOT NULL DEFAULT 5,
    result          TEXT,
    error           TEXT,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- Backup metadata table
CREATE TABLE backup_metadata (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- FTS5 virtual table for full-text search
-- External content table synced with memories table
CREATE VIRTUAL TABLE memories_fts USING fts5(
    content,
    tags,
    content='memories',
    content_rowid='rowid'
);

-- Indexes for performance optimization

-- Memories indexes
CREATE INDEX idx_memories_owner ON memories(owner_user_id);
CREATE INDEX idx_memories_status ON memories(status);
CREATE INDEX idx_memories_pending_expires ON memories(pending_expires_at) WHERE pending_expires_at IS NOT NULL;

-- Tasks indexes
CREATE INDEX idx_tasks_state ON tasks(state);
CREATE INDEX idx_tasks_owner ON tasks(owner_user_id);

-- Reminders indexes
CREATE INDEX idx_reminders_fire ON reminders(fire_at) WHERE fired = 0;

-- Events indexes
CREATE INDEX idx_events_status ON events(status);

-- Audit log indexes
CREATE INDEX idx_audit_entity ON audit_log(entity_type, entity_id);
