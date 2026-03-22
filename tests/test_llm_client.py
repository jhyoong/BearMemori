import json
from unittest.mock import AsyncMock, patch

import pytest

from bearmemori.llm.client import LLMClient


@pytest.fixture
def client():
    return LLMClient(base_url="http://localhost:11434/v1", model="llama3", api_key="not-needed")


@pytest.mark.asyncio
async def test_classify_input_returns_store(client):
    mock_response = AsyncMock()
    mock_response.choices = [
        AsyncMock(
            message=AsyncMock(
                content=json.dumps(
                    {
                        "action": "store",
                        "category": "profile",
                        "confidence": 0.9,
                    }
                )
            )
        )
    ]

    with patch.object(client._client.chat.completions, "create", return_value=mock_response):
        result = await client.classify_input("I prefer dark mode")

    assert result.action == "store"
    assert result.category == "profile"


@pytest.mark.asyncio
async def test_classify_input_returns_followup(client):
    mock_response = AsyncMock()
    mock_response.choices = [
        AsyncMock(
            message=AsyncMock(
                content=json.dumps(
                    {
                        "action": "followup",
                        "question": "What kind of dark mode?",
                    }
                )
            )
        )
    ]

    with patch.object(client._client.chat.completions, "create", return_value=mock_response):
        result = await client.classify_input("I changed something")

    assert result.action == "followup"
    assert result.question == "What kind of dark mode?"


@pytest.mark.asyncio
async def test_extract_memory(client):
    mock_response = AsyncMock()
    mock_response.choices = [
        AsyncMock(
            message=AsyncMock(
                content=json.dumps(
                    {
                        "content": "User prefers dark mode in all applications",
                        "category": "profile",
                        "title": "Dark mode preference",
                        "tags": ["ui", "dark-mode", "preference"],
                        "event_fields": None,
                    }
                )
            )
        )
    ]

    with patch.object(client._client.chat.completions, "create", return_value=mock_response):
        result = await client.extract_memory("I prefer dark mode", context=None)

    assert result.content == "User prefers dark mode in all applications"
    assert result.category == "profile"
    assert result.title == "Dark mode preference"
    assert "dark-mode" in result.tags


@pytest.mark.asyncio
async def test_generate_followup(client):
    mock_response = AsyncMock()
    mock_response.choices = [
        AsyncMock(message=AsyncMock(content="Could you tell me more about what changed?"))
    ]

    with patch.object(client._client.chat.completions, "create", return_value=mock_response):
        result = await client.generate_followup("something changed", context=None)

    assert "changed" in result


@pytest.mark.asyncio
async def test_classify_reminder(client):
    mock_response = AsyncMock()
    mock_response.choices = [
        AsyncMock(
            message=AsyncMock(
                content=json.dumps(
                    {
                        "action": "store",
                        "category": "reminder",
                        "confidence": 0.95,
                    }
                )
            )
        )
    ]

    with patch.object(client._client.chat.completions, "create", return_value=mock_response):
        result = await client.classify_input("remind me to take meds at 8pm")

    assert result.action == "store"
    assert result.category == "reminder"


@pytest.mark.asyncio
async def test_extract_reminder(client):
    mock_response = AsyncMock()
    mock_response.choices = [
        AsyncMock(
            message=AsyncMock(
                content=json.dumps(
                    {
                        "content": "Take meds",
                        "category": "reminder",
                        "title": "Take meds at 8pm",
                        "tags": ["health"],
                        "event_fields": {
                            "datetime": "2026-03-21T20:00:00",
                            "status": "pending",
                            "recurrence": None,
                        },
                    }
                )
            )
        )
    ]

    with patch.object(client._client.chat.completions, "create", return_value=mock_response):
        result = await client.extract_memory("remind me to take meds at 8pm", None)

    assert result.category == "reminder"
    assert result.event_fields["datetime"] == "2026-03-21T20:00:00"
    assert result.event_fields["recurrence"] is None


@pytest.mark.asyncio
async def test_extract_recurring_reminder(client):
    mock_response = AsyncMock()
    mock_response.choices = [
        AsyncMock(
            message=AsyncMock(
                content=json.dumps(
                    {
                        "content": "Take meds every 8 hours",
                        "category": "reminder",
                        "title": "Take meds every 8 hours",
                        "tags": ["health"],
                        "event_fields": {
                            "datetime": "2026-03-21T20:00:00",
                            "status": "pending",
                            "recurrence": "every 8 hours",
                        },
                    }
                )
            )
        )
    ]

    with patch.object(client._client.chat.completions, "create", return_value=mock_response):
        result = await client.extract_memory("remind me every 8 hours to take meds", None)

    assert result.category == "reminder"
    assert result.event_fields["recurrence"] == "every 8 hours"


@pytest.mark.asyncio
async def test_describe_image(client):
    mock_response = AsyncMock()
    mock_response.choices = [
        AsyncMock(
            message=AsyncMock(
                content=json.dumps(
                    {
                        "content": "A sunset over the ocean",
                        "category": "general",
                        "title": "Ocean sunset",
                        "tags": ["photo", "nature"],
                        "event_fields": None,
                    }
                )
            )
        )
    ]

    with patch.object(
        client._client.chat.completions, "create", return_value=mock_response
    ) as mock_create:
        result = await client.describe_image(b"fake-image-bytes")

    assert result.title == "Ocean sunset"
    assert result.content == "A sunset over the ocean"
    assert result.category == "general"

    # Verify vision message format was used
    call_args = mock_create.call_args
    messages = call_args.kwargs["messages"]
    assert len(messages) == 2
    assert messages[1]["role"] == "user"
    assert isinstance(messages[1]["content"], list)
    assert messages[1]["content"][0]["type"] == "image_url"
