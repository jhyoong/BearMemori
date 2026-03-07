"""Tests for shared_lib/redis_streams.py consume() and consume_multi() functions.

These tests verify that the consume() and consume_multi() functions properly
handle messages that lack the expected "data" field (currently broken - silently skipped).
"""

import pytest
import pytest_asyncio
import fakeredis.aioredis

from shared_lib.redis_streams import (
    consume,
    consume_multi,
    create_consumer_group,
    publish,
)


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
    _msg_id = await redis_client.xadd(stream_name, {"other_field": "value"})

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


# Tests for consume_multi()


@pytest_asyncio.fixture
async def multi_stream_setup(redis_client):
    """Setup multiple streams with consumer group for testing."""
    stream1 = "test:stream:1"
    stream2 = "test:stream:2"
    group_name = "test-group-multi"
    consumer_name = "test-consumer-multi"

    # Create consumer group for both streams
    await create_consumer_group(redis_client, stream1, group_name)
    await create_consumer_group(redis_client, stream2, group_name)

    return {
        "redis_client": redis_client,
        "streams": {stream1: ">", stream2: ">"},
        "group_name": group_name,
        "consumer_name": consumer_name,
    }


@pytest.mark.asyncio
async def test_consume_multi_returns_empty_when_no_messages(multi_stream_setup):
    """Test that consume_multi() returns empty list when no messages are available."""
    redis_client = multi_stream_setup["redis_client"]
    streams = multi_stream_setup["streams"]
    group_name = multi_stream_setup["group_name"]
    consumer_name = multi_stream_setup["consumer_name"]

    # Consume from empty streams
    messages = await consume_multi(redis_client, streams, group_name, consumer_name)

    assert messages == []


@pytest.mark.asyncio
async def test_consume_multi_single_stream_with_message(multi_stream_setup):
    """Test that consume_multi() reads a message from a single stream."""
    redis_client = multi_stream_setup["redis_client"]

    # Publish a message to one stream
    await publish(redis_client, "test:stream:1", {"key": "value"})

    # Consume from both streams
    messages = await consume_multi(
        redis_client,
        {"test:stream:1": ">", "test:stream:2": ">"},  # stream:2 has no messages
        "test-group-multi",
        "test-consumer-multi",
    )

    # Should get 1 message from stream:1
    assert len(messages) == 1
    assert messages[0][0] == "test:stream:1"  # stream_name
    assert messages[0][2] == {"key": "value"}  # data


@pytest.mark.asyncio
async def test_consume_multi_with_data_field_none(multi_stream_setup):
    """Test that consume_multi() handles messages without 'data' field."""
    redis_client = multi_stream_setup["redis_client"]

    # Add a message without "data" field directly
    _msg_id = await redis_client.xadd("test:stream:1", {"other_field": "value"})

    # Consume from both streams
    messages = await consume_multi(
        redis_client,
        {"test:stream:1": ">", "test:stream:2": ">"},  # stream:2 has no messages
        "test-group-multi",
        "test-consumer-multi",
    )

    # Should get 1 message with None data (not silently dropped)
    assert len(messages) == 1
    assert messages[0][0] == "test:stream:1"  # stream_name
    assert messages[0][2] is None  # data is None when field is missing
