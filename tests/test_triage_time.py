"""Tests for current_time injection in triage prompt."""

from unittest.mock import AsyncMock, patch

import pytest

from bearmemori.core.triage import run_triage
from bearmemori.llm.client import LLMClient


@pytest.fixture
def llm():
    return LLMClient(base_url="http://localhost:11434/v1", model="test", api_key="test")


@pytest.mark.asyncio
async def test_triage_includes_current_time_in_prompt(llm):
    """When current_time is provided, it should be passed to llm.triage()."""
    given_time = "Monday, March 24, 2026, 07:33 PM +0800 (Asia/Singapore)"

    with patch.object(
        llm, "triage", new_callable=AsyncMock, return_value={"should_save": False}
    ) as mock_triage:
        await run_triage(
            conversation=[{"role": "user", "content": "Remind me in 10 minutes"}],
            llm=llm,
            current_time=given_time,
        )

        mock_triage.assert_called_once()
        # current_time is the third positional arg to llm.triage()
        _, _, passed_time = mock_triage.call_args[0]
        assert passed_time == given_time, (
            f"current_time should be passed to llm.triage(), got: {passed_time}"
        )


@pytest.mark.asyncio
async def test_triage_generates_fallback_time_when_not_provided(llm):
    """When current_time is None, triage should generate a server-side time and pass it."""
    with patch.object(
        llm, "triage", new_callable=AsyncMock, return_value={"should_save": False}
    ) as mock_triage:
        await run_triage(
            conversation=[{"role": "user", "content": "Remind me tomorrow"}],
            llm=llm,
            current_time=None,
        )

        mock_triage.assert_called_once()
        _, _, passed_time = mock_triage.call_args[0]
        assert passed_time is not None and len(passed_time) > 0, (
            f"A fallback time string should be generated and passed, got: {passed_time}"
        )
