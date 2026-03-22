import json
from unittest.mock import patch

import pytest

from bearmemori.core.triage import run_triage
from bearmemori.storage.models import MemoryCategory


@pytest.mark.asyncio
async def test_triage_should_save():
    response_data = {
        "should_save": True,
        "category": "profile",
        "title": "Likes coffee",
        "content": "User prefers black coffee",
        "tags": ["preference"],
        "event_fields": None,
    }
    with patch(
        "bearmemori.core.triage._llm_call",
        return_value={"choices": [{"message": {"content": json.dumps(response_data)}}]},
    ):
        result = await run_triage(
            [{"role": "user", "content": "I love black coffee"}],
            llm_base_url="http://localhost:11434/v1",
            llm_api_key="test",
            llm_model="test",
        )
    assert result.should_save is True
    assert result.draft is not None
    assert result.draft.category == MemoryCategory.PROFILE


@pytest.mark.asyncio
async def test_triage_should_not_save():
    with patch(
        "bearmemori.core.triage._llm_call",
        return_value={"choices": [{"message": {"content": json.dumps({"should_save": False})}}]},
    ):
        result = await run_triage(
            [{"role": "user", "content": "Hello"}],
            llm_base_url="http://localhost:11434/v1",
            llm_api_key="test",
            llm_model="test",
        )
    assert result.should_save is False
    assert result.draft is None


@pytest.mark.asyncio
async def test_triage_malformed_response():
    with patch(
        "bearmemori.core.triage._llm_call",
        return_value={"choices": [{"message": {"content": "not json"}}]},
    ):
        result = await run_triage(
            [{"role": "user", "content": "test"}],
            llm_base_url="http://localhost:11434/v1",
            llm_api_key="test",
            llm_model="test",
        )
    assert result.should_save is False


@pytest.mark.asyncio
async def test_triage_with_memory_hint():
    response_data = {
        "should_save": True,
        "category": "event",
        "title": "Meeting tomorrow",
        "content": "Team standup at 9am",
        "tags": ["meeting"],
        "event_fields": {"datetime": "2026-03-22T09:00:00", "status": "pending"},
    }
    with patch(
        "bearmemori.core.triage._llm_call",
        return_value={"choices": [{"message": {"content": json.dumps(response_data)}}]},
    ):
        result = await run_triage(
            [{"role": "user", "content": "I have a standup at 9am tomorrow"}],
            llm_base_url="http://localhost:11434/v1",
            llm_api_key="test",
            llm_model="test",
            memory_hint={"likely_category": "event", "confidence": "high"},
        )
    assert result.should_save is True
    assert result.draft.event_fields is not None
    assert result.draft.event_fields.datetime == "2026-03-22T09:00:00"
