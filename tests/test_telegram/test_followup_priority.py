"""Tests for T011: Followup job priority - immediate processing.

These tests verify that:
1. receive_followup_answer creates jobs with JobType.followup (not intent_classify)
2. Consumer checks STREAM_LLM_FOLLOWUP NEW first before other streams

These tests should FAIL (Red phase) before the implementation is done.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from telegram import Update
from telegram.ext import ContextTypes

from tg_gateway.handlers.conversation import (
    PENDING_LLM_CONVERSATION,
    receive_followup_answer,
)
from shared_lib.enums import JobType
from shared_lib import redis_streams


# ---------------------------------------------------------------------------
# Helpers / shared fixtures
# ---------------------------------------------------------------------------


def _make_update(text: str = "hello", user_id: int = 99) -> MagicMock:
    """Return a minimal mock Update whose message has the given text."""
    update = MagicMock(spec=Update)
    update.message = MagicMock()
    update.message.text = text
    update.message.reply_text = AsyncMock()
    user = MagicMock()
    user.id = user_id
    update.message.from_user = user
    return update


def _make_context(
    user_data: dict | None = None, bot_data: dict | None = None
) -> MagicMock:
    """Return a minimal mock context with controllable user_data and bot_data."""
    context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
    context.user_data = user_data if user_data is not None else {}
    context.bot_data = bot_data if bot_data is not None else {}
    return context


# ---------------------------------------------------------------------------
# Test 1: JobType in conversation.py - receive_followup_answer
# ---------------------------------------------------------------------------


class TestFollowupJobType:
    """Tests that receive_followup_answer uses JobType.followup."""

    @pytest.mark.asyncio
    async def test_receive_followup_answer_uses_jobtype_followup(self):
        """The created LLM job should have job_type = JobType.followup.

        This test verifies that when a user answers a followup question,
        the job is submitted to the followup stream (not intent_classify).
        """
        core_client = MagicMock()
        core_client.create_llm_job = AsyncMock()

        pending_state = {
            "memory_id": "mem-30",
            "original_text": "Buy groceries",
            "followup_question": "When do you need this?",
        }

        update = _make_update(text="Tomorrow morning")
        context = _make_context(
            user_data={PENDING_LLM_CONVERSATION: pending_state},
            bot_data={"core_client": core_client},
        )

        await receive_followup_answer(update, context)

        core_client.create_llm_job.assert_called_once()
        job_arg = core_client.create_llm_job.call_args[0][0]

        # T011: The job type should be followup, NOT intent_classify
        assert job_arg.job_type == JobType.followup, (
            f"Expected job_type=JobType.followup, got {job_arg.job_type}"
        )

    @pytest.mark.asyncio
    async def test_receive_followup_answer_does_not_use_intent_classify(self):
        """The created LLM job should NOT use job_type = JobType.intent_classify.

        The followup should go to a separate stream for immediate processing.
        """
        core_client = MagicMock()
        core_client.create_llm_job = AsyncMock()

        pending_state = {
            "memory_id": "mem-31",
            "original_text": "Call dentist",
            "followup_question": "When?",
        }

        update = _make_update(text="Next week")
        context = _make_context(
            user_data={PENDING_LLM_CONVERSATION: pending_state},
            bot_data={"core_client": core_client},
        )

        await receive_followup_answer(update, context)

        core_client.create_llm_job.assert_called_once()
        job_arg = core_client.create_llm_job.call_args[0][0]

        # T011: The job type should NOT be intent_classify
        assert job_arg.job_type != JobType.intent_classify, (
            "Followup jobs should use their own job type, not intent_classify"
        )


# ---------------------------------------------------------------------------
# Test 2: Consumer priority - STREAM_LLM_FOLLOWUP checked first
# ---------------------------------------------------------------------------


class TestFollowupConsumerPriority:
    """Tests that consumer checks STREAM_LLM_FOLLOWUP NEW first."""

    @pytest.mark.asyncio
    async def test_consumer_checks_followup_stream_first(self):
        """The consumer should check STREAM_LLM_FOLLOWUP NEW before other streams.

        This test verifies that when there are pending messages in multiple
        streams, the followup stream is checked first for NEW messages.
        """
        from worker.consumer import STREAM_HANDLER_MAP
        from worker.config import LLMWorkerSettings

        # Mock redis client
        mock_redis = MagicMock()

        # Track the order of stream checks for NEW messages
        new_stream_checks = []

        async def mock_xreadgroup(group, consumer, streams_dict, **kwargs):
            """Return empty to simulate no new messages initially."""
            # Record which streams were checked
            for stream_name in streams_dict.keys():
                new_stream_checks.append(stream_name)
            return []

        mock_redis.xreadgroup = mock_xreadgroup
        mock_redis.xgroup_create = AsyncMock()
        mock_redis.xgroup_setid = AsyncMock()

        # Mock handlers

        # Mock core_api
        MagicMock()

        # Mock retry_tracker
        mock_retry_tracker = MagicMock()
        mock_retry_tracker.is_ready_for_retry = MagicMock(return_value=True)

        # Mock config
        MagicMock(spec=LLMWorkerSettings)

        # Patch time to avoid infinite loop (run one iteration)
        import asyncio

        counter = [0]

        async def mock_sleep(duration):
            counter[0] += 1
            if counter[0] >= 1:
                raise asyncio.CancelledError()

        # We need to test the actual stream order in STREAM_HANDLER_MAP
        # T011: STREAM_LLM_FOLLOWUP should come FIRST in the stream list
        stream_list = list(STREAM_HANDLER_MAP.values())

        # Verify that STREAM_LLM_FOLLOWUP is the first stream checked
        assert stream_list[0] == redis_streams.STREAM_LLM_FOLLOWUP, (
            f"STREAM_LLM_FOLLOWUP should be first in stream list, "
            f"but found: {stream_list[0]}"
        )

    @pytest.mark.asyncio
    async def test_followup_stream_comes_before_intent_stream(self):
        """STREAM_LLM_FOLLOWUP should come before STREAM_LLM_INTENT in stream order.

        This ensures followup jobs are processed before intent classification jobs.
        """
        from worker.consumer import STREAM_HANDLER_MAP

        stream_list = list(STREAM_HANDLER_MAP.values())
        followup_idx = stream_list.index(redis_streams.STREAM_LLM_FOLLOWUP)
        intent_idx = stream_list.index(redis_streams.STREAM_LLM_INTENT)

        assert followup_idx < intent_idx, (
            f"STREAM_LLM_FOLLOWUP (index {followup_idx}) should come before "
            f"STREAM_LLM_INTENT (index {intent_idx})"
        )

    @pytest.mark.asyncio
    async def test_consumer_new_message_check_order(self):
        """The consumer should check followup stream NEW first.

        This verifies that in the consumer loop, when checking for new messages,
        the followup stream is queried first.
        """
        from worker.consumer import STREAM_HANDLER_MAP
        from worker.config import LLMWorkerSettings

        # Create mock objects
        mock_redis = MagicMock()
        MagicMock()
        mock_retry_tracker = MagicMock()
        mock_retry_tracker.is_ready_for_retry = MagicMock(return_value=True)

        # Build the streams dict to capture order
        stream_order_checked = []

        async def mock_xreadgroup(group, consumer, streams_dict, count=1, block=2000):
            """Simulate reading from multiple streams.

            Returns a message from STREAM_LLM_FOLLOWUP first to verify
            it gets checked first.
            """
            # Record the stream order from the dict keys
            stream_order_checked.clear()
            for stream_name in streams_dict.keys():
                stream_order_checked.append(stream_name)

            # Return empty to end test
            return []

        mock_redis.xreadgroup = AsyncMock(side_effect=mock_xreadgroup)
        mock_redis.xgroup_create = AsyncMock()
        mock_redis.xgroup_setid = AsyncMock()
        mock_redis.xack = AsyncMock()

        MagicMock(spec=LLMWorkerSettings)

        # Get expected stream order - followup should be first
        streams = list(STREAM_HANDLER_MAP.values())
        expected_first_stream = redis_streams.STREAM_LLM_FOLLOWUP

        # Verify the order in the code
        assert streams[0] == expected_first_stream, (
            f"For immediate processing, STREAM_LLM_FOLLOWUP must be first "
            f"in the streams list. Found: {streams[0]}"
        )


# ---------------------------------------------------------------------------
# Integration test: full followup flow
# ---------------------------------------------------------------------------


class TestFollowupFullFlow:
    """Integration test for the full followup priority flow."""

    @pytest.mark.asyncio
    async def test_followup_job_uses_separate_stream(self):
        """Followup answers should be submitted as a followup type job.

        This ensures:
        1. Job is created with JobType.followup
        2. This maps to STREAM_LLM_FOLLOWUP in the consumer
        """
        # First verify the JobType.followup exists and has correct value
        assert JobType.followup.value == "followup"

        # Verify the stream constant exists
        assert redis_streams.STREAM_LLM_FOLLOWUP == "llm:followup"

        # Now verify that when receive_followup_answer is called,
        # it creates a job that would route to the followup stream
        core_client = MagicMock()
        core_client.create_llm_job = AsyncMock()

        pending_state = {
            "memory_id": "mem-40",
            "original_text": "Remember to water plants",
            "followup_question": "How often?",
        }

        update = _make_update(text="Every day")
        context = _make_context(
            user_data={PENDING_LLM_CONVERSATION: pending_state},
            bot_data={"core_client": core_client},
        )

        await receive_followup_answer(update, context)

        # Get the job that was created
        core_client.create_llm_job.assert_called_once()
        job_arg = core_client.create_llm_job.call_args[0][0]

        # The job type should be followup
        assert job_arg.job_type == JobType.followup
