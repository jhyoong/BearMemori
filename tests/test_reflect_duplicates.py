from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bearmemori.llm.client import LLMClient
from bearmemori.storage.models import MemoryCategory, MemoryRecord


def _make_record(record_id: str, title: str, content: str) -> MemoryRecord:
    return MemoryRecord(
        id=record_id,
        category=MemoryCategory.GENERAL,
        title=title,
        content=content,
        created_at=datetime.now(UTC),
        importance=5,
    )


def _mock_openai(content: str):
    msg = SimpleNamespace(content=content, reasoning_content=None)
    choice = SimpleNamespace(message=msg)
    response = SimpleNamespace(choices=[choice])

    fake = SimpleNamespace()
    fake.chat = SimpleNamespace()
    fake.chat.completions = SimpleNamespace()
    fake.chat.completions.create = AsyncMock(return_value=response)
    return fake


@pytest.mark.asyncio
async def test_reflect_duplicates_returns_parsed_json():
    fake = _mock_openai('{"is_duplicate": true, "keep_id": "mem_a", "reasoning": "Same fact."}')
    client = LLMClient(base_url="x", model="m", _client=fake)
    group = [
        _make_record("mem_a", "Pizza preference", "User likes pepperoni"),
        _make_record("mem_b", "Pizza pref", "User prefers pepperoni"),
    ]
    result = await client.reflect_duplicates(group)
    assert result["is_duplicate"] is True
    assert result["keep_id"] == "mem_a"
    assert "Same fact" in result["reasoning"]


@pytest.mark.asyncio
async def test_reflect_duplicates_handles_negative():
    fake = _mock_openai('{"is_duplicate": false, "keep_id": "", "reasoning": "Different topics."}')
    client = LLMClient(base_url="x", model="m", _client=fake)
    group = [
        _make_record("mem_a", "A", "alpha"),
        _make_record("mem_b", "B", "beta"),
    ]
    result = await client.reflect_duplicates(group)
    assert result["is_duplicate"] is False
