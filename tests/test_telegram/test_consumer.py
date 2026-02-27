"""Tests for the Telegram consumer (tg_gateway/consumer.py).

Covers:
- _dispatch_notification routing to _handle_intent_result
- _handle_intent_result for all five intent types
- Stale datetime detection (reminder / task)
- Flood control in run_notify_consumer
- _is_stale helper
"""

import asyncio
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tg_gateway.consumer import (
    FLOOD_CONTROL_DELAY_SECONDS,
    _dispatch_notification,
    _handle_intent_result,
    _is_stale,
    run_notify_consumer,
)
from tg_gateway.handlers.conversation import (
    AWAITING_BUTTON_ACTION,
    PENDING_LLM_CONVERSATION,
    USER_QUEUE_COUNT,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_application(user_data: dict | None = None) -> MagicMock:
    """Return a mock Application with a mocked bot and user_data store."""
    app = MagicMock()
    app.bot = MagicMock()
    app.bot.send_message = AsyncMock()
    app.user_data = user_data if user_data is not None else {}
    return app


def _future_iso() -> str:
    """Return an ISO datetime string one hour in the future (UTC)."""
    return (datetime.now(tz=timezone.utc) + timedelta(hours=1)).isoformat()


def _past_iso() -> str:
    """Return an ISO datetime string one hour in the past (UTC)."""
    return (datetime.now(tz=timezone.utc) - timedelta(hours=1)).isoformat()


# ---------------------------------------------------------------------------
# _is_stale
# ---------------------------------------------------------------------------


class TestIsStale:
    def test_past_datetime_is_stale(self):
        assert _is_stale(_past_iso()) is True

    def test_future_datetime_is_not_stale(self):
        assert _is_stale(_future_iso()) is False

    def test_invalid_string_returns_false(self):
        assert _is_stale("not-a-date") is False

    def test_empty_string_returns_false(self):
        assert _is_stale("") is False

    def test_naive_past_datetime_treated_as_utc_and_stale(self):
        # A naive ISO string from the past should be treated as UTC and return True.
        naive_past = (
            (datetime.now(tz=timezone.utc) - timedelta(hours=2))
            .replace(tzinfo=None)
            .isoformat()
        )
        assert _is_stale(naive_past) is True

    def test_naive_future_datetime_treated_as_utc_and_not_stale(self):
        naive_future = (
            (datetime.now(tz=timezone.utc) + timedelta(hours=2))
            .replace(tzinfo=None)
            .isoformat()
        )
        assert _is_stale(naive_future) is False


# ---------------------------------------------------------------------------
# _handle_intent_result — reminder intent
# ---------------------------------------------------------------------------


class TestHandleIntentResultReminder:
    @pytest.mark.asyncio
    async def test_reminder_fresh_sends_proposal_keyboard(self):
        app = _make_application()
        content = {
            "intent": "reminder",
            "query": "Call mom",
            "memory_id": "mem-r1",
            "extracted_datetime": _future_iso(),
        }

        await _handle_intent_result(app, "12345", content)

        app.bot.send_message.assert_called_once()
        call_kwargs = app.bot.send_message.call_args[1]
        assert "mem-r1" in str(call_kwargs.get("reply_markup", ""))
        assert "Call mom" in call_kwargs.get("text", "")
        # State set
        assert app.user_data[12345][AWAITING_BUTTON_ACTION] == {"memory_id": "mem-r1"}

    @pytest.mark.asyncio
    async def test_reminder_stale_sends_reschedule_keyboard(self):
        app = _make_application()
        content = {
            "intent": "reminder",
            "query": "Buy groceries",
            "memory_id": "mem-r2",
            "extracted_datetime": _past_iso(),
        }

        await _handle_intent_result(app, "12345", content)

        app.bot.send_message.assert_called_once()
        call_kwargs = app.bot.send_message.call_args[1]
        text = call_kwargs.get("text", "")
        assert "passed" in text.lower() or "reschedule" in text.lower()
        # State still set (user needs to act)
        assert app.user_data[12345][AWAITING_BUTTON_ACTION] == {"memory_id": "mem-r2"}

    @pytest.mark.asyncio
    async def test_reminder_no_datetime_shows_unspecified(self):
        app = _make_application()
        content = {
            "intent": "reminder",
            "query": "Buy groceries",
            "memory_id": "mem-r3",
            "extracted_datetime": None,
        }

        await _handle_intent_result(app, "12345", content)

        call_kwargs = app.bot.send_message.call_args[1]
        assert "unspecified" in call_kwargs.get("text", "").lower()

    @pytest.mark.asyncio
    async def test_reminder_with_resolved_time_shows_datetime(self):
        """Test that reminder uses resolved_time field (not extracted_datetime)."""
        app = _make_application()
        future_dt = _future_iso()
        content = {
            "intent": "reminder",
            "query": "Call mom",
            "memory_id": "mem-r4",
            "resolved_time": future_dt,
        }

        await _handle_intent_result(app, "12345", content)

        call_kwargs = app.bot.send_message.call_args[1]
        text = call_kwargs.get("text", "")
        assert "Call mom" in text
        assert future_dt in text, f"Expected resolved_time {future_dt} in text: {text}"
        # Should NOT show "unspecified time"
        assert "unspecified" not in text.lower()

    @pytest.mark.asyncio
    async def test_reminder_stale_with_resolved_time_shows_reschedule(self):
        """Test that stale detection uses resolved_time field."""
        app = _make_application()
        past_dt = _past_iso()
        content = {
            "intent": "reminder",
            "query": "Buy groceries",
            "memory_id": "mem-r5",
            "resolved_time": past_dt,
        }

        await _handle_intent_result(app, "12345", content)

        call_kwargs = app.bot.send_message.call_args[1]
        text = call_kwargs.get("text", "")
        assert "passed" in text.lower() or "reschedule" in text.lower()
        # Reschedule keyboard should be present
        assert call_kwargs.get("reply_markup") is not None

    @pytest.mark.asyncio
    async def test_reminder_no_resolved_time_falls_back_to_unspecified(self):
        """Test that missing resolved_time shows 'unspecified time'."""
        app = _make_application()
        content = {
            "intent": "reminder",
            "query": "Quick reminder",
            "memory_id": "mem-r6",
            "resolved_time": None,
        }

        await _handle_intent_result(app, "12345", content)

        call_kwargs = app.bot.send_message.call_args[1]
        text = call_kwargs.get("text", "")
        assert "unspecified time" in text

    @pytest.mark.asyncio
    async def test_reminder_initialises_user_data_if_absent(self):
        # user_data for uid 99 does not pre-exist
        app = _make_application()
        content = {
            "intent": "reminder",
            "query": "Test",
            "memory_id": "mem-x",
            "extracted_datetime": _future_iso(),
        }

        await _handle_intent_result(app, "99", content)

        assert 99 in app.user_data
        assert app.user_data[99][AWAITING_BUTTON_ACTION] == {"memory_id": "mem-x"}


# ---------------------------------------------------------------------------
# _handle_intent_result — task intent
# ---------------------------------------------------------------------------


class TestHandleIntentResultTask:
    @pytest.mark.asyncio
    async def test_task_fresh_sends_proposal_keyboard(self):
        app = _make_application()
        content = {
            "intent": "task",
            "query": "Finish report",
            "memory_id": "mem-t1",
            "extracted_datetime": _future_iso(),
        }

        await _handle_intent_result(app, "12345", content)

        call_kwargs = app.bot.send_message.call_args[1]
        text = call_kwargs.get("text", "")
        assert "Finish report" in text
        assert "Task:" in text
        assert app.user_data[12345][AWAITING_BUTTON_ACTION] == {"memory_id": "mem-t1"}

    @pytest.mark.asyncio
    async def test_task_stale_sends_reschedule_keyboard(self):
        app = _make_application()
        content = {
            "intent": "task",
            "query": "Submit form",
            "memory_id": "mem-t2",
            "extracted_datetime": _past_iso(),
        }

        await _handle_intent_result(app, "12345", content)

        call_kwargs = app.bot.send_message.call_args[1]
        text = call_kwargs.get("text", "")
        assert "passed" in text.lower() or "reschedule" in text.lower()
        assert app.user_data[12345][AWAITING_BUTTON_ACTION] == {"memory_id": "mem-t2"}

    @pytest.mark.asyncio
    async def test_task_no_datetime_shows_unspecified(self):
        app = _make_application()
        content = {
            "intent": "task",
            "query": "Clean desk",
            "memory_id": "mem-t3",
            "extracted_datetime": None,
        }

        await _handle_intent_result(app, "12345", content)

        call_kwargs = app.bot.send_message.call_args[1]
        assert "unspecified" in call_kwargs.get("text", "").lower()

    @pytest.mark.asyncio
    async def test_task_with_resolved_due_time_shows_datetime(self):
        """Test that task uses resolved_due_time field (not extracted_datetime)."""
        app = _make_application()
        future_dt = _future_iso()
        content = {
            "intent": "task",
            "query": "Finish report",
            "memory_id": "mem-t4",
            "resolved_due_time": future_dt,
        }

        await _handle_intent_result(app, "12345", content)

        call_kwargs = app.bot.send_message.call_args[1]
        text = call_kwargs.get("text", "")
        assert "Finish report" in text
        assert "Task:" in text
        assert future_dt in text, (
            f"Expected resolved_due_time {future_dt} in text: {text}"
        )
        # Should NOT show "unspecified"
        assert "unspecified" not in text.lower()

    @pytest.mark.asyncio
    async def test_task_stale_with_resolved_due_time_shows_reschedule(self):
        """Test that stale detection uses resolved_due_time field."""
        app = _make_application()
        past_dt = _past_iso()
        content = {
            "intent": "task",
            "query": "Submit form",
            "memory_id": "mem-t5",
            "resolved_due_time": past_dt,
        }

        await _handle_intent_result(app, "12345", content)

        call_kwargs = app.bot.send_message.call_args[1]
        text = call_kwargs.get("text", "")
        assert "passed" in text.lower() or "reschedule" in text.lower()
        # Reschedule keyboard should be present
        assert call_kwargs.get("reply_markup") is not None

    @pytest.mark.asyncio
    async def test_task_no_resolved_due_time_falls_back_to_unspecified(self):
        """Test that missing resolved_due_time shows 'unspecified'."""
        app = _make_application()
        content = {
            "intent": "task",
            "query": "Clean desk",
            "memory_id": "mem-t6",
            "resolved_due_time": None,
        }

        await _handle_intent_result(app, "12345", content)

        call_kwargs = app.bot.send_message.call_args[1]
        text = call_kwargs.get("text", "")
        assert "unspecified" in text


# ---------------------------------------------------------------------------
# _handle_intent_result — search intent
# ---------------------------------------------------------------------------


class TestHandleIntentResultSearch:
    @pytest.mark.asyncio
    async def test_search_with_results_sends_keyboard(self):
        app = _make_application()
        content = {
            "intent": "search",
            "query": "python tips",
            "memory_id": "",
            "search_results": [
                {"title": "Python tricks", "memory_id": "mem-s1"},
                {"title": "Advanced Python", "memory_id": "mem-s2"},
            ],
        }

        await _handle_intent_result(app, "12345", content)

        call_kwargs = app.bot.send_message.call_args[1]
        text = call_kwargs.get("text", "")
        assert "python tips" in text.lower() or "search" in text.lower()
        assert call_kwargs.get("reply_markup") is not None

    @pytest.mark.asyncio
    async def test_search_no_results_sends_plain_message(self):
        app = _make_application()
        content = {
            "intent": "search",
            "query": "xyzzy",
            "memory_id": "",
            "search_results": [],
        }

        await _handle_intent_result(app, "12345", content)

        call_kwargs = app.bot.send_message.call_args[1]
        assert call_kwargs.get("reply_markup") is None
        assert "no results" in call_kwargs.get("text", "").lower()

    @pytest.mark.asyncio
    async def test_search_decrements_queue_counter(self):
        app = _make_application(user_data={12345: {USER_QUEUE_COUNT: 3}})
        content = {
            "intent": "search",
            "query": "anything",
            "memory_id": "",
            "search_results": [],
        }

        await _handle_intent_result(app, "12345", content)

        assert app.user_data[12345][USER_QUEUE_COUNT] == 2

    @pytest.mark.asyncio
    async def test_search_queue_clamps_at_zero(self):
        app = _make_application(user_data={12345: {USER_QUEUE_COUNT: 0}})
        content = {
            "intent": "search",
            "query": "anything",
            "memory_id": "",
            "search_results": [],
        }

        await _handle_intent_result(app, "12345", content)

        assert app.user_data[12345][USER_QUEUE_COUNT] == 0

    @pytest.mark.asyncio
    async def test_search_does_not_set_awaiting_button_action(self):
        app = _make_application()
        content = {
            "intent": "search",
            "query": "anything",
            "memory_id": "",
            "search_results": [],
        }

        await _handle_intent_result(app, "12345", content)

        assert AWAITING_BUTTON_ACTION not in app.user_data.get(12345, {})


# ---------------------------------------------------------------------------
# _handle_intent_result — general_note intent
# ---------------------------------------------------------------------------


class TestHandleIntentResultGeneralNote:
    @pytest.mark.asyncio
    async def test_general_note_sends_note_keyboard(self):
        app = _make_application()
        content = {
            "intent": "general_note",
            "query": "Remember to water the plants",
            "memory_id": "mem-n1",
            "suggested_tags": ["plants", "home"],
        }

        await _handle_intent_result(app, "12345", content)

        call_kwargs = app.bot.send_message.call_args[1]
        text = call_kwargs.get("text", "")
        assert "Suggested tags" in text
        assert "plants" in text
        assert "home" in text
        assert call_kwargs.get("reply_markup") is not None
        assert app.user_data[12345][AWAITING_BUTTON_ACTION] == {"memory_id": "mem-n1"}

    @pytest.mark.asyncio
    async def test_general_note_empty_tags(self):
        app = _make_application()
        content = {
            "intent": "general_note",
            "query": "Quick thought",
            "memory_id": "mem-n2",
            "suggested_tags": [],
        }

        await _handle_intent_result(app, "12345", content)

        app.bot.send_message.assert_called_once()
        assert app.user_data[12345][AWAITING_BUTTON_ACTION] == {"memory_id": "mem-n2"}


# ---------------------------------------------------------------------------
# _handle_intent_result — ambiguous intent
# ---------------------------------------------------------------------------


class TestHandleIntentResultAmbiguous:
    @pytest.mark.asyncio
    async def test_ambiguous_sends_followup_question(self):
        app = _make_application()
        content = {
            "intent": "ambiguous",
            "query": "Do the thing",
            "memory_id": "mem-a1",
            "followup_question": "Should I create a task or a reminder?",
        }

        await _handle_intent_result(app, "12345", content)

        call_kwargs = app.bot.send_message.call_args[1]
        assert "Should I create a task or a reminder?" in call_kwargs.get("text", "")
        # No keyboard for ambiguous
        assert call_kwargs.get("reply_markup") is None

    @pytest.mark.asyncio
    async def test_ambiguous_sets_pending_llm_conversation(self):
        app = _make_application()
        content = {
            "intent": "ambiguous",
            "query": "do something",
            "memory_id": "mem-a2",
            "followup_question": "What exactly do you mean?",
        }

        await _handle_intent_result(app, "12345", content)

        pending = app.user_data[12345].get(PENDING_LLM_CONVERSATION)
        assert pending is not None
        assert pending["memory_id"] == "mem-a2"
        assert pending["original_text"] == "do something"
        assert pending["followup_question"] == "What exactly do you mean?"

    @pytest.mark.asyncio
    async def test_ambiguous_does_not_set_awaiting_button_action(self):
        app = _make_application()
        content = {
            "intent": "ambiguous",
            "query": "huh",
            "memory_id": "mem-a3",
            "followup_question": "Please clarify.",
        }

        await _handle_intent_result(app, "12345", content)

        assert AWAITING_BUTTON_ACTION not in app.user_data.get(12345, {})


# ---------------------------------------------------------------------------
# _handle_intent_result — unknown intent fallback
# ---------------------------------------------------------------------------


class TestHandleIntentResultUnknown:
    @pytest.mark.asyncio
    async def test_unknown_intent_sends_generic_message(self):
        app = _make_application()
        content = {
            "intent": "definitely_not_a_real_intent",
            "query": "something strange",
            "memory_id": "mem-u1",
        }

        await _handle_intent_result(app, "12345", content)

        app.bot.send_message.assert_called_once()
        text = app.bot.send_message.call_args[1].get("text", "")
        assert "something strange" in text


# ---------------------------------------------------------------------------
# _dispatch_notification routing
# ---------------------------------------------------------------------------


class TestDispatchNotificationIntentResult:
    @pytest.mark.asyncio
    async def test_dispatch_routes_intent_result_to_handler(self):
        app = _make_application()
        data = {
            "user_id": "12345",
            "message_type": "llm_intent_result",
            "content": {
                "intent": "general_note",
                "query": "Test note",
                "memory_id": "mem-d1",
                "suggested_tags": [],
            },
        }

        await _dispatch_notification(app, data)

        app.bot.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_dispatch_reminder_type_does_not_use_intent_handler(self):
        """The 'reminder' message_type (scheduled reminder) uses a different path
        from the 'llm_intent_result' with intent=='reminder'."""
        app = _make_application()
        data = {
            "user_id": "12345",
            "message_type": "reminder",
            "content": {
                "memory_content": "Call the bank",
                "fire_at": "2030-01-01 09:00",
            },
        }

        await _dispatch_notification(app, data)

        call_args = app.bot.send_message.call_args[1]
        assert "Call the bank" in call_args.get("text", "")


# ---------------------------------------------------------------------------
# Flood control in run_notify_consumer
# ---------------------------------------------------------------------------


class TestFloodControl:
    @pytest.mark.asyncio
    async def test_flood_control_sleeps_between_same_user_messages(self):
        """When two consecutive messages are for the same user, sleep is called."""
        app = _make_application()

        # Two messages for the same user
        msg1 = {
            "user_id": "111",
            "message_type": "llm_intent_result",
            "content": {
                "intent": "general_note",
                "query": "First",
                "memory_id": "mem-f1",
                "suggested_tags": [],
            },
        }
        msg2 = {
            "user_id": "111",
            "message_type": "llm_intent_result",
            "content": {
                "intent": "general_note",
                "query": "Second",
                "memory_id": "mem-f2",
                "suggested_tags": [],
            },
        }

        messages = [
            ("id-1", msg1),
            ("id-2", msg2),
        ]

        # Mock redis: returns messages on first call, then empty list (loop idles).
        # We cancel the task externally to terminate.
        call_count = 0

        async def fake_consume(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return messages
            # Block indefinitely so we can cancel from outside.
            await asyncio.sleep(9999)
            return []

        async def fake_ack(*args, **kwargs):
            pass

        async def fake_create_group(*args, **kwargs):
            pass

        app.bot_data = {"redis": AsyncMock()}

        sleep_calls = []
        real_sleep = asyncio.sleep

        async def tracking_sleep(seconds):
            sleep_calls.append(seconds)
            # Only yield briefly so the loop progresses without actually waiting.
            await real_sleep(0)

        with (
            patch("tg_gateway.consumer.consume", side_effect=fake_consume),
            patch("tg_gateway.consumer.ack", side_effect=fake_ack),
            patch(
                "tg_gateway.consumer.create_consumer_group",
                side_effect=fake_create_group,
            ),
            patch("tg_gateway.consumer.asyncio.sleep", side_effect=tracking_sleep),
        ):
            task = asyncio.create_task(run_notify_consumer(app))
            # Give enough time for both messages to be processed.
            await real_sleep(0.1)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        # The flood-control sleep (FLOOD_CONTROL_DELAY_SECONDS) must appear.
        assert FLOOD_CONTROL_DELAY_SECONDS in sleep_calls, (
            f"Expected flood-control sleep of {FLOOD_CONTROL_DELAY_SECONDS}s, "
            f"got sleep calls: {sleep_calls}"
        )

    @pytest.mark.asyncio
    async def test_flood_control_no_sleep_for_different_users(self):
        """No flood-control sleep when consecutive messages are for different users."""
        app = _make_application()

        msg1 = {
            "user_id": "111",
            "message_type": "llm_intent_result",
            "content": {
                "intent": "general_note",
                "query": "First",
                "memory_id": "mem-g1",
                "suggested_tags": [],
            },
        }
        msg2 = {
            "user_id": "222",
            "message_type": "llm_intent_result",
            "content": {
                "intent": "general_note",
                "query": "Second",
                "memory_id": "mem-g2",
                "suggested_tags": [],
            },
        }

        messages = [
            ("id-1", msg1),
            ("id-2", msg2),
        ]

        call_count = 0

        async def fake_consume(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return messages
            await asyncio.sleep(9999)
            return []

        async def fake_ack(*args, **kwargs):
            pass

        async def fake_create_group(*args, **kwargs):
            pass

        app.bot_data = {"redis": AsyncMock()}

        sleep_calls = []
        real_sleep = asyncio.sleep

        async def tracking_sleep(seconds):
            sleep_calls.append(seconds)
            await real_sleep(0)

        with (
            patch("tg_gateway.consumer.consume", side_effect=fake_consume),
            patch("tg_gateway.consumer.ack", side_effect=fake_ack),
            patch(
                "tg_gateway.consumer.create_consumer_group",
                side_effect=fake_create_group,
            ),
            patch("tg_gateway.consumer.asyncio.sleep", side_effect=tracking_sleep),
        ):
            task = asyncio.create_task(run_notify_consumer(app))
            await real_sleep(0.1)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        # Flood-control sleep must NOT have been called (only back-off sleep may appear).
        assert FLOOD_CONTROL_DELAY_SECONDS not in sleep_calls, (
            f"Flood-control sleep should not occur for different users, "
            f"got sleep calls: {sleep_calls}"
        )
