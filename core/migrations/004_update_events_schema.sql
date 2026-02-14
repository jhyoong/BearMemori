-- Migration 004: Update events table schema to match API requirements
-- Rename and add columns for consistency with EventResponse schema

-- Rename event_date to event_time for consistency
ALTER TABLE events RENAME COLUMN event_date TO event_time;

-- Rename source_ref to source_detail for consistency
ALTER TABLE events RENAME COLUMN source_ref TO source_detail;

-- Add confirmed_at field
ALTER TABLE events ADD COLUMN confirmed_at TEXT;

-- Add updated_at field
ALTER TABLE events ADD COLUMN updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'));
