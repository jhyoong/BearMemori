"""FTS5 full-text search module for memories."""

import logging

import aiosqlite

logger = logging.getLogger(__name__)

STOP_WORDS = frozenset({
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "it", "this", "that", "are", "was",
    "be", "has", "had", "do", "does", "did", "will", "can", "could",
    "should", "would", "may", "might", "about", "all", "my", "me", "i",
    "you", "your", "we", "our", "they", "their", "what", "which", "who",
    "how", "when", "where", "find", "search", "show", "get", "list",
    "tell", "give",
})


async def _get_cached_fts_data(
    db: aiosqlite.Connection, memory_id: str
) -> tuple[str, str] | None:
    """Return the (content, tags) that were last written into the FTS5 index.

    Returns None if no cached entry exists (memory has not been indexed yet).
    """
    cursor = await db.execute(
        "SELECT content, tags FROM memories_fts_meta WHERE memory_id = ?",
        (memory_id,),
    )
    row = await cursor.fetchone()
    if row is None:
        return None
    return row[0], row[1]


async def _get_memory_fts_data(
    db: aiosqlite.Connection, memory_id: str
) -> tuple[int, str, str] | None:
    """Fetch the rowid, content, and current confirmed tags for a memory.

    Returns None if the memory does not exist.
    """
    cursor = await db.execute(
        "SELECT rowid, content FROM memories WHERE id = ?",
        (memory_id,),
    )
    row = await cursor.fetchone()
    if row is None:
        return None

    memory_rowid = row[0]
    content = row[1] or ""

    tag_cursor = await db.execute(
        "SELECT tag FROM memory_tags WHERE memory_id = ? AND status = 'confirmed'",
        (memory_id,),
    )
    tag_rows = await tag_cursor.fetchall()
    tags = " ".join(t[0] for t in tag_rows)

    return memory_rowid, content, tags


async def _write_fts_meta(
    db: aiosqlite.Connection, memory_id: str, content: str, tags: str
) -> None:
    """Upsert the cached FTS5 indexed content for a memory."""
    await db.execute(
        "INSERT OR REPLACE INTO memories_fts_meta (memory_id, content, tags) "
        "VALUES (?, ?, ?)",
        (memory_id, content, tags),
    )


async def _delete_fts_meta(db: aiosqlite.Connection, memory_id: str) -> None:
    """Remove the cached FTS5 entry for a memory."""
    await db.execute(
        "DELETE FROM memories_fts_meta WHERE memory_id = ?",
        (memory_id,),
    )


async def rebuild_fts_index(db: aiosqlite.Connection) -> None:
    """Full rebuild of the FTS5 index. Use as a maintenance fallback only."""
    await db.execute("INSERT INTO memories_fts(memories_fts) VALUES('delete-all')")
    await db.execute("DELETE FROM memories_fts_meta")

    cursor = await db.execute(
        "SELECT rowid, id, content FROM memories WHERE status = 'confirmed'"
    )
    memories = await cursor.fetchall()

    for memory_rowid, memory_id, content in memories:
        tag_cursor = await db.execute(
            "SELECT tag FROM memory_tags "
            "WHERE memory_id = ? AND status = 'confirmed'",
            (memory_id,),
        )
        tag_rows = await tag_cursor.fetchall()
        tags = " ".join(tag[0] for tag in tag_rows)

        await db.execute(
            "INSERT INTO memories_fts(rowid, content, tags) VALUES (?, ?, ?)",
            (memory_rowid, content or "", tags),
        )
        await _write_fts_meta(db, memory_id, content or "", tags)

    await db.commit()


async def index_memory(db: aiosqlite.Connection, memory_id: str) -> None:
    """Index or re-index a single memory in FTS5.

    Only indexes confirmed memories. If the memory is not confirmed,
    any existing FTS5 entry is removed.
    """
    # Check memory status
    status_cursor = await db.execute(
        "SELECT status FROM memories WHERE id = ?", (memory_id,)
    )
    status_row = await status_cursor.fetchone()
    if status_row is None:
        return

    if status_row[0] != "confirmed":
        await remove_from_index(db, memory_id)
        return

    data = await _get_memory_fts_data(db, memory_id)
    if data is None:
        return

    memory_rowid, content, tags = data

    # If there is a prior cached entry, delete it using the EXACT original content.
    # The FTS5 'delete' command for external-content tables requires that the
    # content matches what was indexed; using any other value corrupts the index.
    cached = await _get_cached_fts_data(db, memory_id)
    if cached is not None:
        old_content, old_tags = cached
        await db.execute(
            "INSERT INTO memories_fts(memories_fts, rowid, content, tags) "
            "VALUES('delete', ?, ?, ?)",
            (memory_rowid, old_content, old_tags),
        )

    # Insert the current (new) entry and update the cache.
    await db.execute(
        "INSERT INTO memories_fts(rowid, content, tags) VALUES (?, ?, ?)",
        (memory_rowid, content, tags),
    )
    await _write_fts_meta(db, memory_id, content, tags)
    await db.commit()


async def remove_from_index(db: aiosqlite.Connection, memory_id: str) -> None:
    """Remove a single memory from the FTS5 index."""
    cached = await _get_cached_fts_data(db, memory_id)
    if cached is None:
        return

    cached_content, cached_tags = cached

    rowid_cursor = await db.execute(
        "SELECT rowid FROM memories WHERE id = ?", (memory_id,)
    )
    rowid_row = await rowid_cursor.fetchone()
    if rowid_row is None:
        return

    try:
        await db.execute(
            "INSERT INTO memories_fts(memories_fts, rowid, content, tags) "
            "VALUES('delete', ?, ?, ?)",
            (rowid_row[0], cached_content, cached_tags),
        )
        await _delete_fts_meta(db, memory_id)
        await db.commit()
    except Exception:
        pass


async def search_memories(
    db: aiosqlite.Connection,
    query: str,
    owner_user_id: int,
    pinned_only: bool = False,
    limit: int = 20,
    offset: int = 0,
) -> list[dict]:
    """Query FTS5 and return results with pin boost."""
    terms = query.split()
    filtered = [t for t in terms if t.lower() not in STOP_WORDS]
    if not filtered:
        filtered = terms  # fallback: use original if all words are stop words
    sanitized_query = " OR ".join(f'"{term}"' for term in filtered if term)

    logger.info(
        "search_memories: raw_query=%r, terms=%s, filtered=%s, fts_query=%r, owner=%s",
        query, terms, filtered, sanitized_query, owner_user_id,
    )

    if not sanitized_query:
        return []

    sql = """
        SELECT m.*, memories_fts.rank
        FROM memories_fts
        JOIN memories m ON m.rowid = memories_fts.rowid
        WHERE memories_fts MATCH ?
        AND m.owner_user_id = ?
        AND m.status = 'confirmed'
    """

    params: list = [sanitized_query, owner_user_id]

    if pinned_only:
        sql += " AND m.is_pinned = 1"

    sql += " ORDER BY m.is_pinned DESC, rank"
    sql += " LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    cursor = await db.execute(sql, params)
    rows = await cursor.fetchall()

    column_names = [description[0] for description in cursor.description]

    results = []
    for row in rows:
        memory_dict = dict(zip(column_names, row))

        tag_cursor = await db.execute(
            "SELECT tag FROM memory_tags "
            "WHERE memory_id = ? AND status = 'confirmed'",
            (memory_dict["id"],),
        )
        tag_rows = await tag_cursor.fetchall()
        memory_dict["tags"] = [tag[0] for tag in tag_rows]

        results.append(memory_dict)

    return results
