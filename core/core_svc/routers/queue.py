"""Queue and conversation routers for message processing."""

import json
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request, status

from shared_lib.redis_streams import (
    CONVERSATION_KEY_PREFIX,
    CONVERSATION_TTL_SECONDS,
    QUEUE_KEY_PREFIX,
    QUEUE_TTL_SECONDS,
)
from shared_lib.schemas import (
    CancelResponse,
    ConversationReply,
    ConversationResponse,
    ConversationStart,
    ConversationStateUpdate,
    DequeueResponse,
    QueueItem,
    QueueItemCreate,
    QueueStatus,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["queue"])
conversations_router = APIRouter(tags=["conversations"])

TERMINAL_STATES = {"completed", "cancelled"}
SHORT_TTL_SECONDS = 60


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _queue_key(user_id: int) -> str:
    return f"{QUEUE_KEY_PREFIX}{user_id}"


def _conv_key(user_id: int) -> str:
    return f"{CONVERSATION_KEY_PREFIX}{user_id}"


async def _pop_next_item(
    redis, user_id: int
) -> QueueItem | None:
    """LPOP the next queue item and return it, or None."""
    raw = await redis.lpop(_queue_key(user_id))
    if raw is None:
        return None
    return QueueItem(**json.loads(raw))


def _conv_hash_to_response(
    data: dict[bytes | str, bytes | str],
    user_id: int,
) -> ConversationResponse:
    """Convert a Redis HGETALL result dict to ConversationResponse."""
    def _s(v: bytes | str) -> str:
        return v.decode() if isinstance(v, bytes) else v

    return ConversationResponse(
        id=_s(data[b"id"] if b"id" in data else data["id"]),
        user_id=user_id,
        queue_item_id=_s(
            data[b"queue_item_id"]
            if b"queue_item_id" in data
            else data["queue_item_id"]
        ),
        state=_s(
            data[b"state"] if b"state" in data else data["state"]
        ),
        history=json.loads(
            _s(
                data[b"history"]
                if b"history" in data
                else data["history"]
            )
        ),
        created_at=_s(
            data[b"created_at"]
            if b"created_at" in data
            else data["created_at"]
        ),
        updated_at=_s(
            data[b"updated_at"]
            if b"updated_at" in data
            else data["updated_at"]
        ),
    )


# ---------------------------------------------------------------------------
# Queue endpoints
# ---------------------------------------------------------------------------

@router.post("/{user_id}/enqueue", status_code=status.HTTP_201_CREATED)
async def enqueue(
    user_id: int,
    body: QueueItemCreate,
    request: Request,
) -> QueueItem:
    """Add a message to the user's queue."""
    redis = request.app.state.redis
    now = datetime.now(timezone.utc).isoformat()
    item = QueueItem(
        id=str(uuid.uuid4()),
        content=body.content,
        memory_id=body.memory_id,
        image_local_path=body.image_local_path,
        message_timestamp=body.message_timestamp,
        created_at=now,
    )
    key = _queue_key(user_id)
    await redis.rpush(key, item.model_dump_json())
    await redis.expire(key, QUEUE_TTL_SECONDS)
    logger.debug("Enqueued item %s for user %s", item.id, user_id)
    return item


@router.delete("/{user_id}/dequeue")
async def dequeue(
    user_id: int,
    request: Request,
) -> DequeueResponse:
    """Pop the next item from the user's queue."""
    redis = request.app.state.redis
    item = await _pop_next_item(redis, user_id)
    return DequeueResponse(item=item)


@router.get("/{user_id}/next")
async def peek(
    user_id: int,
    request: Request,
) -> QueueItem | None:
    """Peek at the next item without removing it."""
    redis = request.app.state.redis
    result = await redis.lrange(_queue_key(user_id), 0, 0)
    if not result:
        return None
    return QueueItem(**json.loads(result[0]))


@router.get("/{user_id}/status")
async def queue_status(
    user_id: int,
    request: Request,
) -> QueueStatus:
    """Get queue length and conversation state."""
    redis = request.app.state.redis
    length = await redis.llen(_queue_key(user_id))
    conv_key = _conv_key(user_id)
    state_raw = await redis.hget(conv_key, "state")
    conv_state: str | None = None
    if state_raw is not None:
        conv_state = (
            state_raw.decode()
            if isinstance(state_raw, bytes)
            else state_raw
        )
    conv_active = conv_state is not None and conv_state not in TERMINAL_STATES
    return QueueStatus(
        queue_length=length,
        conversation_active=conv_active,
        conversation_state=conv_state,
    )


# ---------------------------------------------------------------------------
# Conversation endpoints
# ---------------------------------------------------------------------------

@conversations_router.post("/{user_id}/start")
async def start_conversation(
    user_id: int,
    body: ConversationStart,
    request: Request,
) -> ConversationResponse:
    """Start a new conversation for a queued item."""
    redis = request.app.state.redis
    conv_key = _conv_key(user_id)

    # Check for existing active conversation
    existing = await redis.hgetall(conv_key)
    if existing:
        existing_state = existing.get("state", "")
        if isinstance(existing_state, bytes):
            existing_state = existing_state.decode()
        if existing_state in ("processing", "awaiting_reply"):
            raise HTTPException(
                status_code=409,
                detail="An active conversation already exists",
            )

    now = datetime.now(timezone.utc).isoformat()
    conv_id = str(uuid.uuid4())
    mapping = {
        "id": conv_id,
        "queue_item_id": body.queue_item_id,
        "state": "processing",
        "history": json.dumps([]),
        "created_at": now,
        "updated_at": now,
    }
    await redis.hset(conv_key, mapping=mapping)
    await redis.expire(conv_key, CONVERSATION_TTL_SECONDS)
    logger.debug(
        "Started conversation %s for user %s", conv_id, user_id
    )
    return ConversationResponse(
        id=conv_id,
        user_id=user_id,
        queue_item_id=body.queue_item_id,
        state="processing",
        history=[],
        created_at=now,
        updated_at=now,
    )


@conversations_router.get("/{user_id}/active")
async def get_active_conversation(
    user_id: int,
    request: Request,
) -> ConversationResponse | None:
    """Get the active conversation, if any."""
    redis = request.app.state.redis
    data = await redis.hgetall(_conv_key(user_id))
    if not data:
        return None
    resp = _conv_hash_to_response(data, user_id)
    if resp.state in TERMINAL_STATES:
        return None
    return resp


@conversations_router.patch("/{user_id}/state")
async def update_state(
    user_id: int,
    body: ConversationStateUpdate,
    request: Request,
) -> ConversationResponse:
    """Update the conversation state."""
    redis = request.app.state.redis
    conv_key = _conv_key(user_id)
    data = await redis.hgetall(conv_key)
    if not data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active conversation",
        )
    now = datetime.now(timezone.utc).isoformat()
    # Update state
    await redis.hset(conv_key, "state", body.state)
    await redis.hset(conv_key, "updated_at", now)
    # Append history entry if provided
    if body.history_entry is not None:
        hist_raw = await redis.hget(conv_key, "history")
        history = json.loads(
            hist_raw.decode()
            if isinstance(hist_raw, bytes)
            else hist_raw
        )
        history.append(body.history_entry)
        await redis.hset(conv_key, "history", json.dumps(history))
    # Set short TTL for terminal states
    if body.state in TERMINAL_STATES:
        await redis.expire(conv_key, SHORT_TTL_SECONDS)
    # Return updated conversation
    updated = await redis.hgetall(conv_key)
    return _conv_hash_to_response(updated, user_id)


@conversations_router.post("/{user_id}/reply")
async def reply_to_conversation(
    user_id: int,
    body: ConversationReply,
    request: Request,
) -> ConversationResponse:
    """Reply to a conversation that is awaiting input."""
    redis = request.app.state.redis
    conv_key = _conv_key(user_id)
    data = await redis.hgetall(conv_key)
    if not data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active conversation",
        )
    resp = _conv_hash_to_response(data, user_id)
    if resp.state != "awaiting_reply":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Conversation is in '{resp.state}' state, "
                "not 'awaiting_reply'"
            ),
        )
    now = datetime.now(timezone.utc).isoformat()
    # Append user reply to history
    hist_raw = await redis.hget(conv_key, "history")
    history = json.loads(
        hist_raw.decode()
        if isinstance(hist_raw, bytes)
        else hist_raw
    )
    history.append({"role": "user", "content": body.content})
    await redis.hset(conv_key, "history", json.dumps(history))
    await redis.hset(conv_key, "state", "processing")
    await redis.hset(conv_key, "updated_at", now)
    updated = await redis.hgetall(conv_key)
    return _conv_hash_to_response(updated, user_id)


@conversations_router.post("/{user_id}/cancel")
async def cancel_conversation(
    user_id: int,
    request: Request,
) -> CancelResponse:
    """Cancel the active conversation and pop the next queue item."""
    redis = request.app.state.redis
    conv_key = _conv_key(user_id)
    data = await redis.hgetall(conv_key)
    if not data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active conversation",
        )
    now = datetime.now(timezone.utc).isoformat()
    await redis.hset(conv_key, "state", "cancelled")
    await redis.hset(conv_key, "updated_at", now)
    await redis.expire(conv_key, SHORT_TTL_SECONDS)
    next_item = await _pop_next_item(redis, user_id)
    return CancelResponse(state="cancelled", next_item=next_item)
