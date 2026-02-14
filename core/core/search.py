"""FTS5 full-text search module for memories."""

import aiosqlite


async def _rebuild_fts_index(db: aiosqlite.Connection) -> None:
    """
    Rebuild the FTS5 index with only confirmed memories.

    This is the safe approach for external content FTS5 tables.
    """
    # Clear the entire FTS5 index
    await db.execute("INSERT INTO memories_fts(memories_fts) VALUES('delete-all')")

    # Fetch all confirmed memories with their tags
    cursor = await db.execute(
        "SELECT rowid, id, content FROM memories WHERE status = 'confirmed'"
    )
    memories = await cursor.fetchall()

    # Index each confirmed memory
    for memory_rowid, memory_id, content in memories:
        # Fetch confirmed tags for this memory
        tag_cursor = await db.execute(
            "SELECT tag FROM memory_tags WHERE memory_id = ? AND status = 'confirmed'",
            (memory_id,)
        )
        tag_rows = await tag_cursor.fetchall()
        tags = ' '.join(tag[0] for tag in tag_rows)

        # Insert into FTS5 index
        await db.execute(
            "INSERT INTO memories_fts(rowid, content, tags) VALUES (?, ?, ?)",
            (memory_rowid, content, tags)
        )

    await db.commit()


async def index_memory(db: aiosqlite.Connection, memory_id: str) -> None:
    """
    Upsert the FTS5 entry for a memory. Only indexes confirmed memories.

    For external content FTS5 tables, the safest approach is to rebuild the entire index.

    Args:
        db: Database connection
        memory_id: UUID of the memory to index
    """
    await _rebuild_fts_index(db)


async def remove_from_index(db: aiosqlite.Connection, memory_id: str) -> None:
    """
    Remove the FTS5 entry for a memory by rebuilding the index.

    For external content FTS5 tables, the safest approach is to rebuild.

    Args:
        db: Database connection
        memory_id: UUID of the memory to remove from index
    """
    await _rebuild_fts_index(db)


async def search_memories(
    db: aiosqlite.Connection,
    query: str,
    owner_user_id: int,
    pinned_only: bool = False,
    limit: int = 20,
    offset: int = 0
) -> list[dict]:
    """
    Query FTS5 and return results with pin boost.

    Args:
        db: Database connection
        query: Search query string
        owner_user_id: User ID to filter by
        pinned_only: If True, only return pinned memories
        limit: Maximum number of results to return
        offset: Number of results to skip for pagination

    Returns:
        List of memory dictionaries with tags and relevance score
    """
    # Sanitize FTS5 query by wrapping each term in double quotes
    # This treats them as literal phrases and avoids FTS5 syntax errors
    terms = query.split()
    sanitized_query = ' '.join(f'"{term}"' for term in terms if term)

    if not sanitized_query:
        return []

    # Build the query
    sql = """
        SELECT m.*, memories_fts.rank
        FROM memories_fts
        JOIN memories m ON m.rowid = memories_fts.rowid
        WHERE memories_fts MATCH ?
        AND m.owner_user_id = ?
        AND m.status = 'confirmed'
    """

    params = [sanitized_query, owner_user_id]

    if pinned_only:
        sql += " AND m.is_pinned = 1"

    # Order by pinned first, then by relevance rank
    sql += " ORDER BY m.is_pinned DESC, rank"

    # Apply pagination
    sql += " LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    # Execute query
    cursor = await db.execute(sql, params)
    rows = await cursor.fetchall()

    # Get column names
    column_names = [description[0] for description in cursor.description]

    # Build result list
    results = []
    for row in rows:
        # Convert row to dict
        memory_dict = dict(zip(column_names, row))

        # Fetch tags for this memory
        tag_cursor = await db.execute(
            "SELECT tag FROM memory_tags WHERE memory_id = ? AND status = 'confirmed'",
            (memory_dict['id'],)
        )
        tag_rows = await tag_cursor.fetchall()
        memory_dict['tags'] = [tag[0] for tag in tag_rows]

        results.append(memory_dict)

    return results
