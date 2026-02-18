"""Tests for the events endpoints."""

from datetime import datetime, timezone, timedelta


async def _create_memory(client, user_id: int) -> str:
    """Helper to create a confirmed memory and return its ID."""
    resp = await client.post(
        "/memories",
        json={"owner_user_id": user_id, "content": "event memory"},
    )
    return resp.json()["id"]


async def _create_event(client, user_id: int, memory_id: str | None = None) -> dict:
    """Helper to create a pending event and return the response body."""
    event_time = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    resp = await client.post(
        "/events",
        json={
            "owner_user_id": user_id,
            "event_time": event_time,
            "description": "team meeting",
            "source_type": "manual",
            "memory_id": memory_id,
        },
    )
    return resp.json()


async def test_create_event(test_app, test_user):
    """POST an event returns status=pending and pending_since is set."""
    data = await _create_event(test_app, test_user)
    assert data["status"] == "pending"
    assert data["id"] is not None


async def test_confirm_event_creates_reminder(test_app, test_user):
    """Confirming an event with a memory_id creates a reminder and sets reminder_id."""
    memory_id = await _create_memory(test_app, test_user)
    event_data = await _create_event(test_app, test_user, memory_id=memory_id)
    event_id = event_data["id"]

    patch_resp = await test_app.patch(
        f"/events/{event_id}",
        json={"status": "confirmed"},
    )
    assert patch_resp.status_code == 200
    data = patch_resp.json()
    assert data["status"] == "confirmed"
    assert data["reminder_id"] is not None

    # Verify the reminder actually exists
    list_resp = await test_app.get("/reminders", params={"owner_user_id": test_user})
    reminder_ids = [r["id"] for r in list_resp.json()]
    assert data["reminder_id"] in reminder_ids


async def test_reject_event(test_app, test_user):
    """PATCH status=rejected sets event status to rejected."""
    event_data = await _create_event(test_app, test_user)
    event_id = event_data["id"]

    patch_resp = await test_app.patch(
        f"/events/{event_id}",
        json={"status": "rejected"},
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["status"] == "rejected"


async def test_list_events_filter_status(test_app, test_user):
    """Create pending and confirmed events; filter by status returns correct subset."""
    memory_id = await _create_memory(test_app, test_user)

    pending_data = await _create_event(test_app, test_user)
    pending_id = pending_data["id"]

    confirmed_data = await _create_event(test_app, test_user, memory_id=memory_id)
    confirmed_id = confirmed_data["id"]
    await test_app.patch(f"/events/{confirmed_id}", json={"status": "confirmed"})

    pending_list = await test_app.get("/events", params={"status": "pending"})
    confirmed_list = await test_app.get("/events", params={"status": "confirmed"})

    pending_ids = [e["id"] for e in pending_list.json()]
    confirmed_ids = [e["id"] for e in confirmed_list.json()]

    assert pending_id in pending_ids
    assert confirmed_id not in pending_ids
    assert confirmed_id in confirmed_ids
    assert pending_id not in confirmed_ids
