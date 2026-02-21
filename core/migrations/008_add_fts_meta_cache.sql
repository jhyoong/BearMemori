-- Migration 008: Add FTS5 indexed-content cache table
-- This table caches the last-indexed (content, tags) per memory so that
-- targeted FTS5 deletes can supply the exact original content, avoiding
-- "database disk image is malformed" errors on external-content FTS5 tables.

CREATE TABLE IF NOT EXISTS memories_fts_meta (
    memory_id  TEXT PRIMARY KEY,
    content    TEXT NOT NULL DEFAULT '',
    tags       TEXT NOT NULL DEFAULT ''
);
