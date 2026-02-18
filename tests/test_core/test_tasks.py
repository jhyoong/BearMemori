"""Tests for the tasks endpoints."""

from datetime import datetime, timezone, timedelta


async def _create_memory(client, user_id: int) -> str:
    """Helper to create a confirmed memory and return its ID."""
    resp = await client.post(
        "/memories",
        json={"owner_user_id": user_id, "content": "task memory"},
    )
    return resp.json()["id"]


async def test_create_task(test_app, test_user):
    """POST a task linked to a memory returns the created task."""
    memory_id = await _create_memory(test_app, test_user)

    resp = await test_app.post(
        "/tasks",
        json={
            "memory_id": memory_id,
            "owner_user_id": test_user,
            "description": "do the thing",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["description"] == "do the thing"
    assert data["state"] == "NOT_DONE"
    assert data["memory_id"] == memory_id


async def test_list_tasks(test_app, test_user):
    """Create multiple tasks then GET all; count matches."""
    memory_id = await _create_memory(test_app, test_user)

    for i in range(3):
        await test_app.post(
            "/tasks",
            json={
                "memory_id": memory_id,
                "owner_user_id": test_user,
                "description": f"task {i}",
            },
        )

    resp = await test_app.get("/tasks", params={"owner_user_id": test_user})
    assert resp.status_code == 200
    assert len(resp.json()) >= 3


async def test_list_tasks_filter_state(test_app, test_user):
    """Create NOT_DONE and DONE tasks; filter by state returns correct subset."""
    memory_id = await _create_memory(test_app, test_user)

    # Create a NOT_DONE task
    create_resp = await test_app.post(
        "/tasks",
        json={
            "memory_id": memory_id,
            "owner_user_id": test_user,
            "description": "pending task",
        },
    )
    pending_id = create_resp.json()["id"]

    # Create a task and mark it DONE
    done_resp = await test_app.post(
        "/tasks",
        json={
            "memory_id": memory_id,
            "owner_user_id": test_user,
            "description": "done task",
        },
    )
    done_id = done_resp.json()["id"]
    await test_app.patch(f"/tasks/{done_id}", json={"state": "DONE"})

    not_done_list = await test_app.get("/tasks", params={"state": "NOT_DONE"})
    done_list = await test_app.get("/tasks", params={"state": "DONE"})

    not_done_ids = [t["id"] for t in not_done_list.json()]
    done_ids = [t["id"] for t in done_list.json()]

    assert pending_id in not_done_ids
    assert done_id not in not_done_ids
    assert done_id in done_ids
    assert pending_id not in done_ids


async def test_mark_task_done(test_app, test_user):
    """PATCH state=DONE sets completed_at."""
    memory_id = await _create_memory(test_app, test_user)

    create_resp = await test_app.post(
        "/tasks",
        json={
            "memory_id": memory_id,
            "owner_user_id": test_user,
            "description": "complete me",
        },
    )
    task_id = create_resp.json()["id"]

    patch_resp = await test_app.patch(f"/tasks/{task_id}", json={"state": "DONE"})
    assert patch_resp.status_code == 200
    data = patch_resp.json()
    assert data["task"]["state"] == "DONE"
    assert data["task"]["completed_at"] is not None


async def test_recurring_task_creates_next(test_app, test_user):
    """Marking a recurring task DONE creates a new NOT_DONE task with due_at = original + recurrence."""
    memory_id = await _create_memory(test_app, test_user)
    original_due = datetime.now(timezone.utc) + timedelta(hours=1)

    create_resp = await test_app.post(
        "/tasks",
        json={
            "memory_id": memory_id,
            "owner_user_id": test_user,
            "description": "daily recurring",
            "due_at": original_due.isoformat(),
            "recurrence_minutes": 1440,
        },
    )
    task_id = create_resp.json()["id"]

    patch_resp = await test_app.patch(f"/tasks/{task_id}", json={"state": "DONE"})
    assert patch_resp.status_code == 200
    data = patch_resp.json()
    recurring_id = data["recurring_task_id"]
    assert recurring_id is not None

    all_tasks = await test_app.get("/tasks", params={"owner_user_id": test_user})
    tasks_by_id = {t["id"]: t for t in all_tasks.json()}
    assert recurring_id in tasks_by_id
    new_task = tasks_by_id[recurring_id]
    assert new_task["state"] == "NOT_DONE"

    new_due = datetime.fromisoformat(new_task["due_at"])
    expected_due = original_due + timedelta(minutes=1440)
    diff = abs((new_due - expected_due).total_seconds())
    assert diff < 5


async def test_recurring_task_drift_prevention(test_app, test_user):
    """Recurring task with past due_at: new due_at is based on old due_at, not now."""
    memory_id = await _create_memory(test_app, test_user)
    past_due = datetime.now(timezone.utc) - timedelta(hours=2)

    create_resp = await test_app.post(
        "/tasks",
        json={
            "memory_id": memory_id,
            "owner_user_id": test_user,
            "description": "past due recurring",
            "due_at": past_due.isoformat(),
            "recurrence_minutes": 60,
        },
    )
    task_id = create_resp.json()["id"]

    patch_resp = await test_app.patch(f"/tasks/{task_id}", json={"state": "DONE"})
    data = patch_resp.json()
    recurring_id = data["recurring_task_id"]

    all_tasks = await test_app.get("/tasks", params={"owner_user_id": test_user})
    tasks_by_id = {t["id"]: t for t in all_tasks.json()}
    new_task = tasks_by_id[recurring_id]

    new_due = datetime.fromisoformat(new_task["due_at"])
    expected_due = past_due + timedelta(minutes=60)
    diff = abs((new_due - expected_due).total_seconds())
    assert diff < 5


async def test_delete_task(test_app, test_user):
    """Create a task then DELETE it; subsequent GET returns empty list for that ID."""
    memory_id = await _create_memory(test_app, test_user)

    create_resp = await test_app.post(
        "/tasks",
        json={
            "memory_id": memory_id,
            "owner_user_id": test_user,
            "description": "delete me",
        },
    )
    task_id = create_resp.json()["id"]

    del_resp = await test_app.delete(f"/tasks/{task_id}")
    assert del_resp.status_code == 204

    all_tasks = await test_app.get("/tasks")
    task_ids = [t["id"] for t in all_tasks.json()]
    assert task_id not in task_ids


async def test_create_task_with_due_at(test_app, test_user):
    """POST a task with due_at set; verify it is returned in the response."""
    memory_id = await _create_memory(test_app, test_user)
    due_at = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()

    resp = await test_app.post(
        "/tasks",
        json={
            "memory_id": memory_id,
            "owner_user_id": test_user,
            "description": "task with deadline",
            "due_at": due_at,
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["due_at"] is not None
    returned_due = datetime.fromisoformat(data["due_at"])
    expected_due = datetime.fromisoformat(due_at)
    diff = abs((returned_due - expected_due).total_seconds())
    assert diff < 2


async def test_filter_tasks_by_owner(test_app, test_user, test_db):
    """GET /tasks?owner_user_id=X returns only tasks for that user."""
    memory_id = await _create_memory(test_app, test_user)

    # Create a second user and a memory for them
    await test_db.execute(
        "INSERT OR IGNORE INTO users (telegram_user_id, display_name, is_allowed) "
        "VALUES (?, ?, ?)",
        (999888, "otheruser", 1),
    )
    await test_db.commit()
    other_mem_resp = await test_app.post(
        "/memories",
        json={"owner_user_id": 999888, "content": "other user memory"},
    )
    other_memory_id = other_mem_resp.json()["id"]

    # Create tasks for each user
    await test_app.post(
        "/tasks",
        json={
            "memory_id": memory_id,
            "owner_user_id": test_user,
            "description": "user1 task",
        },
    )
    await test_app.post(
        "/tasks",
        json={
            "memory_id": other_memory_id,
            "owner_user_id": 999888,
            "description": "user2 task",
        },
    )

    resp = await test_app.get("/tasks", params={"owner_user_id": 999888})
    assert resp.status_code == 200
    tasks = resp.json()
    for t in tasks:
        assert t["owner_user_id"] == 999888


async def test_filter_tasks_due_before_after(test_app, test_user):
    """GET /tasks with due_before and due_after params filters correctly."""
    memory_id = await _create_memory(test_app, test_user)
    now = datetime.now(timezone.utc)

    # Task due in 1 day
    await test_app.post(
        "/tasks",
        json={
            "memory_id": memory_id,
            "owner_user_id": test_user,
            "description": "due soon",
            "due_at": (now + timedelta(days=1)).isoformat(),
        },
    )
    # Task due in 5 days
    await test_app.post(
        "/tasks",
        json={
            "memory_id": memory_id,
            "owner_user_id": test_user,
            "description": "due later",
            "due_at": (now + timedelta(days=5)).isoformat(),
        },
    )

    # due_before 3 days from now should include "due soon" but not "due later"
    cutoff = (now + timedelta(days=3)).isoformat()
    resp_before = await test_app.get("/tasks", params={"due_before": cutoff})
    assert resp_before.status_code == 200
    descs_before = [t["description"] for t in resp_before.json()]
    assert "due soon" in descs_before
    assert "due later" not in descs_before

    # due_after 3 days from now should include "due later" but not "due soon"
    resp_after = await test_app.get("/tasks", params={"due_after": cutoff})
    assert resp_after.status_code == 200
    descs_after = [t["description"] for t in resp_after.json()]
    assert "due later" in descs_after
    assert "due soon" not in descs_after


async def test_filter_tasks_limit_offset(test_app, test_user):
    """GET /tasks with limit and offset params pages results correctly."""
    memory_id = await _create_memory(test_app, test_user)

    # Create 5 tasks
    for i in range(5):
        await test_app.post(
            "/tasks",
            json={
                "memory_id": memory_id,
                "owner_user_id": test_user,
                "description": f"paged task {i}",
            },
        )

    # Fetch first 2
    resp1 = await test_app.get(
        "/tasks",
        params={"owner_user_id": test_user, "limit": 2, "offset": 0},
    )
    assert resp1.status_code == 200
    page1 = resp1.json()
    assert len(page1) == 2

    # Fetch next 2
    resp2 = await test_app.get(
        "/tasks",
        params={"owner_user_id": test_user, "limit": 2, "offset": 2},
    )
    assert resp2.status_code == 200
    page2 = resp2.json()
    assert len(page2) == 2

    # No overlap between pages
    ids1 = {t["id"] for t in page1}
    ids2 = {t["id"] for t in page2}
    assert ids1.isdisjoint(ids2)


async def test_update_task_description_and_due_at(test_app, test_user):
    """PATCH /tasks/{id} with description and due_at updates both without changing state."""
    memory_id = await _create_memory(test_app, test_user)

    create_resp = await test_app.post(
        "/tasks",
        json={
            "memory_id": memory_id,
            "owner_user_id": test_user,
            "description": "original desc",
        },
    )
    task_id = create_resp.json()["id"]

    new_due = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
    patch_resp = await test_app.patch(
        f"/tasks/{task_id}",
        json={"description": "updated desc", "due_at": new_due},
    )
    assert patch_resp.status_code == 200
    data = patch_resp.json()
    assert data["task"]["description"] == "updated desc"
    assert data["task"]["due_at"] is not None
    assert data["task"]["state"] == "NOT_DONE"
    assert data["recurring_task_id"] is None


async def test_complete_non_recurring_task(test_app, test_user):
    """PATCH state=DONE on a non-recurring task sets completed_at, recurring_task_id is None."""
    memory_id = await _create_memory(test_app, test_user)

    create_resp = await test_app.post(
        "/tasks",
        json={
            "memory_id": memory_id,
            "owner_user_id": test_user,
            "description": "one-time task",
        },
    )
    task_id = create_resp.json()["id"]

    patch_resp = await test_app.patch(f"/tasks/{task_id}", json={"state": "DONE"})
    assert patch_resp.status_code == 200
    data = patch_resp.json()
    assert data["task"]["state"] == "DONE"
    assert data["task"]["completed_at"] is not None
    assert data["recurring_task_id"] is None


async def test_recurring_task_without_due_at(test_app, test_user):
    """Create recurring task without due_at, mark DONE; new task gets due_at ~ now + recurrence."""
    memory_id = await _create_memory(test_app, test_user)

    create_resp = await test_app.post(
        "/tasks",
        json={
            "memory_id": memory_id,
            "owner_user_id": test_user,
            "description": "weekly review",
            "recurrence_minutes": 10080,
        },
    )
    task_id = create_resp.json()["id"]
    assert create_resp.json()["due_at"] is None

    before_done = datetime.now(timezone.utc)
    patch_resp = await test_app.patch(f"/tasks/{task_id}", json={"state": "DONE"})
    assert patch_resp.status_code == 200
    data = patch_resp.json()
    recurring_id = data["recurring_task_id"]
    assert recurring_id is not None

    # Fetch the new recurring task
    all_tasks = await test_app.get("/tasks", params={"owner_user_id": test_user})
    tasks_by_id = {t["id"]: t for t in all_tasks.json()}
    new_task = tasks_by_id[recurring_id]
    assert new_task["state"] == "NOT_DONE"
    assert new_task["due_at"] is not None

    new_due = datetime.fromisoformat(new_task["due_at"])
    expected_due = before_done + timedelta(minutes=10080)
    diff = abs((new_due - expected_due).total_seconds())
    assert diff < 10


async def test_already_done_task_no_duplicate_recurring(test_app, test_user):
    """Mark recurring task DONE, then update description; no second recurring task is created."""
    memory_id = await _create_memory(test_app, test_user)

    create_resp = await test_app.post(
        "/tasks",
        json={
            "memory_id": memory_id,
            "owner_user_id": test_user,
            "description": "recurring chore",
            "recurrence_minutes": 60,
        },
    )
    task_id = create_resp.json()["id"]

    # First DONE -> creates a recurring task
    patch1 = await test_app.patch(f"/tasks/{task_id}", json={"state": "DONE"})
    assert patch1.json()["recurring_task_id"] is not None

    # Second update (description only) on already-DONE task -> no new recurring task
    patch2 = await test_app.patch(
        f"/tasks/{task_id}", json={"description": "updated chore"}
    )
    assert patch2.status_code == 200
    assert patch2.json()["recurring_task_id"] is None

    # Verify only 2 tasks total (original + 1 recurring, not 3)
    all_tasks = await test_app.get("/tasks", params={"owner_user_id": test_user})
    task_ids = [t["id"] for t in all_tasks.json()]
    # Should have the original task + exactly one recurring task
    assert task_id in task_ids
    assert len([tid for tid in task_ids if tid != task_id]) >= 1
    # Count tasks with same description pattern to confirm no duplicates
    recurring_tasks = [
        t for t in all_tasks.json()
        if t["id"] != task_id and t["recurrence_minutes"] == 60
    ]
    assert len(recurring_tasks) == 1


async def test_update_nonexistent_task_404(test_app, test_user):
    """PATCH /tasks/nonexistent returns 404."""
    resp = await test_app.patch(
        "/tasks/nonexistent-id-12345",
        json={"description": "does not matter"},
    )
    assert resp.status_code == 404
