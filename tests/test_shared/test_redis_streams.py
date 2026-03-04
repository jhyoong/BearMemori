"""Tests for shared_lib/redis_streams.py consume() function.

These tests verify that the consume() function properly handles messages
that lack the expected "data" field (currently broken - silently skipped).
"""

import pytest
import pytest_asyncio
import fakeredis.aioredis

from shared_lib.redis_streams import consume, create_consumer_group, publish


@pytest_asyncio.fixture
async def redis_client():
    """Create a fake Redis client for testing."""
    client = fakeredis.aioredis.FakeRedis()
    yield client
    await client.aclose()


@pytest_asyncio.fixture
async def stream_setup(redis_client):
    """Setup a stream with consumer group for testing."""
    stream_name = "test:stream"
    group_name = "test-group"
    consumer_name = "test-consumer"

    # Create consumer group
    await create_consumer_group(redis_client, stream_name, group_name)

    return {
        "stream_name": stream_name,
        "group_name": group_name,
        "consumer_name": consumer_name,
    }


@pytest.mark.asyncio
async def test_consume_message_without_data_field_returns_none(
    redis_client, stream_setup
):
    """Test that consume() returns message with None data when 'data' field is missing.

    This is the main bug being fixed: currently messages without "data" field
    are silently dropped, causing them to block subsequent messages in the PEL.
    """
    stream_name = stream_setup["stream_name"]
    group_name = stream_setup["group_name"]
    consumer_name = stream_setup["consumer_name"]

    # Add a message without "data" field (flat format)
    # Using XADD directly to avoid the publish() which always adds "data"
    msg_id = await redis_client.xadd(stream_name, {"other_field": "value"})

    # Consume messages
    messages = await consume(redis_client, stream_name, group_name, consumer_name)

    # The message without "data" field should be returned with None data
    # (not silently dropped as currently happens)
    assert len(messages) == 1, (
        "Message without 'data' field should not be silently dropped"
    )

    msg_id_result, data = messages[0]
    assert data is None, "Data should be None when 'data' field is missing"


@pytest.mark.asyncio
async def test_consume_message_with_valid_json_returns_parsed_data(
    redis_client, stream_setup
):
    """Test that consume() returns parsed JSON data for valid JSON in 'data' field."""
    stream_name = stream_setup["stream_name"]
    group_name = stream_setup["group_name"]
    consumer_name = stream_setup["consumer_name"]

    # Publish a message with valid JSON data
    test_data = {"key": "value", "number": 42}
    await publish(redis_client, stream_name, test_data)

    # Consume messages
    messages = await consume(redis_client, stream_name, group_name, consumer_name)

    # Should return parsed JSON
    assert len(messages) == 1
    msg_id_result, data = messages[0]
    assert data == test_data
    assert data["key"] == "value"
    assert data["number"] == 42


@pytest.mark.asyncio
async def test_consume_message_with_invalid_json_is_skipped(redis_client, stream_setup):
    """Test that consume() skips messages with invalid JSON in 'data' field."""
    stream_name = stream_setup["stream_name"]
    group_name = stream_setup["group_name"]
    consumer_name = stream_setup["consumer_name"]

    # Add a message with invalid JSON directly to avoid validation
    await redis_client.xadd(stream_name, {"data": "not valid json {"})

    # Consume messages
    messages = await consume(redis_client, stream_name, group_name, consumer_name)

    # Invalid JSON should be skipped (current behavior - OK)
    assert len(messages) == 0


@pytest.mark.asyncio
async def test_consume_mixed_messages(redis_client, stream_setup):
    """Test consume() with both valid and missing data field messages."""
    stream_name = stream_setup["stream_name"]
    group_name = stream_setup["group_name"]
    consumer_name = stream_setup["consumer_name"]

    # Add multiple messages with different formats
    await redis_client.xadd(stream_name, {"data": '{"valid": true}'})
    await redis_client.xadd(stream_name, {"other_field": "no data field"})
    await redis_client.xadd(stream_name, {"data": '{"another": "valid"}'})

    # Consume messages
    messages = await consume(redis_client, stream_name, group_name, consumer_name)

    # Should get 3 messages: 2 valid + 1 with None data
    assert len(messages) == 3

    # Check that we have both parsed data and None data
    data_values = [msg[1] for msg in messages]
    assert {"valid": True} in data_values
    assert {"another": "valid"} in data_values
    assert None in data_values


@pytest.mark.asyncio
async def test_consume_empty_stream(redis_client, stream_setup):
    """Test that consume() returns empty list when no messages are available."""
    stream_name = stream_setup["stream_name"]
    group_name = stream_setup["group_name"]
    consumer_name = stream_setup["consumer_name"]

    # Consume from empty stream
    messages = await consume(redis_client, stream_name, group_name, consumer_name)

    assert messages == []
