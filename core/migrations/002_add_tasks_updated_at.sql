-- Migration 002: Add updated_at field to tasks table
-- This field is needed to track when tasks are last modified

ALTER TABLE tasks ADD COLUMN updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'));
