import json
import sqlite3
from datetime import UTC, datetime, timedelta

from bearmemori.storage.models import (
    EventFields,
    MemoryCategory,
    MemoryRecord,
    MemorySource,
)


class MemoryDatabase:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None

    def initialize(self) -> None:
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id TEXT PRIMARY KEY,
                category TEXT NOT NULL,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                raw_input TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                tags TEXT NOT NULL DEFAULT '[]',
                source TEXT,
                event_datetime TEXT,
                event_status TEXT,
                event_recurrence TEXT,
                metadata TEXT NOT NULL DEFAULT '{}',
                needs_review INTEGER NOT NULL DEFAULT 0
            )
        """)
        self._migrate()
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_memories_category
            ON memories (category)
        """)
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_memories_event_datetime
            ON memories (event_datetime)
            WHERE event_datetime IS NOT NULL
        """)
        self._conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts
            USING fts5(title, content, tags, content=memories, content_rowid=rowid)
        """)
        self._conn.execute("""
            CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
                INSERT INTO memories_fts(rowid, title, content, tags)
                VALUES (new.rowid, new.title, new.content, new.tags);
            END
        """)
        self._conn.execute("""
            CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
                INSERT INTO memories_fts(memories_fts, rowid, title, content, tags)
                VALUES ('delete', old.rowid, old.title, old.content, old.tags);
            END
        """)
        self._conn.execute("""
            CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
                INSERT INTO memories_fts(memories_fts, rowid, title, content, tags)
                VALUES ('delete', old.rowid, old.title, old.content, old.tags);
                INSERT INTO memories_fts(rowid, title, content, tags)
                VALUES (new.rowid, new.title, new.content, new.tags);
            END
        """)
        self._conn.commit()

    def _migrate(self) -> None:
        """Add needs_review column if it doesn't exist (for existing databases)."""
        cursor = self._conn.execute(
            "SELECT name FROM pragma_table_info('memories') WHERE name = ?",
            ("needs_review",),
        )
        if cursor.fetchone() is None:
            self._conn.execute(
                "ALTER TABLE memories ADD COLUMN needs_review INTEGER NOT NULL DEFAULT 0"
            )
            self._conn.commit()

    def _row_to_record(self, row: sqlite3.Row) -> MemoryRecord:
        event_fields = None
        if row["event_datetime"] is not None:
            event_fields = EventFields(
                datetime=row["event_datetime"],
                status=row["event_status"] or "pending",
                recurrence=row["event_recurrence"],
            )

        source = None
        if row["source"] is not None:
            source = MemorySource.model_validate_json(row["source"])

        return MemoryRecord(
            id=row["id"],
            category=MemoryCategory(row["category"]),
            title=row["title"],
            content=row["content"],
            raw_input=row["raw_input"],
            created_at=datetime.fromisoformat(row["created_at"]),
            event_fields=event_fields,
            tags=json.loads(row["tags"]),
            source=source,
            metadata=json.loads(row["metadata"]),
            needs_review=bool(row["needs_review"]),
        )

    def create(self, record: MemoryRecord) -> None:
        event_dt = None
        event_status = None
        event_recurrence = None
        if record.event_fields:
            event_dt = record.event_fields.datetime
            event_status = record.event_fields.status
            event_recurrence = record.event_fields.recurrence

        source_json = record.source.model_dump_json() if record.source else None
        now = datetime.now(UTC).isoformat()

        self._conn.execute(
            """INSERT INTO memories
               (id, category, title, content, raw_input, created_at, updated_at,
                tags, source, event_datetime, event_status, event_recurrence,
                metadata, needs_review)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                record.id,
                record.category.value,
                record.title,
                record.content,
                record.raw_input,
                record.created_at.isoformat(),
                now,
                json.dumps(record.tags),
                source_json,
                event_dt,
                event_status,
                event_recurrence,
                json.dumps(record.metadata),
                1 if record.needs_review else 0,
            ),
        )
        self._conn.commit()

    def get(self, record_id: str) -> MemoryRecord | None:
        row = self._conn.execute("SELECT * FROM memories WHERE id = ?", (record_id,)).fetchone()
        return self._row_to_record(row) if row else None

    def delete(self, record_id: str) -> bool:
        cursor = self._conn.execute("DELETE FROM memories WHERE id = ?", (record_id,))
        self._conn.commit()
        return cursor.rowcount > 0

    def delete_many(self, record_ids: list[str]) -> int:
        if not record_ids:
            return 0
        placeholders = ", ".join("?" * len(record_ids))
        cursor = self._conn.execute(
            f"DELETE FROM memories WHERE id IN ({placeholders})", record_ids
        )
        self._conn.commit()
        return cursor.rowcount

    def list_all(self, needs_review: bool | None = None) -> list[MemoryRecord]:
        if needs_review is None:
            rows = self._conn.execute("SELECT * FROM memories ORDER BY created_at DESC").fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM memories WHERE needs_review = ? ORDER BY created_at DESC",
                (1 if needs_review else 0,),
            ).fetchall()
        return [self._row_to_record(r) for r in rows]

    def list_by_category(self, category: MemoryCategory) -> list[MemoryRecord]:
        rows = self._conn.execute(
            "SELECT * FROM memories WHERE category = ? ORDER BY created_at DESC",
            (category.value,),
        ).fetchall()
        return [self._row_to_record(r) for r in rows]

    def search_keyword(self, query: str, limit: int = 20) -> list[MemoryRecord]:
        rows = self._conn.execute(
            """SELECT memories.* FROM memories_fts
               JOIN memories ON memories.rowid = memories_fts.rowid
               WHERE memories_fts MATCH ?
               ORDER BY rank
               LIMIT ?""",
            (query, limit),
        ).fetchall()
        return [self._row_to_record(r) for r in rows]

    def get_upcoming_events(self, days: int = 7) -> list[MemoryRecord]:
        now = datetime.now(UTC).isoformat()
        future = (datetime.now(UTC) + timedelta(days=days)).isoformat()
        rows = self._conn.execute(
            """SELECT * FROM memories
               WHERE category IN ('event', 'reminder', 'task')
                 AND event_datetime IS NOT NULL
                 AND event_datetime >= ?
                 AND event_datetime <= ?
                 AND (event_status IS NULL OR event_status = 'pending')
               ORDER BY event_datetime ASC""",
            (now, future),
        ).fetchall()
        return [self._row_to_record(r) for r in rows]

    def get_due_events(self) -> list[MemoryRecord]:
        now = datetime.now(UTC).isoformat()
        rows = self._conn.execute(
            """SELECT * FROM memories
               WHERE category IN ('event', 'reminder', 'task')
                 AND event_datetime IS NOT NULL
                 AND event_datetime <= ?
                 AND (event_status IS NULL OR event_status = 'pending')
               ORDER BY event_datetime ASC""",
            (now,),
        ).fetchall()
        return [self._row_to_record(r) for r in rows]

    def update(self, record: MemoryRecord) -> None:
        event_dt = None
        event_status = None
        event_recurrence = None
        if record.event_fields:
            event_dt = record.event_fields.datetime
            event_status = record.event_fields.status
            event_recurrence = record.event_fields.recurrence

        source_json = record.source.model_dump_json() if record.source else None
        now = datetime.now(UTC).isoformat()

        self._conn.execute(
            """UPDATE memories SET category=?, title=?, content=?, raw_input=?,
               updated_at=?, tags=?, source=?, event_datetime=?, event_status=?,
               event_recurrence=?, metadata=?, needs_review=?
               WHERE id=?""",
            (
                record.category.value,
                record.title,
                record.content,
                record.raw_input,
                now,
                json.dumps(record.tags),
                source_json,
                event_dt,
                event_status,
                event_recurrence,
                json.dumps(record.metadata),
                1 if record.needs_review else 0,
                record.id,
            ),
        )
        self._conn.commit()
