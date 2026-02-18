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
