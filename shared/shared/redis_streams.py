"""Redis Streams helpers for BearMemori.

This module provides constants and async helper functions for working with
Redis Streams across different services in the BearMemori application.
"""

import json
from typing import Any
import redis.exceptions


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
        await redis_client.xgroup_create(
            stream_name, group_name, id="0", mkstream=True
        )
    except redis.exceptions.ResponseError as e:
        # Ignore if group already exists
        if "BUSYGROUP" not in str(e):
            raise


async def consume(
    redis_client,
    stream_name: str,
    group_name: str,
    consumer_name: str,
    count: int = 1,
    block_ms: int = 5000,
) -> list[tuple[str, dict[str, Any]]]:
    """Consume messages from a Redis stream using a consumer group.

    Args:
        redis_client: Async Redis client instance
        stream_name: Name of the stream to consume from
        group_name: Name of the consumer group
        consumer_name: Name of this consumer instance
        count: Maximum number of messages to retrieve (default: 1)
        block_ms: Time to block waiting for messages in milliseconds (default: 5000)

    Returns:
        List of (message_id, data_dict) tuples. Empty list if no messages available.
    """
    result = await redis_client.xreadgroup(
        group_name, consumer_name, {stream_name: ">"}, count=count, block=block_ms
    )

    messages = []
    if result:
        for stream, stream_messages in result:
            for message_id, fields in stream_messages:
                # Decode message_id if it's bytes
                msg_id = message_id.decode() if isinstance(message_id, bytes) else message_id

                # Get the 'data' field and deserialize JSON
                data_field = fields.get(b"data") if b"data" in fields else fields.get("data")
                if data_field:
                    json_str = data_field.decode() if isinstance(data_field, bytes) else data_field
                    try:
                        data = json.loads(json_str)
                        messages.append((msg_id, data))
                    except json.JSONDecodeError:
                        # Handle invalid JSON - skip or log
                        pass

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
