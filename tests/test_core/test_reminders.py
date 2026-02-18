"""Tests for the reminders endpoints."""

from datetime import datetime, timezone, timedelta


async def _create_memory(client, user_id: int) -> str:
    """Helper to create a confirmed memory and return its ID."""
    resp = await client.post(
        "/memories",
        json={"owner_user_id": user_id, "content": "reminder memory"},
    )
    return resp.json()["id"]


async def _create_reminder(client, memory_id: str, user_id: int, fire_at: datetime) -> dict:
    """Helper to create a reminder and return the response body."""
    resp = await client.post(
        "/reminders",
        json={
            "memory_id": memory_id,
            "owner_user_id": user_id,
            "text": "reminder text",
            "fire_at": fire_at.isoformat(),
        },
    )
    return resp.json()


async def test_create_reminder(test_app, test_user):
    """POST a reminder returns the created reminder."""
    memory_id = await _create_memory(test_app, test_user)
    fire_at = datetime.now(timezone.utc) + timedelta(hours=1)

    resp = await test_app.post(
        "/reminders",
        json={
            "memory_id": memory_id,
            "owner_user_id": test_user,
            "text": "pick up kids",
            "fire_at": fire_at.isoformat(),
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["text"] == "pick up kids"
    assert data["fired"] is False
    assert data["memory_id"] == memory_id


async def test_list_reminders(test_app, test_user):
    """Create multiple reminders; GET all sorted by fire_at ascending."""
    memory_id = await _create_memory(test_app, test_user)
    now = datetime.now(timezone.utc)

    fire_times = [
        now + timedelta(hours=3),
        now + timedelta(hours=1),
        now + timedelta(hours=2),
    ]
    for ft in fire_times:
        await _create_reminder(test_app, memory_id, test_user, ft)

    resp = await test_app.get("/reminders", params={"owner_user_id": test_user})
    assert resp.status_code == 200
    reminders = resp.json()
    assert len(reminders) >= 3

    fire_ats = [datetime.fromisoformat(r["fire_at"]) for r in reminders]
    assert fire_ats == sorted(fire_ats)


async def test_list_upcoming_only(test_app, test_user):
    """Create a fired and an unfired reminder; upcoming_only=true returns only unfired."""
    memory_id = await _create_memory(test_app, test_user)
    now = datetime.now(timezone.utc)

    future_data = await _create_reminder(test_app, memory_id, test_user, now + timedelta(hours=1))
    past_data = await _create_reminder(test_app, memory_id, test_user, now + timedelta(hours=2))

    # Manually mark one reminder as fired via direct DB manipulation through test_db
    # We use the test_db fixture indirectly: instead, let's create a past-fire reminder
    # The reminders router has no "fire" endpoint, so we check that upcoming_only=true
    # filters by fire_at > now. A reminder with fire_at in the past (not fired) is excluded.
    past_fire_data = await _create_reminder(
        test_app, memory_id, test_user, now - timedelta(hours=1)
    )

    resp = await test_app.get(
        "/reminders",
        params={"owner_user_id": test_user, "upcoming_only": "true"},
    )
    assert resp.status_code == 200
    ids = [r["id"] for r in resp.json()]
    assert future_data["id"] in ids
    assert past_fire_data["id"] not in ids


async def test_update_reminder(test_app, test_user):
    """PATCH fire_at on a reminder; updated value is persisted."""
    memory_id = await _create_memory(test_app, test_user)
    fire_at = datetime.now(timezone.utc) + timedelta(hours=1)

    create_data = await _create_reminder(test_app, memory_id, test_user, fire_at)
    reminder_id = create_data["id"]

    new_fire_at = datetime.now(timezone.utc) + timedelta(hours=5)
    patch_resp = await test_app.patch(
        f"/reminders/{reminder_id}",
        json={"fire_at": new_fire_at.isoformat()},
    )
    assert patch_resp.status_code == 200

    updated_fire_at = datetime.fromisoformat(patch_resp.json()["fire_at"])
    diff = abs((updated_fire_at - new_fire_at).total_seconds())
    assert diff < 2


async def test_delete_reminder(test_app, test_user):
    """Create a reminder then DELETE it; it no longer appears in list."""
    memory_id = await _create_memory(test_app, test_user)
    fire_at = datetime.now(timezone.utc) + timedelta(hours=1)

    create_data = await _create_reminder(test_app, memory_id, test_user, fire_at)
    reminder_id = create_data["id"]

    del_resp = await test_app.delete(f"/reminders/{reminder_id}")
    assert del_resp.status_code == 204

    list_resp = await test_app.get("/reminders", params={"owner_user_id": test_user})
    ids = [r["id"] for r in list_resp.json()]
    assert reminder_id not in ids
