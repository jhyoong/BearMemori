"""End-to-end integration tests for queue and conversation lifecycle."""

import pytest

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

QUEUE_PREFIX = "/queue"
CONV_PREFIX = "/conversations"


async def _enqueue(client, user_id: int, content: str = "hello") -> dict:
    """Enqueue a message and return the created QueueItem dict."""
    resp = await client.post(
        f"{QUEUE_PREFIX}/{user_id}/enqueue",
        json={"content": content, "message_timestamp": "2026-03-07T12:00:00Z"},
    )
    assert resp.status_code == 201
    return resp.json()


async def _dequeue(client, user_id: int) -> dict:
    """Dequeue next item and return the DequeueResponse dict."""
    resp = await client.delete(f"{QUEUE_PREFIX}/{user_id}/dequeue")
    assert resp.status_code == 200
    return resp.json()


async def _start(client, user_id: int, queue_item_id: str) -> dict:
    """Start a conversation and return the ConversationResponse dict."""
    resp = await client.post(
        f"{CONV_PREFIX}/{user_id}/start",
        json={"queue_item_id": queue_item_id},
    )
    assert resp.status_code == 200
    return resp.json()


async def _update_state(
    client, user_id: int, state: str, history_entry: dict | None = None
) -> dict:
    """Update conversation state and return the ConversationResponse dict."""
    body: dict = {"state": state}
    if history_entry is not None:
        body["history_entry"] = history_entry
    resp = await client.patch(
        f"{CONV_PREFIX}/{user_id}/state",
        json=body,
    )
    assert resp.status_code == 200
    return resp.json()


async def _get_active(client, user_id: int):
    """Get the active conversation (may return None in body)."""
    resp = await client.get(f"{CONV_PREFIX}/{user_id}/active")
    assert resp.status_code == 200
    return resp.json()


async def _queue_status(client, user_id: int) -> dict:
    resp = await client.get(f"{QUEUE_PREFIX}/{user_id}/status")
    assert resp.status_code == 200
    return resp.json()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestFullLifecycleSingleMessage:
    async def test_full_lifecycle_single_message(self, test_app, test_user):
        """Enqueue one message -> dequeue -> start -> complete -> verify clean."""
        uid = test_user

        # 1. Enqueue one message
        item = await _enqueue(test_app, uid, "buy milk")

        # 2. No active conversation yet
        active = await _get_active(test_app, uid)
        assert active is None

        # 3. Dequeue
        deq = await _dequeue(test_app, uid)
        assert deq["item"] is not None
        assert deq["item"]["id"] == item["id"]
        assert deq["item"]["content"] == "buy milk"

        # 4. Start conversation
        conv = await _start(test_app, uid, item["id"])
        assert conv["state"] == "processing"
        assert conv["queue_item_id"] == item["id"]

        # 5. Complete
        updated = await _update_state(test_app, uid, "completed")
        assert updated["state"] == "completed"

        # 6. Queue is empty, no active conversation
        st = await _queue_status(test_app, uid)
        assert st["queue_length"] == 0
        assert st["conversation_active"] is False

        active = await _get_active(test_app, uid)
        assert active is None


class TestFullLifecycleWithFollowup:
    async def test_full_lifecycle_with_followup(self, test_app, test_user):
        """Enqueue -> dequeue -> start -> follow-up -> user reply -> complete."""
        uid = test_user

        await _enqueue(test_app, uid, "remind me tomorrow")
        deq = await _dequeue(test_app, uid)
        await _start(test_app, uid, deq["item"]["id"])

        # LLM asks a follow-up question
        updated = await _update_state(
            test_app,
            uid,
            "awaiting_reply",
            history_entry={"role": "assistant", "content": "What time?"},
        )
        assert updated["state"] == "awaiting_reply"
        assert len(updated["history"]) == 1

        # User replies
        resp = await test_app.post(
            f"{CONV_PREFIX}/{uid}/reply",
            json={"content": "3pm"},
        )
        assert resp.status_code == 200
        replied = resp.json()
        assert replied["state"] == "processing"
        assert len(replied["history"]) == 2
        assert replied["history"][0]["role"] == "assistant"
        assert replied["history"][1]["role"] == "user"
        assert replied["history"][1]["content"] == "3pm"

        # Complete
        final = await _update_state(test_app, uid, "completed")
        assert final["state"] == "completed"


class TestQueuedMessagesDuringActiveConversation:
    async def test_queued_messages_during_active_conversation(
        self, test_app, test_user
    ):
        """Start a conversation, enqueue 2 more, complete first, dequeue next."""
        uid = test_user

        # Enqueue 3 messages total
        item1 = await _enqueue(test_app, uid, "first")
        item2 = await _enqueue(test_app, uid, "second")
        await _enqueue(test_app, uid, "third")

        # Dequeue and start conversation for first
        deq1 = await _dequeue(test_app, uid)
        assert deq1["item"]["id"] == item1["id"]
        await _start(test_app, uid, deq1["item"]["id"])

        # Queue should have 2 remaining items
        st = await _queue_status(test_app, uid)
        assert st["queue_length"] == 2
        assert st["conversation_active"] is True

        # Complete first conversation
        await _update_state(test_app, uid, "completed")

        # Dequeue next -- should be second message (FIFO)
        deq2 = await _dequeue(test_app, uid)
        assert deq2["item"] is not None
        assert deq2["item"]["id"] == item2["id"]
        assert deq2["item"]["content"] == "second"


class TestCancelPopsNextItem:
    async def test_cancel_pops_next_item(self, test_app, test_user):
        """Cancel with queued items returns next_item."""
        uid = test_user

        await _enqueue(test_app, uid, "first")
        item2 = await _enqueue(test_app, uid, "second")
        item3 = await _enqueue(test_app, uid, "third")

        # Dequeue and start first
        deq = await _dequeue(test_app, uid)
        await _start(test_app, uid, deq["item"]["id"])

        # Cancel -- should pop second item as next_item
        resp = await test_app.post(f"{CONV_PREFIX}/{uid}/cancel")
        assert resp.status_code == 200
        cancel_data = resp.json()
        assert cancel_data["state"] == "cancelled"
        assert cancel_data["next_item"] is not None
        assert cancel_data["next_item"]["id"] == item2["id"]

        # Dequeue should now return third item
        deq3 = await _dequeue(test_app, uid)
        assert deq3["item"] is not None
        assert deq3["item"]["id"] == item3["id"]


class TestReplyOnlyWorksWhenAwaiting:
    async def test_reply_only_works_when_awaiting(self, test_app, test_user):
        """Reply should fail with 409 unless state is awaiting_reply."""
        uid = test_user

        await _enqueue(test_app, uid, "test message")
        deq = await _dequeue(test_app, uid)
        await _start(test_app, uid, deq["item"]["id"])

        # State is "processing" -- reply should fail with 409
        resp = await test_app.post(
            f"{CONV_PREFIX}/{uid}/reply",
            json={"content": "my reply"},
        )
        assert resp.status_code == 409

        # Update to awaiting_reply
        await _update_state(
            test_app,
            uid,
            "awaiting_reply",
            history_entry={"role": "assistant", "content": "Need more info"},
        )

        # Now reply should succeed
        resp = await test_app.post(
            f"{CONV_PREFIX}/{uid}/reply",
            json={"content": "here is more info"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["state"] == "processing"
        assert len(data["history"]) == 2


class TestConversationExpiryDetection:
    async def test_conversation_expiry_detection(
        self, test_app, test_user, mock_redis
    ):
        """Simulate TTL expiry by deleting the Redis key."""
        uid = test_user

        # Enqueue two items
        await _enqueue(test_app, uid, "first")
        await _enqueue(test_app, uid, "second")

        # Dequeue and start first conversation
        deq = await _dequeue(test_app, uid)
        await _start(test_app, uid, deq["item"]["id"])

        # Verify conversation is active
        active = await _get_active(test_app, uid)
        assert active is not None

        # Simulate TTL expiry by deleting the key directly
        await mock_redis.delete(f"conversation:{uid}")

        # Active conversation should be gone
        active = await _get_active(test_app, uid)
        assert active is None

        # Queue items should still be there (item2 is still queued)
        st = await _queue_status(test_app, uid)
        assert st["queue_length"] == 1


class TestMultipleFollowupRounds:
    async def test_multiple_followup_rounds(self, test_app, test_user):
        """Two rounds of assistant question + user reply = 4 history entries."""
        uid = test_user

        await _enqueue(test_app, uid, "complex task")
        deq = await _dequeue(test_app, uid)
        await _start(test_app, uid, deq["item"]["id"])

        # Round 1: assistant asks, user replies
        await _update_state(
            test_app,
            uid,
            "awaiting_reply",
            history_entry={"role": "assistant", "content": "Question 1?"},
        )
        resp = await test_app.post(
            f"{CONV_PREFIX}/{uid}/reply",
            json={"content": "Answer 1"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["state"] == "processing"
        assert len(data["history"]) == 2

        # Round 2: assistant asks again, user replies again
        await _update_state(
            test_app,
            uid,
            "awaiting_reply",
            history_entry={"role": "assistant", "content": "Question 2?"},
        )
        resp = await test_app.post(
            f"{CONV_PREFIX}/{uid}/reply",
            json={"content": "Answer 2"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["state"] == "processing"
        assert len(data["history"]) == 4

        # Verify history content
        assert data["history"][0] == {"role": "assistant", "content": "Question 1?"}
        assert data["history"][1] == {"role": "user", "content": "Answer 1"}
        assert data["history"][2] == {"role": "assistant", "content": "Question 2?"}
        assert data["history"][3] == {"role": "user", "content": "Answer 2"}

        # Complete
        final = await _update_state(test_app, uid, "completed")
        assert final["state"] == "completed"
        assert len(final["history"]) == 4
