"""Tests for the LLM client."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import openai
import pytest

from worker.llm_client import LLMClient, LLMError


@pytest.fixture
def mock_openai_client():
    """Mock the openai.AsyncOpenAI client."""
    with patch("worker.llm_client.openai.AsyncOpenAI") as mock:
        yield mock


async def test_complete_returns_text(mock_openai_client):
    """Mock completions.create to return a response, verify text returned."""
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message = MagicMock()
    mock_response.choices[0].message.content = "Hello, world!"
    mock_openai_client.return_value.chat.completions.create = AsyncMock(
        return_value=mock_response
    )

    client = LLMClient(base_url="http://localhost:8080/v1")
    result = await client.complete(model="mistral", prompt="Test prompt")

    assert result == "Hello, world!"
    mock_openai_client.return_value.chat.completions.create.assert_called_once()


async def test_complete_with_image_sends_multipart(mock_openai_client):
    """Verify the messages list includes image_url content part."""
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message = MagicMock()
    mock_response.choices[0].message.content = "Describe the image"
    mock_openai_client.return_value.chat.completions.create = AsyncMock(
        return_value=mock_response
    )

    client = LLMClient(base_url="http://localhost:8080/v1")
    await client.complete_with_image(
        model="llava", prompt="What is in this image?", image_b64="base64string"
    )

    call_kwargs = (
        mock_openai_client.return_value.chat.completions.create.call_args
    )
    messages = call_kwargs[1]["messages"]
    assert len(messages[0]["content"]) == 2
    assert messages[0]["content"][0] == {"type": "text", "text": "What is in this image?"}
    assert messages[0]["content"][1]["type"] == "image_url"


async def test_complete_raises_llm_error_on_api_error(mock_openai_client):
    """Mock APIError, verify LLMError raised."""
    mock_request = httpx.Request("POST", "http://localhost:8080/v1/chat/completions")
    mock_openai_client.return_value.chat.completions.create = AsyncMock(
        side_effect=openai.APIError("Test API error", request=mock_request, body=None)
    )

    client = LLMClient(base_url="http://localhost:8080/v1")
    with pytest.raises(LLMError, match="LLM API error"):
        await client.complete(model="mistral", prompt="Test prompt")


async def test_complete_raises_llm_error_on_connection_error(mock_openai_client):
    """Mock APIConnectionError, verify LLMError raised."""
    mock_request = httpx.Request("POST", "http://localhost:8080/v1/chat/completions")
    mock_openai_client.return_value.chat.completions.create = AsyncMock(
        side_effect=openai.APIConnectionError(request=mock_request)
    )

    client = LLMClient(base_url="http://localhost:8080/v1")
    with pytest.raises(LLMError, match="LLM API error"):
        await client.complete(model="mistral", prompt="Test prompt")