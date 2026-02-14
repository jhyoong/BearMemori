"""Memories router with FTS5 integration."""

import os
import uuid
from datetime import datetime, timedelta

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, status

from core.audit import log_audit
from core.database import get_db
from core.search import index_memory, remove_from_index
from shared.schemas import (
    MemoryCreate,
    MemoryResponse,
    MemoryUpdate,
    MemoryWithTags,
    MemoryTagResponse,
    TagsAddRequest,
)

router = APIRouter(prefix="/memories", tags=["memories"])


@router.post("", response_model=MemoryResponse, status_code=status.HTTP_201_CREATED)
async def create_memory(
    memory: MemoryCreate,
    db: aiosqlite.Connection = Depends(get_db),
) -> MemoryResponse:
    """
    Create a new memory.

    - If media_type == "image": set status = "pending", set pending_expires_at = now + 7 days
    - If media_type is None (text): set status = "confirmed"
    - Insert into memories table
    - If status is confirmed: call index_memory() to sync FTS5
    - Call log_audit() to log the creation
    """
    # Generate UUID for id
    memory_id = str(uuid.uuid4())

    # Determine status and pending_expires_at based on media_type
    if memory.media_type == "image":
        memory_status = "pending"
        pending_expires_at = (datetime.utcnow() + timedelta(days=7)).isoformat() + 'Z'
    else:
        memory_status = "confirmed"
        pending_expires_at = None

    # Insert into memories table
    await db.execute(
        """
        INSERT INTO memories (
            id, owner_user_id, content, media_type, media_file_id,
            source_chat_id, source_message_id, status, pending_expires_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            memory_id,
            memory.owner_user_id,
            memory.content,
            memory.media_type,
            memory.media_file_id,
            memory.source_chat_id,
            memory.source_message_id,
            memory_status,
            pending_expires_at,
        ),
    )
    await db.commit()

    # If status is confirmed, sync FTS5
    if memory_status == "confirmed":
        await index_memory(db, memory_id)

    # Log audit
    await log_audit(db, "memory", memory_id, "created", f"user:{memory.owner_user_id}")

    # Fetch and return the created memory
    cursor = await db.execute(
        "SELECT * FROM memories WHERE id = ?",
        (memory_id,),
    )
    row = await cursor.fetchone()

    return MemoryResponse(
        id=row["id"],
        owner_user_id=row["owner_user_id"],
        content=row["content"],
        media_type=row["media_type"],
        media_file_id=row["media_file_id"],
        media_local_path=row["media_local_path"],
        status=row["status"],
        pending_expires_at=datetime.fromisoformat(row["pending_expires_at"].replace('Z', '+00:00')) if row["pending_expires_at"] else None,
        is_pinned=bool(row["is_pinned"]),
        created_at=datetime.fromisoformat(row["created_at"].replace('Z', '+00:00')),
        updated_at=datetime.fromisoformat(row["updated_at"].replace('Z', '+00:00')),
    )


@router.get("/{id}", response_model=MemoryWithTags)
async def get_memory(
    id: str,
    db: aiosqlite.Connection = Depends(get_db),
) -> MemoryWithTags:
    """
    Fetch a memory by ID with its tags.

    - Fetch memory by ID from memories table
    - If not found: return 404
    - Fetch tags from memory_tags WHERE memory_id = ?
    - Return: MemoryWithTags
    """
    # Fetch memory
    cursor = await db.execute(
        "SELECT * FROM memories WHERE id = ?",
        (id,),
    )
    row = await cursor.fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail="Memory not found")

    # Fetch tags
    tag_cursor = await db.execute(
        "SELECT tag, status, suggested_at, confirmed_at FROM memory_tags WHERE memory_id = ?",
        (id,),
    )
    tag_rows = await tag_cursor.fetchall()

    tags = [
        MemoryTagResponse(
            tag=tag_row["tag"],
            status=tag_row["status"],
            suggested_at=datetime.fromisoformat(tag_row["suggested_at"].replace('Z', '+00:00')) if tag_row["suggested_at"] else None,
            confirmed_at=datetime.fromisoformat(tag_row["confirmed_at"].replace('Z', '+00:00')) if tag_row["confirmed_at"] else None,
        )
        for tag_row in tag_rows
    ]

    return MemoryWithTags(
        id=row["id"],
        owner_user_id=row["owner_user_id"],
        content=row["content"],
        media_type=row["media_type"],
        media_file_id=row["media_file_id"],
        media_local_path=row["media_local_path"],
        status=row["status"],
        pending_expires_at=datetime.fromisoformat(row["pending_expires_at"].replace('Z', '+00:00')) if row["pending_expires_at"] else None,
        is_pinned=bool(row["is_pinned"]),
        created_at=datetime.fromisoformat(row["created_at"].replace('Z', '+00:00')),
        updated_at=datetime.fromisoformat(row["updated_at"].replace('Z', '+00:00')),
        tags=tags,
    )


@router.patch("/{id}", response_model=MemoryResponse)
async def update_memory(
    id: str,
    memory_update: MemoryUpdate,
    db: aiosqlite.Connection = Depends(get_db),
) -> MemoryResponse:
    """
    Update a memory by ID.

    - Fetch existing memory; 404 if not found
    - Build UPDATE query for only the provided fields
    - Always set updated_at = now
    - If status changes to confirmed: call index_memory() to sync FTS5
    - If is_pinned changes: no FTS5 re-index needed (pin boost is at query time)
    - Call log_audit() to log the update
    """
    # Fetch existing memory
    cursor = await db.execute(
        "SELECT * FROM memories WHERE id = ?",
        (id,),
    )
    row = await cursor.fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail="Memory not found")

    # Build UPDATE query for provided fields
    update_fields = []
    update_values = []
    changed_fields = {}

    if memory_update.content is not None:
        update_fields.append("content = ?")
        update_values.append(memory_update.content)
        changed_fields["content"] = memory_update.content

    if memory_update.status is not None:
        update_fields.append("status = ?")
        update_values.append(memory_update.status)
        changed_fields["status"] = memory_update.status

    if memory_update.is_pinned is not None:
        update_fields.append("is_pinned = ?")
        update_values.append(1 if memory_update.is_pinned else 0)
        changed_fields["is_pinned"] = memory_update.is_pinned

    if memory_update.media_local_path is not None:
        update_fields.append("media_local_path = ?")
        update_values.append(memory_update.media_local_path)
        changed_fields["media_local_path"] = memory_update.media_local_path

    # Always set updated_at
    update_fields.append("updated_at = ?")
    updated_at = datetime.utcnow().isoformat() + 'Z'
    update_values.append(updated_at)

    # Add id to values for WHERE clause
    update_values.append(id)

    # Execute update
    if update_fields:
        sql = f"UPDATE memories SET {', '.join(update_fields)} WHERE id = ?"
        await db.execute(sql, update_values)
        await db.commit()

    # If status changes to confirmed, sync FTS5
    if memory_update.status == "confirmed":
        await index_memory(db, id)

    # Log audit
    owner_user_id = row["owner_user_id"]
    await log_audit(
        db,
        "memory",
        id,
        "updated",
        f"user:{owner_user_id}",
        detail=changed_fields if changed_fields else None,
    )

    # Fetch and return updated memory
    cursor = await db.execute(
        "SELECT * FROM memories WHERE id = ?",
        (id,),
    )
    row = await cursor.fetchone()

    return MemoryResponse(
        id=row["id"],
        owner_user_id=row["owner_user_id"],
        content=row["content"],
        media_type=row["media_type"],
        media_file_id=row["media_file_id"],
        media_local_path=row["media_local_path"],
        status=row["status"],
        pending_expires_at=datetime.fromisoformat(row["pending_expires_at"].replace('Z', '+00:00')) if row["pending_expires_at"] else None,
        is_pinned=bool(row["is_pinned"]),
        created_at=datetime.fromisoformat(row["created_at"].replace('Z', '+00:00')),
        updated_at=datetime.fromisoformat(row["updated_at"].replace('Z', '+00:00')),
    )


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_memory(
    id: str,
    db: aiosqlite.Connection = Depends(get_db),
) -> None:
    """
    Delete a memory by ID.

    - Fetch existing memory; 404 if not found
    - Call remove_from_index() to remove from FTS5
    - If media_local_path exists and file is on disk: delete the file
    - Delete from memories (cascade will delete memory_tags)
    - Call log_audit() to log the deletion
    """
    # Fetch existing memory
    cursor = await db.execute(
        "SELECT * FROM memories WHERE id = ?",
        (id,),
    )
    row = await cursor.fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail="Memory not found")

    owner_user_id = row["owner_user_id"]
    media_local_path = row["media_local_path"]

    # Remove from FTS5
    await remove_from_index(db, id)

    # Delete file if it exists
    if media_local_path and os.path.exists(media_local_path):
        try:
            os.remove(media_local_path)
        except OSError as e:
            # Log error but continue with database deletion
            print(f"Warning: Failed to delete file {media_local_path}: {e}")

    # Delete from database (cascade will delete memory_tags)
    await db.execute("DELETE FROM memories WHERE id = ?", (id,))
    await db.commit()

    # Log audit
    await log_audit(db, "memory", id, "deleted", f"user:{owner_user_id}")


@router.post("/{id}/tags", response_model=MemoryWithTags)
async def add_tags_to_memory(
    id: str,
    tags_request: TagsAddRequest,
    db: aiosqlite.Connection = Depends(get_db),
) -> MemoryWithTags:
    """
    Add tags to a memory.

    - Accept: TagsAddRequest body (tags: list[str], status: str = "confirmed")
    - Fetch memory; 404 if not found
    - For each tag: INSERT OR REPLACE INTO memory_tags
    - If memory is confirmed: call index_memory() to re-sync FTS5 with new tags
    - Call log_audit() to log the update
    """
    # Fetch memory
    cursor = await db.execute(
        "SELECT * FROM memories WHERE id = ?",
        (id,),
    )
    row = await cursor.fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail="Memory not found")

    owner_user_id = row["owner_user_id"]
    memory_status = row["status"]

    # Insert or replace tags
    for tag in tags_request.tags:
        if tags_request.status == "suggested":
            suggested_at = datetime.utcnow().isoformat() + 'Z'
            confirmed_at = None
        else:  # confirmed
            suggested_at = None
            confirmed_at = datetime.utcnow().isoformat() + 'Z'

        await db.execute(
            """
            INSERT OR REPLACE INTO memory_tags (memory_id, tag, status, suggested_at, confirmed_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (id, tag, tags_request.status, suggested_at, confirmed_at),
        )

    await db.commit()

    # If memory is confirmed, re-sync FTS5
    if memory_status == "confirmed":
        await index_memory(db, id)

    # Log audit
    await log_audit(
        db,
        "memory",
        id,
        "updated",
        f"user:{owner_user_id}",
        detail={"tags_added": tags_request.tags},
    )

    # Fetch and return updated memory with tags
    return await get_memory(id, db)


@router.delete("/{id}/tags/{tag}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_tag_from_memory(
    id: str,
    tag: str,
    db: aiosqlite.Connection = Depends(get_db),
) -> None:
    """
    Remove a tag from a memory.

    - Fetch memory; 404 if not found
    - Delete from memory_tags WHERE memory_id = ? AND tag = ?
    - If memory is confirmed: call index_memory() to re-sync FTS5
    - Call log_audit() to log the update
    """
    # Fetch memory
    cursor = await db.execute(
        "SELECT * FROM memories WHERE id = ?",
        (id,),
    )
    row = await cursor.fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail="Memory not found")

    owner_user_id = row["owner_user_id"]
    memory_status = row["status"]

    # Delete tag
    await db.execute(
        "DELETE FROM memory_tags WHERE memory_id = ? AND tag = ?",
        (id, tag),
    )
    await db.commit()

    # If memory is confirmed, re-sync FTS5
    if memory_status == "confirmed":
        await index_memory(db, id)

    # Log audit
    await log_audit(
        db,
        "memory",
        id,
        "updated",
        f"user:{owner_user_id}",
        detail={"tag_removed": tag},
    )
