"""Tests for current_time injection in triage prompt."""

import json
from unittest.mock import AsyncMock, patch

import pytest

from bearmemori.core.triage import run_triage


@pytest.mark.asyncio
async def test_triage_includes_current_time_in_prompt():
    """When current_time is provided, it should appear in the LLM messages."""
    mock_response = {
        "choices": [{
            "message": {
                "content": json.dumps({"should_save": False}),
            }
        }]
    }

    with patch(
        "bearmemori.core.triage._llm_call",
        new_callable=AsyncMock,
        return_value=mock_response,
    ) as mock_call:
        await run_triage(
            conversation=[{"role": "user", "content": "Remind me in 10 minutes"}],
            llm_base_url="http://fake",
            llm_api_key="key",
            llm_model="model",
            current_time="Monday, March 24, 2026, 07:33 PM +0800 (Asia/Singapore)",
        )

        messages = mock_call.call_args[0][0]
        system_msg = messages[0]["content"]
        assert "Monday, March 24, 2026, 07:33 PM +0800" in system_msg, (
            f"System prompt should contain current_time, got:\n{system_msg}"
        )


@pytest.mark.asyncio
async def test_triage_generates_fallback_time_when_not_provided():
    """When current_time is None, triage should generate a server-side time."""
    mock_response = {
        "choices": [{
            "message": {
                "content": json.dumps({"should_save": False}),
            }
        }]
    }

    with patch(
        "bearmemori.core.triage._llm_call",
        new_callable=AsyncMock,
        return_value=mock_response,
    ) as mock_call:
        await run_triage(
            conversation=[{"role": "user", "content": "Remind me tomorrow"}],
            llm_base_url="http://fake",
            llm_api_key="key",
            llm_model="model",
            current_time=None,
        )

        messages = mock_call.call_args[0][0]
        system_msg = messages[0]["content"]
        assert "Current date and time:" in system_msg, (
            f"System prompt should contain fallback time, got:\n{system_msg}"
        )
