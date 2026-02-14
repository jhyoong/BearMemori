-- Migration 003: Add text and updated_at fields to reminders table
-- These fields are needed for storing reminder messages and tracking modifications

ALTER TABLE reminders ADD COLUMN text TEXT;
ALTER TABLE reminders ADD COLUMN updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'));
