import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from bearmemori.llm.client import CLASSIFY_SYSTEM_PROMPT, LLMClient


@pytest.fixture
def mock_openai_client():
    client = MagicMock()
    client.chat.completions.create = AsyncMock()
    return client


@pytest.fixture
def client(mock_openai_client):
    return LLMClient(
        base_url="http://localhost:11434/v1",
        model="llama3",
        _client=mock_openai_client,
    )


@pytest.mark.asyncio
async def test_classify_input_returns_store(client, mock_openai_client):
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

    mock_openai_client.chat.completions.create.return_value = mock_response
    result = await client.classify_input("I prefer dark mode")

    assert result.action == "store"
    assert result.category == "profile"


@pytest.mark.asyncio
async def test_classify_input_returns_followup(client, mock_openai_client):
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

    mock_openai_client.chat.completions.create.return_value = mock_response
    result = await client.classify_input("I changed something")

    assert result.action == "followup"
    assert result.question == "What kind of dark mode?"


@pytest.mark.asyncio
async def test_extract_memory(client, mock_openai_client):
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

    mock_openai_client.chat.completions.create.return_value = mock_response
    result = await client.extract_memory("I prefer dark mode", context=None)

    assert result.content == "User prefers dark mode in all applications"
    assert result.category == "profile"
    assert result.title == "Dark mode preference"
    assert "dark-mode" in result.tags


@pytest.mark.asyncio
async def test_generate_followup(client, mock_openai_client):
    mock_response = AsyncMock()
    mock_response.choices = [
        AsyncMock(message=AsyncMock(content="Could you tell me more about what changed?"))
    ]

    mock_openai_client.chat.completions.create.return_value = mock_response
    result = await client.generate_followup("something changed", context=None)

    assert "changed" in result


@pytest.mark.asyncio
async def test_classify_reminder(client, mock_openai_client):
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

    mock_openai_client.chat.completions.create.return_value = mock_response
    result = await client.classify_input("remind me to take meds at 8pm")

    assert result.action == "store"
    assert result.category == "reminder"


@pytest.mark.asyncio
async def test_extract_reminder(client, mock_openai_client):
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

    mock_openai_client.chat.completions.create.return_value = mock_response
    result = await client.extract_memory("remind me to take meds at 8pm", None)

    assert result.category == "reminder"
    assert result.event_fields["datetime"] == "2026-03-21T20:00:00"
    assert result.event_fields["recurrence"] is None


@pytest.mark.asyncio
async def test_extract_recurring_reminder(client, mock_openai_client):
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

    mock_openai_client.chat.completions.create.return_value = mock_response
    result = await client.extract_memory("remind me every 8 hours to take meds", None)

    assert result.category == "reminder"
    assert result.event_fields["recurrence"] == "every 8 hours"


@pytest.mark.asyncio
async def test_describe_image(client, mock_openai_client):
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

    mock_openai_client.chat.completions.create.return_value = mock_response
    result = await client.describe_image(b"fake-image-bytes")

    assert result.title == "Ocean sunset"
    assert result.content == "A sunset over the ocean"
    assert result.category == "general"

    # Verify vision message format was used
    call_args = mock_openai_client.chat.completions.create.call_args
    messages = call_args.kwargs["messages"]
    assert len(messages) == 2
    assert messages[1]["role"] == "user"
    assert isinstance(messages[1]["content"], list)
    assert messages[1]["content"][0]["type"] == "image_url"


def test_classify_prompt_biases_toward_store():
    assert "prefer" in CLASSIFY_SYSTEM_PROMPT.lower()
    assert "store" in CLASSIFY_SYSTEM_PROMPT.lower()
    assert "unintelligible" in CLASSIFY_SYSTEM_PROMPT.lower()


@pytest.mark.asyncio
async def test_extract_memory_includes_current_time():
    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock()
    client = LLMClient(
        base_url="http://localhost:11434/v1",
        model="llama3",
        user_timezone="Asia/Singapore",
        _client=mock_client,
    )
    mock_response = AsyncMock()
    mock_response.choices = [
        AsyncMock(
            message=AsyncMock(
                content=json.dumps(
                    {
                        "content": "Take meds",
                        "category": "reminder",
                        "title": "Take meds",
                        "tags": ["health"],
                        "event_fields": {
                            "datetime": "2026-03-26T20:00:00+08:00",
                            "status": "pending",
                            "recurrence": None,
                        },
                    }
                )
            )
        )
    ]

    mock_client.chat.completions.create.return_value = mock_response
    await client.extract_memory("remind me to take meds at 8pm", None)

    call_args = mock_client.chat.completions.create.call_args
    messages = call_args.kwargs["messages"]
    system_msg = messages[0]["content"]
    assert "Current date and time:" in system_msg
    assert "Asia/Singapore" in system_msg


@pytest.mark.asyncio
async def test_llm_client_triage_returns_dict(client, mock_openai_client):
    response_data = {
        "should_save": True,
        "category": "profile",
        "title": "Likes coffee",
        "content": "User prefers black coffee",
        "tags": ["preference"],
        "importance": 5,
        "event_fields": None,
    }
    mock_response = AsyncMock()
    mock_response.choices = [
        AsyncMock(message=AsyncMock(content=json.dumps(response_data), reasoning_content=None))
    ]
    mock_openai_client.chat.completions.create.return_value = mock_response
    result = await client.triage("USER: I love black coffee", "", "2026-04-11T10:00:00")
    assert result["should_save"] is True
    assert result["category"] == "profile"


@pytest.mark.asyncio
async def test_llm_client_extract_triage_returns_dict(client, mock_openai_client):
    response_data = {
        "category": "reminder",
        "title": "Pack bag",
        "content": "Pack bag in 10 minutes",
        "tags": ["reminder"],
        "importance": 6,
        "event_fields": {
            "datetime": "2026-04-11T10:10:00",
            "status": "pending",
            "recurrence": None,
        },
    }
    mock_response = AsyncMock()
    mock_response.choices = [
        AsyncMock(message=AsyncMock(content=json.dumps(response_data), reasoning_content=None))
    ]
    mock_openai_client.chat.completions.create.return_value = mock_response
    result = await client.extract_triage(
        "USER: Pack my bag in 10 minutes", "2026-04-11T10:00:00"
    )
    assert result["category"] == "reminder"
    assert result["event_fields"] is not None


def test_triage_prompt_templates_exist():
    from bearmemori.llm.client import _EXTRACTION_SYSTEM_TEMPLATE, _TRIAGE_SYSTEM_TEMPLATE

    assert "should_save" in _TRIAGE_SYSTEM_TEMPLATE
    assert "when in doubt" in _TRIAGE_SYSTEM_TEMPLATE.lower()
    assert "multiple messages" in _TRIAGE_SYSTEM_TEMPLATE
    assert "multiple unrelated topics" in _TRIAGE_SYSTEM_TEMPLATE
    assert "category" in _EXTRACTION_SYSTEM_TEMPLATE


@pytest.mark.asyncio
async def test_reflect_memory_returns_archive_decision(client, mock_openai_client):
    from datetime import UTC, datetime

    from bearmemori.storage.models import MemoryCategory, MemoryRecord

    record = MemoryRecord(
        id="mem_test",
        category=MemoryCategory.GENERAL,
        title="Old note",
        content="Some old content",
        created_at=datetime(2025, 1, 1, tzinfo=UTC),
        importance=2,
    )
    response_data = {
        "action": "archive",
        "new_importance": None,
        "reason": "Outdated and low value",
    }
    mock_response = AsyncMock()
    mock_response.choices = [
        AsyncMock(message=AsyncMock(content=json.dumps(response_data), reasoning_content=None))
    ]
    mock_openai_client.chat.completions.create.return_value = mock_response
    result = await client.reflect_memory(record)
    assert result["action"] == "archive"
    assert result["reason"] == "Outdated and low value"


@pytest.mark.asyncio
async def test_reflect_memory_returns_keep_with_new_importance(client, mock_openai_client):
    from datetime import UTC, datetime

    from bearmemori.storage.models import MemoryCategory, MemoryRecord

    record = MemoryRecord(
        id="mem_test2",
        category=MemoryCategory.PROFILE,
        title="Preference",
        content="Likes hiking",
        created_at=datetime(2025, 6, 1, tzinfo=UTC),
        importance=4,
    )
    response_data = {
        "action": "keep",
        "new_importance": 7,
        "reason": "Still relevant personal preference",
    }
    mock_response = AsyncMock()
    mock_response.choices = [
        AsyncMock(message=AsyncMock(content=json.dumps(response_data), reasoning_content=None))
    ]
    mock_openai_client.chat.completions.create.return_value = mock_response
    result = await client.reflect_memory(record)
    assert result["action"] == "keep"
    assert result["new_importance"] == 7


def test_reflect_memory_prompt_template_exists():
    from bearmemori.llm.client import _REFLECT_SYSTEM_PROMPT

    assert "archive" in _REFLECT_SYSTEM_PROMPT
    assert "new_importance" in _REFLECT_SYSTEM_PROMPT
    assert "reason" in _REFLECT_SYSTEM_PROMPT
