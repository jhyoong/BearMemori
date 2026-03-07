"""Tests for queue and conversation routers."""


import pytest


pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Queue endpoint tests
# ---------------------------------------------------------------------------


class TestEnqueue:
    """Tests for POST /queue/{user_id}/enqueue."""

    async def test_enqueue_text(self, test_app, test_user):
        resp = await test_app.post(
            f"/queue/{test_user}/enqueue",
            json={
                "content": "hello",
                "message_timestamp": "2026-03-06T12:00:00Z",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["content"] == "hello"
        assert data["memory_id"] is None
        assert data["image_local_path"] is None
        assert "id" in data
        assert "created_at" in data

    async def test_enqueue_image(self, test_app, test_user):
        resp = await test_app.post(
            f"/queue/{test_user}/enqueue",
            json={
                "memory_id": "mem-abc",
                "image_local_path": "/data/images/abc.jpg",
                "message_timestamp": "2026-03-06T12:00:00Z",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["memory_id"] == "mem-abc"
        assert data["image_local_path"] == "/data/images/abc.jpg"
        assert data["content"] is None

    async def test_enqueue_multiple_fifo(self, test_app, test_user):
        """Multiple enqueues maintain FIFO order."""
        for i in range(3):
            await test_app.post(
                f"/queue/{test_user}/enqueue",
                json={
                    "content": f"msg-{i}",
                    "message_timestamp": "2026-03-06T12:00:00Z",
                },
            )
        # Peek should return the first one
        resp = await test_app.get(f"/queue/{test_user}/next")
        assert resp.status_code == 200
        assert resp.json()["content"] == "msg-0"


class TestDequeue:
    """Tests for DELETE /queue/{user_id}/dequeue."""

    async def test_dequeue_returns_first(self, test_app, test_user):
        await test_app.post(
            f"/queue/{test_user}/enqueue",
            json={
                "content": "first",
                "message_timestamp": "2026-03-06T12:00:00Z",
            },
        )
        await test_app.post(
            f"/queue/{test_user}/enqueue",
            json={
                "content": "second",
                "message_timestamp": "2026-03-06T12:00:00Z",
            },
        )
        resp = await test_app.delete(f"/queue/{test_user}/dequeue")
        assert resp.status_code == 200
        data = resp.json()
        assert data["item"]["content"] == "first"

    async def test_dequeue_empty_returns_null(
        self, test_app, test_user
    ):
        resp = await test_app.delete(f"/queue/{test_user}/dequeue")
        assert resp.status_code == 200
        data = resp.json()
        assert data["item"] is None


class TestPeek:
    """Tests for GET /queue/{user_id}/next."""

    async def test_peek_does_not_remove(self, test_app, test_user):
        await test_app.post(
            f"/queue/{test_user}/enqueue",
            json={
                "content": "peek-me",
                "message_timestamp": "2026-03-06T12:00:00Z",
            },
        )
        # Peek twice — both should return the same item
        r1 = await test_app.get(f"/queue/{test_user}/next")
        r2 = await test_app.get(f"/queue/{test_user}/next")
        assert r1.json()["id"] == r2.json()["id"]

    async def test_peek_empty_returns_null(
        self, test_app, test_user
    ):
        resp = await test_app.get(f"/queue/{test_user}/next")
        assert resp.status_code == 200
        assert resp.json() is None


class TestQueueStatus:
    """Tests for GET /queue/{user_id}/status."""

    async def test_status_shows_length(self, test_app, test_user):
        for i in range(2):
            await test_app.post(
                f"/queue/{test_user}/enqueue",
                json={
                    "content": f"msg-{i}",
                    "message_timestamp": "2026-03-06T12:00:00Z",
                },
            )
        resp = await test_app.get(f"/queue/{test_user}/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["queue_length"] == 2
        assert data["conversation_active"] is False
        assert data["conversation_state"] is None

    async def test_status_with_active_conversation(
        self, test_app, test_user
    ):
        # Enqueue and start a conversation
        enq = await test_app.post(
            f"/queue/{test_user}/enqueue",
            json={
                "content": "test",
                "message_timestamp": "2026-03-06T12:00:00Z",
            },
        )
        item_id = enq.json()["id"]
        await test_app.post(
            f"/conversations/{test_user}/start",
            json={"queue_item_id": item_id},
        )
        resp = await test_app.get(f"/queue/{test_user}/status")
        data = resp.json()
        assert data["conversation_active"] is True
        assert data["conversation_state"] == "processing"


# ---------------------------------------------------------------------------
# Conversation endpoint tests
# ---------------------------------------------------------------------------


class TestStartConversation:
    """Tests for POST /conversations/{user_id}/start."""

    async def test_start_conversation(self, test_app, test_user):
        resp = await test_app.post(
            f"/conversations/{test_user}/start",
            json={"queue_item_id": "item-123"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["state"] == "processing"
        assert data["queue_item_id"] == "item-123"
        assert data["user_id"] == test_user
        assert data["history"] == []
        assert "id" in data
        assert "created_at" in data
        assert "updated_at" in data


class TestGetActiveConversation:
    """Tests for GET /conversations/{user_id}/active."""

    async def test_get_active_exists(self, test_app, test_user):
        await test_app.post(
            f"/conversations/{test_user}/start",
            json={"queue_item_id": "item-abc"},
        )
        resp = await test_app.get(
            f"/conversations/{test_user}/active"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["state"] == "processing"
        assert data["queue_item_id"] == "item-abc"

    async def test_get_active_not_exists(
        self, test_app, test_user
    ):
        resp = await test_app.get(
            f"/conversations/{test_user}/active"
        )
        assert resp.status_code == 200
        assert resp.json() is None

    async def test_get_active_returns_none_when_completed(
        self, test_app, test_user
    ):
        await test_app.post(
            f"/conversations/{test_user}/start",
            json={"queue_item_id": "item-done"},
        )
        await test_app.patch(
            f"/conversations/{test_user}/state",
            json={"state": "completed"},
        )
        resp = await test_app.get(
            f"/conversations/{test_user}/active"
        )
        assert resp.status_code == 200
        assert resp.json() is None


class TestUpdateState:
    """Tests for PATCH /conversations/{user_id}/state."""

    async def test_update_to_awaiting_reply(
        self, test_app, test_user
    ):
        await test_app.post(
            f"/conversations/{test_user}/start",
            json={"queue_item_id": "item-1"},
        )
        resp = await test_app.patch(
            f"/conversations/{test_user}/state",
            json={
                "state": "awaiting_reply",
                "history_entry": {
                    "role": "assistant",
                    "content": "What do you mean?",
                },
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["state"] == "awaiting_reply"
        assert len(data["history"]) == 1
        assert data["history"][0]["role"] == "assistant"

    async def test_update_to_completed(self, test_app, test_user):
        await test_app.post(
            f"/conversations/{test_user}/start",
            json={"queue_item_id": "item-2"},
        )
        resp = await test_app.patch(
            f"/conversations/{test_user}/state",
            json={"state": "completed"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["state"] == "completed"

    async def test_update_no_conversation_404(
        self, test_app, test_user
    ):
        resp = await test_app.patch(
            f"/conversations/{test_user}/state",
            json={"state": "processing"},
        )
        assert resp.status_code == 404


class TestReply:
    """Tests for POST /conversations/{user_id}/reply."""

    async def test_reply_to_conversation(
        self, test_app, test_user
    ):
        await test_app.post(
            f"/conversations/{test_user}/start",
            json={"queue_item_id": "item-r"},
        )
        # Set state to awaiting_reply
        await test_app.patch(
            f"/conversations/{test_user}/state",
            json={"state": "awaiting_reply"},
        )
        resp = await test_app.post(
            f"/conversations/{test_user}/reply",
            json={"content": "My reply"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["state"] == "processing"
        assert any(
            e.get("content") == "My reply"
            for e in data["history"]
        )

    async def test_reply_fails_when_not_awaiting(
        self, test_app, test_user
    ):
        await test_app.post(
            f"/conversations/{test_user}/start",
            json={"queue_item_id": "item-nope"},
        )
        resp = await test_app.post(
            f"/conversations/{test_user}/reply",
            json={"content": "nope"},
        )
        assert resp.status_code == 409


class TestCancel:
    """Tests for POST /conversations/{user_id}/cancel."""

    async def test_cancel_conversation(self, test_app, test_user):
        await test_app.post(
            f"/conversations/{test_user}/start",
            json={"queue_item_id": "item-cancel"},
        )
        resp = await test_app.post(
            f"/conversations/{test_user}/cancel"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["state"] == "cancelled"
        assert data["next_item"] is None

    async def test_cancel_returns_next_queued_item(
        self, test_app, test_user
    ):
        # Enqueue an item first
        await test_app.post(
            f"/queue/{test_user}/enqueue",
            json={
                "content": "waiting",
                "message_timestamp": "2026-03-06T12:00:00Z",
            },
        )
        # Start a conversation for a different item
        await test_app.post(
            f"/conversations/{test_user}/start",
            json={"queue_item_id": "item-other"},
        )
        # Cancel — should pop the queued item
        resp = await test_app.post(
            f"/conversations/{test_user}/cancel"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["state"] == "cancelled"
        assert data["next_item"] is not None
        assert data["next_item"]["content"] == "waiting"


class TestImageFields:
    """Tests for image-related fields on queue items."""

    async def test_enqueue_dequeue_image_item(self, test_app, test_user):
        """Enqueue an image item with memory_id and image_local_path, then dequeue it."""
        resp = await test_app.post(
            f"/queue/{test_user}/enqueue",
            json={
                "content": "sunset photo",
                "memory_id": "mem-123",
                "image_local_path": "/data/images/abc.jpg",
                "message_timestamp": "2026-03-07T10:00:00Z",
            },
        )
        assert resp.status_code == 201
        item = resp.json()
        assert item["memory_id"] == "mem-123"
        assert item["image_local_path"] == "/data/images/abc.jpg"
        assert item["content"] == "sunset photo"

        resp = await test_app.delete(f"/queue/{test_user}/dequeue")
        assert resp.status_code == 200
        data = resp.json()
        dequeued = data["item"]
        assert dequeued["memory_id"] == "mem-123"
        assert dequeued["image_local_path"] == "/data/images/abc.jpg"
        assert dequeued["content"] == "sunset photo"

    async def test_enqueue_text_item_has_null_image_fields(self, test_app, test_user):
        """Text items have null memory_id and image_local_path."""
        resp = await test_app.post(
            f"/queue/{test_user}/enqueue",
            json={
                "content": "remind me to buy milk",
                "message_timestamp": "2026-03-07T10:00:00Z",
            },
        )
        assert resp.status_code == 201
        item = resp.json()
        assert item["memory_id"] is None
        assert item["image_local_path"] is None
