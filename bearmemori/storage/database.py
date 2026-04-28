import json
import sqlite3
from datetime import UTC, datetime, timedelta

from bearmemori.storage.models import (
    Actor,
    AuditEntry,
    EventFields,
    MemoryCategory,
    MemoryRecord,
    MemorySource,
    ReflectionProposal,
)


def _normalize_to_utc(dt_str: str) -> str:
    """Parse an ISO 8601 datetime string and return it normalized to UTC."""
    parsed = datetime.fromisoformat(dt_str)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    else:
        parsed = parsed.astimezone(UTC)
    return parsed.isoformat()


class MemoryDatabase:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None

    def initialize(self) -> None:
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
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
                needs_review INTEGER NOT NULL DEFAULT 0,
                archived INTEGER NOT NULL DEFAULT 0
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
            CREATE INDEX IF NOT EXISTS idx_memories_importance
            ON memories (importance)
        """)
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_memories_archived
            ON memories (archived)
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
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                memory_id TEXT NOT NULL,
                action TEXT NOT NULL,
                actor TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                title_snapshot TEXT,
                category_snapshot TEXT
            )
        """)
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_audit_log_timestamp
            ON audit_log (timestamp DESC)
        """)
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_audit_log_memory_id
            ON audit_log (memory_id)
        """)
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_audit_log_actor
            ON audit_log (actor)
        """)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS reflection_proposals (
                id TEXT PRIMARY KEY,
                proposal_type TEXT NOT NULL,
                status TEXT NOT NULL,
                memory_ids TEXT NOT NULL,
                recommended_keep_id TEXT,
                recommended_importance INTEGER,
                reasoning TEXT NOT NULL,
                resolution_note TEXT,
                created_at TEXT NOT NULL,
                resolved_at TEXT
            )
        """)
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_reflection_proposals_status
            ON reflection_proposals (status)
        """)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS reflection_proposal_memories (
                proposal_id TEXT NOT NULL,
                memory_id TEXT NOT NULL,
                PRIMARY KEY (proposal_id, memory_id),
                FOREIGN KEY (proposal_id) REFERENCES reflection_proposals(id) ON DELETE CASCADE
            )
        """)
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_reflection_proposal_memories_memory
            ON reflection_proposal_memories (memory_id)
        """)
        self._conn.commit()

    def _migrate(self) -> None:
        """Add missing columns for existing databases.

        Handles: needs_review, image_path, importance, archived.
        """
        cursor = self._conn.execute(
            "SELECT name FROM pragma_table_info('memories') WHERE name = ?",
            ("needs_review",),
        )
        if cursor.fetchone() is None:
            self._conn.execute(
                "ALTER TABLE memories ADD COLUMN needs_review INTEGER NOT NULL DEFAULT 0"
            )
            self._conn.commit()

        cursor = self._conn.execute(
            "SELECT name FROM pragma_table_info('memories') WHERE name = ?",
            ("image_path",),
        )
        if cursor.fetchone() is None:
            self._conn.execute("ALTER TABLE memories ADD COLUMN image_path TEXT")
            self._conn.commit()

        cursor = self._conn.execute(
            "SELECT name FROM pragma_table_info('memories') WHERE name = ?",
            ("importance",),
        )
        if cursor.fetchone() is None:
            self._conn.execute(
                "ALTER TABLE memories ADD COLUMN importance INTEGER NOT NULL DEFAULT 5"
            )
            self._conn.commit()

        cursor = self._conn.execute(
            "SELECT name FROM pragma_table_info('memories') WHERE name = ?",
            ("archived",),
        )
        if cursor.fetchone() is None:
            self._conn.execute(
                "ALTER TABLE memories ADD COLUMN archived INTEGER NOT NULL DEFAULT 0"
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
            image_path=row["image_path"],
            importance=row["importance"],
            archived=bool(row["archived"]),
        )

    def create(self, record: MemoryRecord, *, actor: Actor) -> None:
        event_dt = None
        event_status = None
        event_recurrence = None
        if record.event_fields:
            event_dt = _normalize_to_utc(record.event_fields.datetime)
            event_status = record.event_fields.status
            event_recurrence = record.event_fields.recurrence

        source_json = record.source.model_dump_json() if record.source else None
        now = datetime.now(UTC).isoformat()

        self._conn.execute(
            """INSERT INTO memories
               (id, category, title, content, raw_input, created_at, updated_at,
                tags, source, event_datetime, event_status, event_recurrence,
                metadata, needs_review, image_path, importance, archived)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                record.image_path,
                record.importance,
                1 if record.archived else 0,
            ),
        )
        self._write_audit(
            memory_id=record.id,
            action="create",
            actor=actor,
            title_snapshot=record.title,
            category_snapshot=record.category.value,
        )
        self._conn.commit()

    def get(self, record_id: str) -> MemoryRecord | None:
        row = self._conn.execute("SELECT * FROM memories WHERE id = ?", (record_id,)).fetchone()
        return self._row_to_record(row) if row else None

    def delete(self, record_id: str, *, actor: Actor) -> bool:
        row = self._conn.execute(
            "SELECT title, category FROM memories WHERE id = ?",
            (record_id,),
        ).fetchone()
        if row is None:
            return False
        cursor = self._conn.execute("DELETE FROM memories WHERE id = ?", (record_id,))
        self._write_audit(
            memory_id=record_id,
            action="delete",
            actor=actor,
            title_snapshot=row["title"],
            category_snapshot=row["category"],
        )
        self._conn.commit()
        return cursor.rowcount > 0

    def delete_many(self, record_ids: list[str], *, actor: Actor) -> int:
        if not record_ids:
            return 0
        placeholders = ", ".join("?" * len(record_ids))
        rows = self._conn.execute(
            f"SELECT id, title, category FROM memories WHERE id IN ({placeholders})",
            record_ids,
        ).fetchall()
        snapshots = {r["id"]: (r["title"], r["category"]) for r in rows}
        cursor = self._conn.execute(
            f"DELETE FROM memories WHERE id IN ({placeholders})", record_ids
        )
        for mid, (title, category) in snapshots.items():
            self._write_audit(
                memory_id=mid,
                action="delete",
                actor=actor,
                title_snapshot=title,
                category_snapshot=category,
            )
        self._conn.commit()
        return cursor.rowcount

    def list_all(
        self, needs_review: bool | None = None, offset: int = 0, limit: int = 50
    ) -> list[MemoryRecord]:
        if needs_review is None:
            rows = self._conn.execute(
                "SELECT * FROM memories WHERE archived = 0"
                " ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM memories WHERE needs_review = ? AND archived = 0"
                " ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (1 if needs_review else 0, limit, offset),
            ).fetchall()
        return [self._row_to_record(r) for r in rows]

    def list_by_category(
        self, category: MemoryCategory, offset: int = 0, limit: int = 50
    ) -> list[MemoryRecord]:
        rows = self._conn.execute(
            "SELECT * FROM memories WHERE category = ? AND archived = 0"
            " ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (category.value, limit, offset),
        ).fetchall()
        return [self._row_to_record(r) for r in rows]

    def list_archived(self, offset: int = 0, limit: int = 50) -> list[MemoryRecord]:
        rows = self._conn.execute(
            "SELECT * FROM memories WHERE archived = 1 ORDER BY updated_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        return [self._row_to_record(r) for r in rows]

    def search_keyword(self, query: str, limit: int = 20) -> list[MemoryRecord]:
        rows = self._conn.execute(
            """SELECT memories.* FROM memories_fts
               JOIN memories ON memories.rowid = memories_fts.rowid
               WHERE memories_fts MATCH ? AND memories.archived = 0
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
                 AND archived = 0
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
                 AND archived = 0
               ORDER BY event_datetime ASC""",
            (now,),
        ).fetchall()
        return [self._row_to_record(r) for r in rows]

    def get_events_in_range(self, start: datetime, end: datetime) -> list[MemoryRecord]:
        start_iso = start.isoformat()
        end_iso = end.isoformat()
        rows = self._conn.execute(
            """SELECT * FROM memories
               WHERE category IN ('event', 'reminder', 'task')
                 AND archived = 0
                 AND (
                   (event_recurrence IS NULL
                    AND event_datetime IS NOT NULL
                    AND event_datetime >= ?
                    AND event_datetime <= ?)
                   OR
                   (event_recurrence IS NOT NULL
                    AND event_datetime <= ?
                    AND (event_status IS NULL OR event_status = 'pending'))
                 )
               ORDER BY event_datetime ASC""",
            (start_iso, end_iso, end_iso),
        ).fetchall()
        return [self._row_to_record(r) for r in rows]

    def count_all(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) FROM memories WHERE archived = 0").fetchone()
        return row[0]

    def count_needs_review(self) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) FROM memories WHERE needs_review = 1 AND archived = 0"
        ).fetchone()
        return row[0]

    def count_recent(self, hours: int = 24) -> dict:
        cutoff = (datetime.now(UTC) - timedelta(hours=hours)).isoformat()
        row = self._conn.execute(
            """SELECT
                   SUM(CASE WHEN created_at >= ? THEN 1 ELSE 0 END),
                   SUM(CASE WHEN updated_at >= ? THEN 1 ELSE 0 END)
               FROM memories WHERE archived = 0""",
            (cutoff, cutoff),
        ).fetchone()
        return {"created": row[0] or 0, "updated": row[1] or 0}

    def count_by_category(self, category: MemoryCategory) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) FROM memories WHERE category = ? AND archived = 0", (category.value,)
        ).fetchone()
        return row[0]

    def create_proposal(self, proposal: ReflectionProposal) -> None:
        """Insert a ReflectionProposal and its memory_id rows in one transaction."""
        self._conn.execute(
            """INSERT INTO reflection_proposals
               (id, proposal_type, status, memory_ids, recommended_keep_id,
                recommended_importance, reasoning, resolution_note,
                created_at, resolved_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                proposal.id,
                proposal.proposal_type,
                proposal.status,
                json.dumps(proposal.memory_ids),
                proposal.recommended_keep_id,
                proposal.recommended_importance,
                proposal.reasoning,
                proposal.resolution_note,
                proposal.created_at.isoformat(),
                proposal.resolved_at.isoformat() if proposal.resolved_at else None,
            ),
        )
        for memory_id in proposal.memory_ids:
            self._conn.execute(
                """INSERT INTO reflection_proposal_memories (proposal_id, memory_id)
                   VALUES (?, ?)""",
                (proposal.id, memory_id),
            )
        self._conn.commit()

    def _row_to_proposal(self, row: sqlite3.Row) -> ReflectionProposal:
        return ReflectionProposal(
            id=row["id"],
            proposal_type=row["proposal_type"],
            status=row["status"],
            memory_ids=json.loads(row["memory_ids"]),
            recommended_keep_id=row["recommended_keep_id"],
            recommended_importance=row["recommended_importance"],
            reasoning=row["reasoning"],
            resolution_note=row["resolution_note"],
            created_at=datetime.fromisoformat(row["created_at"]),
            resolved_at=datetime.fromisoformat(row["resolved_at"]) if row["resolved_at"] else None,
        )

    def get_proposal(self, proposal_id: str) -> ReflectionProposal | None:
        row = self._conn.execute(
            "SELECT * FROM reflection_proposals WHERE id = ?", (proposal_id,)
        ).fetchone()
        return self._row_to_proposal(row) if row else None

    def memory_ids_in_pending_proposals(self) -> set[str]:
        rows = self._conn.execute(
            """SELECT DISTINCT m.memory_id
               FROM reflection_proposal_memories m
               JOIN reflection_proposals p ON p.id = m.proposal_id
               WHERE p.status = 'pending'"""
        ).fetchall()
        return {r["memory_id"] for r in rows}

    def list_recently_updated(self, since: datetime, limit: int = 50) -> list[MemoryRecord]:
        since_iso = since.isoformat()
        rows = self._conn.execute(
            """SELECT * FROM memories
               WHERE updated_at >= ? AND archived = 0
               ORDER BY updated_at DESC
               LIMIT ?""",
            (since_iso, limit),
        ).fetchall()
        return [self._row_to_record(r) for r in rows]

    def _write_audit(
        self,
        memory_id: str,
        action: str,
        actor: Actor,
        title_snapshot: str | None,
        category_snapshot: str | None,
    ) -> None:
        self._conn.execute(
            """INSERT INTO audit_log
               (memory_id, action, actor, timestamp, title_snapshot, category_snapshot)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                memory_id,
                action,
                actor.value,
                datetime.now(UTC).isoformat(),
                title_snapshot,
                category_snapshot,
            ),
        )

    def list_audit(
        self,
        actor: Actor | None = None,
        action: str | None = None,
        memory_id: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> list[AuditEntry]:
        limit = min(limit, 500)
        clauses: list[str] = []
        params: list = []
        if actor is not None:
            clauses.append("actor = ?")
            params.append(actor.value)
        if action is not None:
            clauses.append("action = ?")
            params.append(action)
        if memory_id is not None:
            clauses.append("memory_id = ?")
            params.append(memory_id)
        if start is not None:
            clauses.append("timestamp >= ?")
            params.append(start.isoformat())
        if end is not None:
            clauses.append("timestamp <= ?")
            params.append(end.isoformat())
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        params.extend([limit, offset])
        rows = self._conn.execute(
            f"SELECT * FROM audit_log{where} ORDER BY timestamp DESC, id DESC LIMIT ? OFFSET ?",
            params,
        ).fetchall()
        return [
            AuditEntry(
                id=r["id"],
                memory_id=r["memory_id"],
                action=r["action"],
                actor=Actor(r["actor"]),
                timestamp=datetime.fromisoformat(r["timestamp"]),
                title_snapshot=r["title_snapshot"],
                category_snapshot=r["category_snapshot"],
            )
            for r in rows
        ]

    def update(self, record: MemoryRecord, *, actor: Actor) -> None:
        prev = self._conn.execute(
            "SELECT archived FROM memories WHERE id = ?", (record.id,)
        ).fetchone()
        prev_archived = bool(prev["archived"]) if prev else False
        becoming_archived = (not prev_archived) and record.archived
        action = "archive" if becoming_archived else "update"

        event_dt = None
        event_status = None
        event_recurrence = None
        if record.event_fields:
            event_dt = _normalize_to_utc(record.event_fields.datetime)
            event_status = record.event_fields.status
            event_recurrence = record.event_fields.recurrence

        source_json = record.source.model_dump_json() if record.source else None
        now = datetime.now(UTC).isoformat()

        self._conn.execute(
            """UPDATE memories SET category=?, title=?, content=?, raw_input=?,
               updated_at=?, tags=?, source=?, event_datetime=?, event_status=?,
               event_recurrence=?, metadata=?, needs_review=?, image_path=?,
               importance=?, archived=?
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
                record.image_path,
                record.importance,
                1 if record.archived else 0,
                record.id,
            ),
        )
        self._write_audit(
            memory_id=record.id,
            action=action,
            actor=actor,
            title_snapshot=record.title,
            category_snapshot=record.category.value,
        )
        self._conn.commit()
