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
        AsyncMock(message=AsyncMock(content=json.dumps({
            "action": "store",
            "memory_type": "preference",
            "confidence": 0.9,
        })))
    ]

    with patch.object(client._client.chat.completions, "create", return_value=mock_response):
        result = await client.classify_input("I prefer dark mode")

    assert result.action == "store"
    assert result.memory_type == "preference"


@pytest.mark.asyncio
async def test_classify_input_returns_followup(client):
    mock_response = AsyncMock()
    mock_response.choices = [
        AsyncMock(message=AsyncMock(content=json.dumps({
            "action": "followup",
            "question": "What kind of dark mode?",
        })))
    ]

    with patch.object(client._client.chat.completions, "create", return_value=mock_response):
        result = await client.classify_input("I changed something")

    assert result.action == "followup"
    assert result.question == "What kind of dark mode?"


@pytest.mark.asyncio
async def test_extract_memory(client):
    mock_response = AsyncMock()
    mock_response.choices = [
        AsyncMock(message=AsyncMock(content=json.dumps({
            "content": "User prefers dark mode in all applications",
            "memory_type": "preference",
            "tags": ["ui", "dark-mode", "preference"],
        })))
    ]

    with patch.object(client._client.chat.completions, "create", return_value=mock_response):
        result = await client.extract_memory("I prefer dark mode", context=None)

    assert result.content == "User prefers dark mode in all applications"
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
        AsyncMock(message=AsyncMock(content=json.dumps({
            "action": "store",
            "memory_type": "reminder",
            "confidence": 0.95,
        })))
    ]

    with patch.object(client._client.chat.completions, "create", return_value=mock_response):
        result = await client.classify_input("remind me to take meds at 8pm")

    assert result.action == "store"
    assert result.memory_type == "reminder"


@pytest.mark.asyncio
async def test_extract_reminder(client):
    mock_response = AsyncMock()
    mock_response.choices = [
        AsyncMock(message=AsyncMock(content=json.dumps({
            "content": "Take meds",
            "memory_type": "reminder",
            "tags": ["health"],
            "remind_at": "2026-03-21T20:00:00",
            "recurring_minutes": None,
        })))
    ]

    with patch.object(client._client.chat.completions, "create", return_value=mock_response):
        result = await client.extract_memory("remind me to take meds at 8pm", None)

    assert result.memory_type == "reminder"
    assert result.remind_at == "2026-03-21T20:00:00"
    assert result.recurring_minutes is None


@pytest.mark.asyncio
async def test_extract_recurring_reminder(client):
    mock_response = AsyncMock()
    mock_response.choices = [
        AsyncMock(message=AsyncMock(content=json.dumps({
            "content": "Take meds",
            "memory_type": "reminder",
            "tags": ["health"],
            "remind_at": "2026-03-21T20:00:00",
            "recurring_minutes": 480,
        })))
    ]

    with patch.object(client._client.chat.completions, "create", return_value=mock_response):
        result = await client.extract_memory("remind me every 8 hours to take meds", None)

    assert result.recurring_minutes == 480
