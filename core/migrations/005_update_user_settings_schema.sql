-- Update user_settings schema to match API requirements
-- Migration 005: Align user_settings table with shared.schemas

-- SQLite doesn't support multiple ALTER TABLE operations in a clean way,
-- so we need to recreate the table with the new schema

-- Step 1: Create new table with desired schema
CREATE TABLE user_settings_new (
    user_id       INTEGER PRIMARY KEY REFERENCES users(telegram_user_id),
    timezone      TEXT NOT NULL DEFAULT 'UTC',
    language      TEXT NOT NULL DEFAULT 'en',
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- Step 2: Copy existing data (if any) from old table to new table
-- Map timezone from old table, use default 'en' for language
INSERT INTO user_settings_new (user_id, timezone, language, created_at, updated_at)
SELECT
    telegram_user_id,
    timezone,
    'en',
    strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
    strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
FROM user_settings;

-- Step 3: Drop old table
DROP TABLE user_settings;

-- Step 4: Rename new table to original name
ALTER TABLE user_settings_new RENAME TO user_settings;
