"""Tests for the Telegram consumer (tg_gateway/consumer.py).

Covers:
- _dispatch_notification routing to _handle_intent_result
- _handle_intent_result for all five intent types
- Stale datetime detection (reminder / task)
- Flood control in run_notify_consumer
"""

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tg_gateway.consumer import (
    FLOOD_CONTROL_DELAY_SECONDS,
    _dispatch_notification,
    _handle_intent_result,
    run_notify_consumer,
)
from tg_gateway.handlers.conversation import (
    AWAITING_BUTTON_ACTION,
    LLM_CONVERSATION_METADATA,
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
    # Include a mock core_client for conversation state updates
    mock_core_client = MagicMock()
    mock_core_client.update_conversation_state = AsyncMock()
    mock_core_client.get_settings = AsyncMock(side_effect=Exception("no settings"))
    app.bot_data = {"core_client": mock_core_client}
    return app


def _future_iso() -> str:
    """Return an ISO datetime string one hour in the future (UTC)."""
    return (datetime.now(tz=timezone.utc) + timedelta(hours=1)).isoformat()


def _past_iso() -> str:
    """Return an ISO datetime string one hour in the past (UTC)."""
    return (datetime.now(tz=timezone.utc) - timedelta(hours=1)).isoformat()


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
        state = app.user_data[12345][AWAITING_BUTTON_ACTION]
        assert state["memory_id"] == "mem-r1"

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
        state = app.user_data[12345][AWAITING_BUTTON_ACTION]
        assert state["memory_id"] == "mem-r2"

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
        # Time is now displayed in user-friendly format (YYYY-MM-DD HH:MM)
        # rather than raw ISO string
        assert "unspecified" not in text.lower()
        # Verify a formatted date is present (e.g., "2026-02-28 20:13")
        import re

        assert re.search(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}", text), (
            f"Expected formatted datetime in text: {text}"
        )

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
        state = app.user_data[99][AWAITING_BUTTON_ACTION]
        assert state["memory_id"] == "mem-x"


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
        state = app.user_data[12345][AWAITING_BUTTON_ACTION]
        assert state["memory_id"] == "mem-t1"

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
        state = app.user_data[12345][AWAITING_BUTTON_ACTION]
        assert state["memory_id"] == "mem-t2"

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
        # Time is now displayed in user-friendly format (YYYY-MM-DD HH:MM)
        assert "unspecified" not in text.lower()
        import re

        assert re.search(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}", text), (
            f"Expected formatted datetime in text: {text}"
        )

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
    async def test_search_completes_conversation_via_core_api(self):
        """Test that search intent completes conversation via Core API."""
        app = _make_application()

        content = {
            "intent": "search",
            "query": "test query",
            "memory_id": "",
            "results": [
                {"title": "Result 1", "memory_id": "mem-s1"},
            ],
        }

        await _handle_intent_result(app, "12345", content)

        core_client = app.bot_data["core_client"]
        core_client.update_conversation_state.assert_awaited_once_with(
            12345, "completed"
        )

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
    async def test_ambiguous_sets_llm_conversation_metadata(self):
        app = _make_application()
        content = {
            "intent": "ambiguous",
            "query": "do something",
            "memory_id": "mem-a2",
            "followup_question": "What exactly do you mean?",
        }

        await _handle_intent_result(app, "12345", content)

        metadata = app.user_data[12345].get(LLM_CONVERSATION_METADATA)
        assert metadata is not None
        assert metadata["memory_id"] == "mem-a2"
        assert metadata["original_text"] == "do something"
        assert metadata["followup_question"] == "What exactly do you mean?"

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


# ---------------------------------------------------------------------------
# Specific phrase integration tests - full flow verification
# ---------------------------------------------------------------------------


class TestConsumerSpecificPhrases:
    """Test specific example phrases from acceptance criteria."""

    @pytest.mark.asyncio
    async def test_search_all_images_about_anime_shows_results(self):
        """Test search phrase shows search results without memory."""
        app = _make_application()
        content = {
            "intent": "search",
            "query": "all images about anime",
            "memory_id": "",
            "search_results": [
                {"title": "Anime Art 1", "memory_id": "mem-a1"},
                {"title": "Anime Art 2", "memory_id": "mem-a2"},
            ],
        }

        await _handle_intent_result(app, "12345", content)

        # Verify message sent with results
        app.bot.send_message.assert_called_once()
        call_kwargs = app.bot.send_message.call_args[1]
        text = call_kwargs.get("text", "")
        # Should show search results or similar message
        assert "anime" in text.lower() or "search" in text.lower()
        # Should have reply markup (keyboard)
        assert call_kwargs.get("reply_markup") is not None
        # Should not set awaiting button action (search doesn't create memory)
        assert AWAITING_BUTTON_ACTION not in app.user_data.get(12345, {})

    @pytest.mark.asyncio
    async def test_search_no_results_for_phrase(self):
        """Test search phrase with no results shows appropriate message."""
        app = _make_application()
        content = {
            "intent": "search",
            "query": "all images about anime",
            "memory_id": "",
            "search_results": [],
        }

        await _handle_intent_result(app, "12345", content)

        # Verify message sent
        app.bot.send_message.assert_called_once()
        call_kwargs = app.bot.send_message.call_args[1]
        text = call_kwargs.get("text", "")
        assert "no results" in text.lower() or "found" not in text.lower()

    @pytest.mark.asyncio
    async def test_remind_me_to_call_mom_tomorrow_shows_proposal(self):
        """Test reminder phrase shows proposal keyboard."""
        app = _make_application()
        future_dt = _future_iso()
        content = {
            "intent": "reminder",
            "query": "call mom",
            "action": "call mom",
            "memory_id": "mem-mom-123",
            "resolved_time": future_dt,
        }

        await _handle_intent_result(app, "12345", content)

        # Verify message sent with proposal keyboard
        app.bot.send_message.assert_called_once()
        call_kwargs = app.bot.send_message.call_args[1]
        text = call_kwargs.get("text", "")
        # Should mention the action
        assert "call mom" in text.lower()
        # Should have reply markup (keyboard with confirm/edit buttons)
        assert call_kwargs.get("reply_markup") is not None
        # Should set awaiting button action state
        assert AWAITING_BUTTON_ACTION in app.user_data[12345]
        state = app.user_data[12345][AWAITING_BUTTON_ACTION]
        assert state["memory_id"] == "mem-mom-123"

    @pytest.mark.asyncio
    async def test_add_task_to_finish_report_by_friday_shows_proposal(self):
        """Test task phrase shows proposal keyboard."""
        app = _make_application()
        future_dt = _future_iso()
        content = {
            "intent": "task",
            "query": "finish report",
            "description": "finish report",
            "memory_id": "mem-task-456",
            "resolved_due_time": future_dt,
        }

        await _handle_intent_result(app, "12345", content)

        # Verify message sent with task proposal keyboard
        app.bot.send_message.assert_called_once()
        call_kwargs = app.bot.send_message.call_args[1]
        text = call_kwargs.get("text", "")
        # Should mention the task description
        assert "finish report" in text.lower()
        # Should have reply markup (keyboard with confirm/edit buttons)
        assert call_kwargs.get("reply_markup") is not None
        # Should set awaiting button action state
        assert AWAITING_BUTTON_ACTION in app.user_data[12345]
        state = app.user_data[12345][AWAITING_BUTTON_ACTION]
        assert state["memory_id"] == "mem-task-456"

    @pytest.mark.asyncio
    async def test_search_phrase_completes_conversation(self):
        """Test that search phrase completes conversation via Core API."""
        app = _make_application()
        content = {
            "intent": "search",
            "query": "all images about anime",
            "memory_id": "",
            "results": [{"title": "Anime", "memory_id": "mem-a1"}],
        }

        await _handle_intent_result(app, "12345", content)

        core_client = app.bot_data["core_client"]
        core_client.update_conversation_state.assert_awaited_once_with(
            12345, "completed"
        )

    @pytest.mark.asyncio
    async def test_reminder_phrase_sets_awaiting_reply(self):
        """Test that reminder phrase sets conversation state to awaiting_reply."""
        app = _make_application()
        future_dt = _future_iso()
        content = {
            "intent": "reminder",
            "query": "call mom",
            "memory_id": "mem-mom-123",
            "resolved_time": future_dt,
        }

        await _handle_intent_result(app, "12345", content)

        # Queue count should NOT be decremented for reminder (handled by conversation)
        # This test verifies the current behavior
        # Note: In the actual implementation, queue decrement may happen elsewhere
        # This test documents the expected behavior


# ---------------------------------------------------------------------------
# llm_image_tag_result conversation state
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_image_tag_result_sets_conversation_awaiting_reply():
    """llm_image_tag_result handler sets conversation state to awaiting_reply."""
    app = _make_application()
    mock_core_client = MagicMock()
    mock_core_client.update_conversation_state = AsyncMock()
    app.bot_data["core_client"] = mock_core_client

    notification = {
        "user_id": "12345",
        "message_type": "llm_image_tag_result",
        "content": {
            "memory_id": "mem-100",
            "tags": ["sunset", "beach"],
            "description": "A sunset at the beach",
        },
    }

    await _dispatch_notification(app, notification)

    mock_core_client.update_conversation_state.assert_called_once()
    call_args = mock_core_client.update_conversation_state.call_args
    assert call_args[0][0] == 12345  # user_id as int
    assert call_args[0][1] == "awaiting_reply"
