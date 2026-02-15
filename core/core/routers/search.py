"""Search router with FTS5 full-text search."""

import logging
from datetime import datetime

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Query, status

from core.database import get_db
from core.search import search_memories
from shared.schemas import MemorySearchResult, MemoryWithTags, MemoryTagResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["search"])


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
    # Validate query string
    if not q or not q.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Search query cannot be empty or whitespace"
        )

    # Call search_memories function
    search_results = await search_memories(
        db=db,
        query=q,
        owner_user_id=owner,
        pinned_only=pinned
    )

    # Transform results into MemorySearchResult objects
    response = []
    for result in search_results:
        # Build MemoryTagResponse objects from tag strings
        memory_tags = []
        for tag_str in result.get('tags', []):
            # Fetch full tag information from memory_tags table
            tag_cursor = await db.execute(
                """
                SELECT tag, status, suggested_at, confirmed_at
                FROM memory_tags
                WHERE memory_id = ? AND tag = ?
                """,
                (result['id'], tag_str)
            )
            tag_row = await tag_cursor.fetchone()

            if tag_row:
                memory_tags.append(
                    MemoryTagResponse(
                        tag=tag_row["tag"],
                        status=tag_row["status"],
                        suggested_at=datetime.fromisoformat(tag_row["suggested_at"].replace('Z', '+00:00')) if tag_row["suggested_at"] else None,
                        confirmed_at=datetime.fromisoformat(tag_row["confirmed_at"].replace('Z', '+00:00')) if tag_row["confirmed_at"] else None,
                    )
                )

        # Build MemoryWithTags object
        memory = MemoryWithTags(
            id=result['id'],
            owner_user_id=result['owner_user_id'],
            content=result['content'],
            media_type=result['media_type'],
            media_file_id=result['media_file_id'],
            media_local_path=result['media_local_path'],
            status=result['status'],
            pending_expires_at=datetime.fromisoformat(result['pending_expires_at'].replace('Z', '+00:00')) if result['pending_expires_at'] else None,
            is_pinned=bool(result['is_pinned']),
            created_at=datetime.fromisoformat(result['created_at'].replace('Z', '+00:00')),
            updated_at=datetime.fromisoformat(result['updated_at'].replace('Z', '+00:00')),
            tags=memory_tags,
        )

        # Build MemorySearchResult with memory and score (rank)
        response.append(
            MemorySearchResult(
                memory=memory,
                score=result['rank']
            )
        )

    return response
