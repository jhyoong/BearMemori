from unittest.mock import AsyncMock, MagicMock

import pytest

from bearmemori.llm.client import ExtractionResult, LLMClient


def test_extraction_result_has_importance():
    result = ExtractionResult(
        content="Test",
        category="general",
        title="Test",
        tags=["test"],
        importance=7,
    )
    assert result.importance == 7


def test_extraction_result_default_importance():
    result = ExtractionResult(
        content="Test",
        category="general",
        title="Test",
        tags=["test"],
    )
    assert result.importance == 5


@pytest.mark.asyncio
async def test_extract_memory_parses_importance():
    client = LLMClient(base_url="http://fake", model="test")

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = (
        '{"content": "Test memory", "category": "general", '
        '"title": "Test", "tags": ["test"], "importance": 8, '
        '"event_fields": null}'
    )
    client._client.chat.completions.create = AsyncMock(return_value=mock_response)

    result = await client.extract_memory("test input", None)
    assert result.importance == 8


@pytest.mark.asyncio
async def test_extract_memory_defaults_importance_when_missing():
    client = LLMClient(base_url="http://fake", model="test")

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = (
        '{"content": "Test memory", "category": "general", '
        '"title": "Test", "tags": ["test"], "event_fields": null}'
    )
    client._client.chat.completions.create = AsyncMock(return_value=mock_response)

    result = await client.extract_memory("test input", None)
    assert result.importance == 5


@pytest.mark.asyncio
async def test_extract_memory_clamps_importance_above_10():
    client = LLMClient(base_url="http://fake", model="test")

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = (
        '{"content": "Test memory", "category": "general", '
        '"title": "Test", "tags": ["test"], "importance": 15, '
        '"event_fields": null}'
    )
    client._client.chat.completions.create = AsyncMock(return_value=mock_response)

    result = await client.extract_memory("test input", None)
    assert result.importance == 10


@pytest.mark.asyncio
async def test_extract_memory_clamps_importance_below_1():
    client = LLMClient(base_url="http://fake", model="test")

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = (
        '{"content": "Test memory", "category": "general", '
        '"title": "Test", "tags": ["test"], "importance": -2, '
        '"event_fields": null}'
    )
    client._client.chat.completions.create = AsyncMock(return_value=mock_response)

    result = await client.extract_memory("test input", None)
    assert result.importance == 1
