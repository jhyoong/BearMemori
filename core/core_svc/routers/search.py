"""Search router with FTS5 full-text search."""

import logging
from datetime import datetime

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Query, status

from core_svc.database import get_db
from core_svc.search import search_memories
from shared_lib.schemas import MemorySearchResult, MemoryWithTags, MemoryTagResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["search"])


def parse_db_datetime(dt_str: str | None) -> datetime | None:
    """Parse datetime string from database, handling both 'Z' and '+00:00' formats."""
    if not dt_str:
        return None
    # Handle edge case: string ending with both timezone offset and 'Z' (e.g., '+00:00Z')
    if "+" in dt_str and dt_str.endswith("Z"):
        dt_str = dt_str[:-1]  # Remove trailing 'Z'
    # Replace 'Z' with '+00:00' for ISO parsing
    elif dt_str.endswith("Z"):
        dt_str = dt_str.replace("Z", "+00:00")
    return datetime.fromisoformat(dt_str)


@router.get("", response_model=list[MemorySearchResult])
async def search(
    q: str = Query(..., description="Search query string"),
    owner: int = Query(..., description="User ID to filter by"),
    pinned: bool = Query(False, description="Only return pinned memories"),
    db: aiosqlite.Connection = Depends(get_db),
) -> list[MemorySearchResult]:
    """
    Search memories using FTS5 full-text search.

    - Query params: q (required, search query string), owner (required, user_id), pinned (optional bool, default false)
    - Call search_memories() from core.search
    - Return: list[MemorySearchResult] (each containing MemoryWithTags + score)
    - If q is empty or only whitespace: return 400
    """
    # Validate query string - allow empty query when pinned=true to fetch all pinned memories
    fetch_pinned_only = False
    if not q or not q.strip():
        if not pinned:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Search query cannot be empty or whitespace",
            )
        # When pinned=true with empty query, fetch all pinned memories directly
        fetch_pinned_only = True

    if fetch_pinned_only:
        # Query all pinned memories directly without FTS5
        cursor = await db.execute(
            """
            SELECT id, owner_user_id, content, media_type, media_file_id,
                   media_local_path, status, pending_expires_at, is_pinned,
                   created_at, updated_at
            FROM memories
            WHERE owner_user_id = ? AND status = 'confirmed' AND is_pinned = 1
            ORDER BY created_at DESC
            """,
            (owner,),
        )
        rows = await cursor.fetchall()
        search_results = []
        for row in rows:
            search_results.append(
                {
                    "id": row["id"],
                    "owner_user_id": row["owner_user_id"],
                    "content": row["content"],
                    "media_type": row["media_type"],
                    "media_file_id": row["media_file_id"],
                    "media_local_path": row["media_local_path"],
                    "status": row["status"],
                    "pending_expires_at": row["pending_expires_at"],
                    "is_pinned": row["is_pinned"],
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                    "rank": 0.0,  # No ranking for pinned-only query
                }
            )
    else:
        # Call search_memories function for normal search
        search_results = await search_memories(
            db=db, query=q, owner_user_id=owner, pinned_only=pinned
        )

    # Batch fetch all tags for all memories in one query
    memory_ids = [result["id"] for result in search_results]
    tags_by_memory = {}

    if memory_ids:
        placeholders = ",".join("?" * len(memory_ids))
        tag_cursor = await db.execute(
            f"""
            SELECT memory_id, tag, status, suggested_at, confirmed_at
            FROM memory_tags
            WHERE memory_id IN ({placeholders})
            """,
            memory_ids,
        )
        all_tags = await tag_cursor.fetchall()

        # Group tags by memory_id
        for tag_row in all_tags:
            memory_id = tag_row["memory_id"]
            if memory_id not in tags_by_memory:
                tags_by_memory[memory_id] = []

            tags_by_memory[memory_id].append(
                MemoryTagResponse(
                    tag=tag_row["tag"],
                    status=tag_row["status"],
                    suggested_at=parse_db_datetime(tag_row["suggested_at"]),
                    confirmed_at=parse_db_datetime(tag_row["confirmed_at"]),
                )
            )

    # Transform results into MemorySearchResult objects
    response = []
    for result in search_results:
        # Get tags for this memory from the batch-fetched tags
        memory_tags = tags_by_memory.get(result["id"], [])

        # Build MemoryWithTags object
        memory = MemoryWithTags(
            id=result["id"],
            owner_user_id=result["owner_user_id"],
            content=result["content"],
            media_type=result["media_type"],
            media_file_id=result["media_file_id"],
            media_local_path=result["media_local_path"],
            status=result["status"],
            pending_expires_at=parse_db_datetime(result["pending_expires_at"]),
            is_pinned=bool(result["is_pinned"]),
            created_at=parse_db_datetime(result["created_at"]),
            updated_at=parse_db_datetime(result["updated_at"]),
            tags=memory_tags,
        )

        # Build MemorySearchResult with memory and score (rank)
        response.append(MemorySearchResult(memory=memory, score=result["rank"]))

    return response
