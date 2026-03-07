"""Redis Streams helpers for BearMemori.

This module provides constants and async helper functions for working with
Redis Streams across different services in the BearMemori application.
"""

import json
import logging
from typing import Any
import redis.exceptions

logger = logging.getLogger(__name__)


# Stream name constants
STREAM_LLM_IMAGE_TAG = "llm:image_tag"
STREAM_LLM_INTENT = "llm:intent"
STREAM_LLM_FOLLOWUP = "llm:followup"
STREAM_LLM_TASK_MATCH = "llm:task_match"
STREAM_LLM_EMAIL_EXTRACT = "llm:email_extract"
STREAM_NOTIFY_TELEGRAM = "notify:telegram"

# Consumer group constants
GROUP_LLM_WORKER = "llm-worker-group"
GROUP_TELEGRAM = "telegram-group"

# Queue and conversation Redis key patterns
QUEUE_KEY_PREFIX = "queue:"          # queue:{user_id} — Redis list
CONVERSATION_KEY_PREFIX = "conversation:"  # conversation:{user_id} — Redis hash
QUEUE_TTL_SECONDS = 7 * 24 * 3600   # 7 days
CONVERSATION_TTL_SECONDS = 24 * 3600  # 24 hours


async def publish(redis_client, stream_name: str, data: dict[str, Any]) -> str:
    """Publish a message to a Redis stream.

    Args:
        redis_client: Async Redis client instance
        stream_name: Name of the stream to publish to
        data: Dictionary to publish (will be JSON-serialized)

    Returns:
        Message ID returned by Redis (e.g., "1234567890-0")
    """
    json_data = json.dumps(data)
    message_id = await redis_client.xadd(stream_name, {"data": json_data})
    return message_id.decode() if isinstance(message_id, bytes) else message_id


async def create_consumer_group(
    redis_client, stream_name: str, group_name: str
) -> None:
    """Create a consumer group for a Redis stream.

    Creates a consumer group starting from the beginning of the stream (id="0").
    If the stream doesn't exist, it will be created (mkstream=True).
    If the group already exists, the BUSYGROUP error is silently ignored.

    Args:
        redis_client: Async Redis client instance
        stream_name: Name of the stream
        group_name: Name of the consumer group to create
    """
    try:
        await redis_client.xgroup_create(stream_name, group_name, id="0", mkstream=True)
    except redis.exceptions.ResponseError as e:
        # Ignore if group already exists
        if "BUSYGROUP" not in str(e):
            raise


async def consume(
    redis_client,
    stream_name: str,
    group_name: str,
    consumer_name: str,
    id: str = ">",
    count: int = 10,
    block_ms: int = 5000,
) -> list[tuple[str, dict[str, Any]]]:
    """Consume messages from a Redis stream using a consumer group.

    Args:
        redis_client: Async Redis client instance
        stream_name: Name of the stream to consume from
        group_name: Name of the consumer group
        consumer_name: Name of this consumer instance
        id: Message ID to start from (">" for new messages, "0" for pending)
        count: Maximum number of messages to retrieve (default: 10)
        block_ms: Time to block waiting for messages in milliseconds (default: 5000)

    Returns:
        List of (message_id, data_dict) tuples. Empty list if no messages available.
    """
    result = await redis_client.xreadgroup(
        group_name, consumer_name, {stream_name: id}, count=count, block=block_ms
    )

    messages = []
    if result:
        for stream, stream_messages in result:
            for message_id, fields in stream_messages:
                # Decode message_id if it's bytes
                msg_id = (
                    message_id.decode() if isinstance(message_id, bytes) else message_id
                )

                # Get the 'data' field and deserialize JSON
                data_field = (
                    fields.get(b"data") if b"data" in fields else fields.get("data")
                )
                if data_field:
                    json_str = (
                        data_field.decode()
                        if isinstance(data_field, bytes)
                        else data_field
                    )
                    try:
                        data = json.loads(json_str)
                        messages.append((msg_id, data))
                    except json.JSONDecodeError:
                        # Handle invalid JSON - skip or log
                        logger.debug(f"Message {msg_id} has invalid JSON in data field")
                        pass
                else:
                    # Message lacks "data" field - return with None data
                    # This prevents messages from being blocked in the PEL
                    logger.debug(
                        f"Message {msg_id} missing 'data' field, returning None"
                    )
                    messages.append((msg_id, None))

    return messages


async def consume_multi(
    redis_client,
    streams: dict[str, str],
    group_name: str,
    consumer_name: str,
    count: int = 10,
    block_ms: int = 5000,
) -> list[tuple[str, str, dict[str, Any] | None]]:
    """Consume messages from multiple Redis streams in a single xreadgroup call.

    Args:
        redis_client: Async Redis client instance
        streams: Dict mapping stream_name -> last_id (">" for new, "0" for PEL)
        group_name: Name of the consumer group
        consumer_name: Name of this consumer instance
        count: Maximum number of messages to retrieve per stream
        block_ms: Time to block waiting for messages in milliseconds

    Returns:
        List of (stream_name, message_id, data_dict) tuples.
    """
    result = await redis_client.xreadgroup(
        group_name, consumer_name, streams, count=count, block=block_ms
    )

    messages = []
    if result:
        for stream, stream_messages in result:
            s_name = stream.decode() if isinstance(stream, bytes) else stream
            for message_id, fields in stream_messages:
                msg_id = (
                    message_id.decode()
                    if isinstance(message_id, bytes)
                    else message_id
                )
                data_field = (
                    fields.get(b"data")
                    if b"data" in fields
                    else fields.get("data")
                )
                if data_field:
                    json_str = (
                        data_field.decode()
                        if isinstance(data_field, bytes)
                        else data_field
                    )
                    try:
                        data = json.loads(json_str)
                        messages.append((s_name, msg_id, data))
                    except json.JSONDecodeError:
                        logger.debug(
                            "Message %s has invalid JSON in data field", msg_id
                        )
                else:
                    logger.debug(
                        "Message %s missing 'data' field, returning None", msg_id
                    )
                    messages.append((s_name, msg_id, None))

    return messages


async def ack(redis_client, stream_name: str, group_name: str, message_id: str) -> None:
    """Acknowledge a message in a Redis stream consumer group.

    Args:
        redis_client: Async Redis client instance
        stream_name: Name of the stream
        group_name: Name of the consumer group
        message_id: ID of the message to acknowledge
    """
    await redis_client.xack(stream_name, group_name, message_id)




