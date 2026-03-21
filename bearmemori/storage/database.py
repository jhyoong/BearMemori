import json
import sqlite3
from datetime import datetime

from bearmemori.storage.models import Memory


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
                content TEXT NOT NULL,
                raw_input TEXT NOT NULL,
                memory_type TEXT NOT NULL,
                tags TEXT NOT NULL DEFAULT '[]',
                embedding BLOB,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'unknown',
                metadata TEXT NOT NULL DEFAULT '{}'
            )
        """)
        self._conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts
            USING fts5(content, tags, content=memories, content_rowid=rowid)
        """)
        self._conn.execute("""
            CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
                INSERT INTO memories_fts(rowid, content, tags)
                VALUES (new.rowid, new.content, new.tags);
            END
        """)
        self._conn.execute("""
            CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
                INSERT INTO memories_fts(memories_fts, rowid, content, tags)
                VALUES ('delete', old.rowid, old.content, old.tags);
            END
        """)
        self._conn.execute("""
            CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
                INSERT INTO memories_fts(memories_fts, rowid, content, tags)
                VALUES ('delete', old.rowid, old.content, old.tags);
                INSERT INTO memories_fts(rowid, content, tags)
                VALUES (new.rowid, new.content, new.tags);
            END
        """)
        self._conn.commit()

    def _row_to_memory(self, row: sqlite3.Row) -> Memory:
        return Memory(
            id=row["id"],
            content=row["content"],
            raw_input=row["raw_input"],
            memory_type=row["memory_type"],
            tags=json.loads(row["tags"]),
            embedding=row["embedding"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            source=row["source"],
            metadata=json.loads(row["metadata"]),
        )

    def create(self, memory: Memory) -> None:
        self._conn.execute(
            """INSERT INTO memories (id, content, raw_input, memory_type, tags, embedding,
               created_at, updated_at, source, metadata)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                memory.id,
                memory.content,
                memory.raw_input,
                memory.memory_type,
                json.dumps(memory.tags),
                memory.embedding,
                memory.created_at.isoformat(),
                memory.updated_at.isoformat(),
                memory.source,
                json.dumps(memory.metadata),
            ),
        )
        self._conn.commit()

    def get(self, memory_id: str) -> Memory | None:
        row = self._conn.execute(
            "SELECT * FROM memories WHERE id = ?", (memory_id,)
        ).fetchone()
        return self._row_to_memory(row) if row else None

    def update(self, memory: Memory) -> None:
        memory.updated_at = datetime.now()
        self._conn.execute(
            """UPDATE memories SET content=?, raw_input=?, memory_type=?, tags=?,
               embedding=?, updated_at=?, source=?, metadata=?
               WHERE id=?""",
            (
                memory.content,
                memory.raw_input,
                memory.memory_type,
                json.dumps(memory.tags),
                memory.embedding,
                memory.updated_at.isoformat(),
                memory.source,
                json.dumps(memory.metadata),
                memory.id,
            ),
        )
        self._conn.commit()

    def delete(self, memory_id: str) -> None:
        self._conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
        self._conn.commit()

    def search_keyword(self, query: str, limit: int = 20) -> list[Memory]:
        rows = self._conn.execute(
            """SELECT memories.* FROM memories_fts
               JOIN memories ON memories.rowid = memories_fts.rowid
               WHERE memories_fts MATCH ?
               ORDER BY rank
               LIMIT ?""",
            (query, limit),
        ).fetchall()
        return [self._row_to_memory(row) for row in rows]

    def list_memories(
        self,
        memory_type: str | None = None,
        tag: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Memory]:
        query = "SELECT * FROM memories WHERE 1=1"
        params: list = []
        if memory_type:
            query += " AND memory_type = ?"
            params.append(memory_type)
        if tag:
            query += " AND json_each.value = ?"
            query = query.replace(
                "FROM memories",
                "FROM memories, json_each(memories.tags)",
            )
            params.append(tag)
        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        rows = self._conn.execute(query, params).fetchall()
        return [self._row_to_memory(row) for row in rows]
