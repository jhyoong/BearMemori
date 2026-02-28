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
    _past_data = await _create_reminder(test_app, memory_id, test_user, now + timedelta(hours=2))

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


async def test_create_reminder_with_recurrence(test_app, test_user):
    """POST a reminder with recurrence_minutes; verify it is returned."""
    memory_id = await _create_memory(test_app, test_user)
    fire_at = datetime.now(timezone.utc) + timedelta(days=1)

    resp = await test_app.post(
        "/reminders",
        json={
            "memory_id": memory_id,
            "owner_user_id": test_user,
            "text": "daily standup",
            "fire_at": fire_at.isoformat(),
            "recurrence_minutes": 1440,
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["recurrence_minutes"] == 1440
    assert data["text"] == "daily standup"
    assert data["fired"] is False


async def test_filter_reminders_by_owner(test_app, test_user, test_db):
    """GET /reminders?owner_user_id filters to a single user."""
    # Create a second user
    await test_db.execute(
        "INSERT INTO users (telegram_user_id, display_name, is_allowed) VALUES (?, ?, ?)",
        (99999, "Other User", 1),
    )
    await test_db.commit()

    memory_id = await _create_memory(test_app, test_user)

    # Create a memory owned by the other user
    other_resp = await test_app.post(
        "/memories",
        json={"owner_user_id": 99999, "content": "other user memory"},
    )
    other_memory_id = other_resp.json()["id"]

    now = datetime.now(timezone.utc)
    await _create_reminder(test_app, memory_id, test_user, now + timedelta(hours=1))
    await _create_reminder(test_app, memory_id, test_user, now + timedelta(hours=2))

    # Create a reminder for the other user
    await test_app.post(
        "/reminders",
        json={
            "memory_id": other_memory_id,
            "owner_user_id": 99999,
            "text": "other reminder",
            "fire_at": (now + timedelta(hours=3)).isoformat(),
        },
    )

    resp = await test_app.get("/reminders", params={"owner_user_id": test_user})
    assert resp.status_code == 200
    reminders = resp.json()
    assert len(reminders) == 2
    for r in reminders:
        assert r["owner_user_id"] == test_user


async def test_filter_reminders_by_fired(test_app, test_user, test_db):
    """GET /reminders?fired=true and fired=false return correct subsets."""
    memory_id = await _create_memory(test_app, test_user)
    now = datetime.now(timezone.utc)

    r1 = await _create_reminder(test_app, memory_id, test_user, now + timedelta(hours=1))
    r2 = await _create_reminder(test_app, memory_id, test_user, now + timedelta(hours=2))
    r3 = await _create_reminder(test_app, memory_id, test_user, now + timedelta(hours=3))

    # Mark r1 and r3 as fired directly in the DB
    await test_db.execute("UPDATE reminders SET fired = 1 WHERE id = ?", (r1["id"],))
    await test_db.execute("UPDATE reminders SET fired = 1 WHERE id = ?", (r3["id"],))
    await test_db.commit()

    # fired=true should return r1 and r3
    resp_fired = await test_app.get(
        "/reminders",
        params={"owner_user_id": test_user, "fired": "true"},
    )
    assert resp_fired.status_code == 200
    fired_ids = [r["id"] for r in resp_fired.json()]
    assert r1["id"] in fired_ids
    assert r3["id"] in fired_ids
    assert r2["id"] not in fired_ids

    # fired=false should return r2
    resp_unfired = await test_app.get(
        "/reminders",
        params={"owner_user_id": test_user, "fired": "false"},
    )
    assert resp_unfired.status_code == 200
    unfired_ids = [r["id"] for r in resp_unfired.json()]
    assert r2["id"] in unfired_ids
    assert r1["id"] not in unfired_ids
    assert r3["id"] not in unfired_ids


async def test_filter_reminders_combined(test_app, test_user, test_db):
    """GET /reminders with owner_user_id + upcoming_only combined."""
    # Create a second user
    await test_db.execute(
        "INSERT INTO users (telegram_user_id, display_name, is_allowed) VALUES (?, ?, ?)",
        (88888, "Another User", 1),
    )
    await test_db.commit()

    memory_id = await _create_memory(test_app, test_user)
    other_resp = await test_app.post(
        "/memories",
        json={"owner_user_id": 88888, "content": "another memory"},
    )
    other_memory_id = other_resp.json()["id"]

    now = datetime.now(timezone.utc)

    # test_user: future unfired (should appear)
    r1 = await _create_reminder(
        test_app, memory_id, test_user, now + timedelta(hours=1)
    )
    # test_user: past unfired (should NOT appear)
    await _create_reminder(
        test_app, memory_id, test_user, now - timedelta(hours=1)
    )
    # other user: future unfired (should NOT appear -- wrong owner)
    await test_app.post(
        "/reminders",
        json={
            "memory_id": other_memory_id,
            "owner_user_id": 88888,
            "text": "other user future",
            "fire_at": (now + timedelta(hours=2)).isoformat(),
        },
    )

    resp = await test_app.get(
        "/reminders",
        params={"owner_user_id": test_user, "upcoming_only": "true"},
    )
    assert resp.status_code == 200
    results = resp.json()
    ids = [r["id"] for r in results]
    assert r1["id"] in ids
    # All returned reminders belong to test_user and are in the future
    for r in results:
        assert r["owner_user_id"] == test_user
        assert r["fired"] is False


async def test_update_reminder_text_only(test_app, test_user):
    """PATCH /reminders/{id} with only the text field."""
    memory_id = await _create_memory(test_app, test_user)
    fire_at = datetime.now(timezone.utc) + timedelta(hours=2)

    create_data = await _create_reminder(test_app, memory_id, test_user, fire_at)
    reminder_id = create_data["id"]
    original_fire_at = create_data["fire_at"]

    patch_resp = await test_app.patch(
        f"/reminders/{reminder_id}",
        json={"text": "updated text only"},
    )
    assert patch_resp.status_code == 200
    data = patch_resp.json()
    assert data["text"] == "updated text only"
    # fire_at should remain unchanged
    assert data["fire_at"] == original_fire_at


async def test_update_reminder_recurrence(test_app, test_user):
    """PATCH /reminders/{id} with recurrence_minutes."""
    memory_id = await _create_memory(test_app, test_user)
    fire_at = datetime.now(timezone.utc) + timedelta(hours=2)

    create_data = await _create_reminder(test_app, memory_id, test_user, fire_at)
    reminder_id = create_data["id"]

    patch_resp = await test_app.patch(
        f"/reminders/{reminder_id}",
        json={"recurrence_minutes": 1440},
    )
    assert patch_resp.status_code == 200
    data = patch_resp.json()
    assert data["recurrence_minutes"] == 1440
    assert data["text"] == "reminder text"


async def test_update_reminder_multiple_fields(test_app, test_user):
    """PATCH /reminders/{id} with text + fire_at + recurrence_minutes."""
    memory_id = await _create_memory(test_app, test_user)
    fire_at = datetime.now(timezone.utc) + timedelta(hours=2)

    create_data = await _create_reminder(test_app, memory_id, test_user, fire_at)
    reminder_id = create_data["id"]

    new_fire_at = datetime.now(timezone.utc) + timedelta(days=1)
    patch_resp = await test_app.patch(
        f"/reminders/{reminder_id}",
        json={
            "text": "multi-update text",
            "fire_at": new_fire_at.isoformat(),
            "recurrence_minutes": 60,
        },
    )
    assert patch_resp.status_code == 200
    data = patch_resp.json()
    assert data["text"] == "multi-update text"
    assert data["recurrence_minutes"] == 60
    updated_fire_at = datetime.fromisoformat(data["fire_at"])
    diff = abs((updated_fire_at - new_fire_at).total_seconds())
    assert diff < 2


async def test_upcoming_only_edge_cases(test_app, test_user, test_db):
    """Four reminders covering all fired/future combinations; upcoming_only returns only future unfired."""
    memory_id = await _create_memory(test_app, test_user)
    now = datetime.now(timezone.utc)

    # Future unfired -- should be returned
    r_future_unfired = await _create_reminder(
        test_app, memory_id, test_user, now + timedelta(hours=1)
    )
    # Future fired -- should NOT be returned
    r_future_fired = await _create_reminder(
        test_app, memory_id, test_user, now + timedelta(hours=2)
    )
    # Past unfired -- should NOT be returned
    r_past_unfired = await _create_reminder(
        test_app, memory_id, test_user, now - timedelta(hours=1)
    )
    # Past fired -- should NOT be returned
    r_past_fired = await _create_reminder(
        test_app, memory_id, test_user, now - timedelta(hours=2)
    )

    # Mark the two "fired" reminders directly in the DB
    await test_db.execute(
        "UPDATE reminders SET fired = 1 WHERE id = ?", (r_future_fired["id"],)
    )
    await test_db.execute(
        "UPDATE reminders SET fired = 1 WHERE id = ?", (r_past_fired["id"],)
    )
    await test_db.commit()

    resp = await test_app.get(
        "/reminders",
        params={"owner_user_id": test_user, "upcoming_only": "true"},
    )
    assert resp.status_code == 200
    results = resp.json()
    ids = [r["id"] for r in results]

    assert r_future_unfired["id"] in ids
    assert r_future_fired["id"] not in ids
    assert r_past_unfired["id"] not in ids
    assert r_past_fired["id"] not in ids


async def test_update_nonexistent_reminder_404(test_app, test_user):
    """PATCH /reminders/nonexistent returns 404."""
    resp = await test_app.patch(
        "/reminders/nonexistent-id-does-not-exist",
        json={"text": "should fail"},
    )
    assert resp.status_code == 404
