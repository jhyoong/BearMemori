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


async def test_create_event_without_memory(test_app, test_user):
    """POST /events with memory_id=null (email-sourced) returns pending event."""
    event_time = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    resp = await test_app.post(
        "/events",
        json={
            "owner_user_id": test_user,
            "event_time": event_time,
            "description": "email-sourced event",
            "source_type": "email",
            "memory_id": None,
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["status"] == "pending"
    assert data["memory_id"] is None
    assert data["id"] is not None


async def test_update_event_description(test_app, test_user):
    """PATCH /events/{id} updates the description."""
    event_data = await _create_event(test_app, test_user)
    event_id = event_data["id"]

    patch_resp = await test_app.patch(
        f"/events/{event_id}",
        json={"description": "updated description"},
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["description"] == "updated description"


async def test_update_event_time(test_app, test_user):
    """PATCH /events/{id} updates the event_time."""
    event_data = await _create_event(test_app, test_user)
    event_id = event_data["id"]

    new_time = (datetime.now(timezone.utc) + timedelta(days=14)).isoformat()
    patch_resp = await test_app.patch(
        f"/events/{event_id}",
        json={"event_time": new_time},
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["event_time"] is not None


async def test_confirm_event_without_memory_skips_reminder(test_app, test_user):
    """Confirming an event without memory_id does not create a reminder."""
    event_data = await _create_event(test_app, test_user, memory_id=None)
    event_id = event_data["id"]

    patch_resp = await test_app.patch(
        f"/events/{event_id}",
        json={"status": "confirmed"},
    )
    assert patch_resp.status_code == 200
    data = patch_resp.json()
    assert data["status"] == "confirmed"
    assert data["reminder_id"] is None


async def test_confirm_event_with_updated_fields(test_app, test_user):
    """PATCH with status=confirmed + event_time + description simultaneously."""
    memory_id = await _create_memory(test_app, test_user)
    event_data = await _create_event(test_app, test_user, memory_id=memory_id)
    event_id = event_data["id"]

    new_time = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    patch_resp = await test_app.patch(
        f"/events/{event_id}",
        json={
            "status": "confirmed",
            "event_time": new_time,
            "description": "confirmed with new details",
        },
    )
    assert patch_resp.status_code == 200
    data = patch_resp.json()
    assert data["status"] == "confirmed"
    assert data["description"] == "confirmed with new details"
    assert data["reminder_id"] is not None


async def test_double_confirm_no_duplicate_reminder(test_app, test_user):
    """Confirming an already-confirmed event does not create a second reminder."""
    memory_id = await _create_memory(test_app, test_user)
    event_data = await _create_event(test_app, test_user, memory_id=memory_id)
    event_id = event_data["id"]

    # First confirm
    first_resp = await test_app.patch(
        f"/events/{event_id}",
        json={"status": "confirmed"},
    )
    assert first_resp.status_code == 200
    first_reminder_id = first_resp.json()["reminder_id"]
    assert first_reminder_id is not None

    # Second confirm
    second_resp = await test_app.patch(
        f"/events/{event_id}",
        json={"status": "confirmed"},
    )
    assert second_resp.status_code == 200
    second_reminder_id = second_resp.json()["reminder_id"]
    assert second_reminder_id == first_reminder_id

    # Verify only 1 reminder exists for this user
    list_resp = await test_app.get("/reminders", params={"owner_user_id": test_user})
    assert len(list_resp.json()) == 1


async def test_filter_events_by_owner(test_app, test_user, test_db):
    """GET /events?owner_user_id=X returns only that user's events."""
    # Create a second user
    await test_db.execute(
        "INSERT INTO users (telegram_user_id, display_name, is_allowed) VALUES (?, ?, ?)",
        (99999, "Other User", 1),
    )
    await test_db.commit()

    # Create events for both users
    await _create_event(test_app, test_user)
    await _create_event(test_app, test_user)

    other_time = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    await test_app.post(
        "/events",
        json={
            "owner_user_id": 99999,
            "event_time": other_time,
            "description": "other user event",
            "source_type": "manual",
            "memory_id": None,
        },
    )

    resp = await test_app.get("/events", params={"owner_user_id": test_user})
    events = resp.json()
    assert len(events) >= 2
    for event in events:
        assert event["owner_user_id"] == test_user


async def test_filter_events_limit_offset(test_app, test_user):
    """GET /events with limit and offset paginates results."""
    # Create 3 events
    for _ in range(3):
        await _create_event(test_app, test_user)

    # Fetch with limit=2
    resp_page1 = await test_app.get(
        "/events",
        params={"owner_user_id": test_user, "limit": 2, "offset": 0},
    )
    page1 = resp_page1.json()
    assert len(page1) == 2

    # Fetch with offset=2
    resp_page2 = await test_app.get(
        "/events",
        params={"owner_user_id": test_user, "limit": 2, "offset": 2},
    )
    page2 = resp_page2.json()
    assert len(page2) >= 1

    # No overlap in IDs
    page1_ids = {e["id"] for e in page1}
    page2_ids = {e["id"] for e in page2}
    assert page1_ids.isdisjoint(page2_ids)


async def test_update_nonexistent_event_404(test_app, test_user):
    """PATCH /events/nonexistent returns 404."""
    resp = await test_app.patch(
        "/events/nonexistent-id-12345",
        json={"description": "does not matter"},
    )
    assert resp.status_code == 404
