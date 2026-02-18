"""Tests for the audit log endpoints."""


async def _create_memory(client, user_id: int, content: str = "audit memory") -> str:
    """Helper to create a confirmed memory and return its ID."""
    resp = await client.post(
        "/memories",
        json={"owner_user_id": user_id, "content": content},
    )
    return resp.json()["id"]


async def test_audit_entries_created(test_app, test_user):
    """Create a memory; GET /audit?entity_type=memory returns an entry for it."""
    memory_id = await _create_memory(test_app, test_user)

    resp = await test_app.get("/audit", params={"entity_type": "memory"})
    assert resp.status_code == 200
    entries = resp.json()
    entity_ids = [e["entity_id"] for e in entries]
    assert memory_id in entity_ids


async def test_audit_filter_by_entity_id(test_app, test_user):
    """Create two memories; filtering audit by entity_id returns only that one."""
    memory_id_a = await _create_memory(test_app, test_user, "first memory")
    memory_id_b = await _create_memory(test_app, test_user, "second memory")

    resp = await test_app.get(
        "/audit",
        params={"entity_type": "memory", "entity_id": memory_id_a},
    )
    assert resp.status_code == 200
    entries = resp.json()
    assert all(e["entity_id"] == memory_id_a for e in entries)
    entity_ids = [e["entity_id"] for e in entries]
    assert memory_id_b not in entity_ids


async def test_audit_detail_field(test_app, test_user):
    """Update a memory; audit entry with detail is returned as a parsed dict."""
    memory_id = await _create_memory(test_app, test_user)

    await test_app.patch(
        f"/memories/{memory_id}",
        json={"is_pinned": True},
    )

    resp = await test_app.get(
        "/audit",
        params={"entity_type": "memory", "entity_id": memory_id, "action": "updated"},
    )
    assert resp.status_code == 200
    entries = resp.json()
    assert len(entries) > 0

    entry_with_detail = next((e for e in entries if e["detail"] is not None), None)
    assert entry_with_detail is not None
    assert isinstance(entry_with_detail["detail"], dict)


async def test_audit_filter_by_action(test_app, test_user):
    """Create a memory and update it; filter audit by action=created and action=updated."""
    memory_id = await _create_memory(test_app, test_user)

    await test_app.patch(
        f"/memories/{memory_id}",
        json={"is_pinned": True},
    )

    resp_created = await test_app.get("/audit", params={"action": "created"})
    assert resp_created.status_code == 200
    created_entries = resp_created.json()
    assert all(e["action"] == "created" for e in created_entries)
    created_entity_ids = [e["entity_id"] for e in created_entries]
    assert memory_id in created_entity_ids

    resp_updated = await test_app.get("/audit", params={"action": "updated"})
    assert resp_updated.status_code == 200
    updated_entries = resp_updated.json()
    assert all(e["action"] == "updated" for e in updated_entries)
    updated_entity_ids = [e["entity_id"] for e in updated_entries]
    assert memory_id in updated_entity_ids


async def test_audit_filter_by_entity_type(test_app, test_user):
    """Create memories and tasks; filter audit by entity_type returns correct entries."""
    memory_id = await _create_memory(test_app, test_user, "entity type test memory")

    await test_app.post(
        "/tasks",
        json={
            "memory_id": memory_id,
            "owner_user_id": test_user,
            "description": "entity type test task",
        },
    )

    resp_memory = await test_app.get("/audit", params={"entity_type": "memory"})
    assert resp_memory.status_code == 200
    memory_entries = resp_memory.json()
    assert len(memory_entries) > 0
    assert all(e["entity_type"] == "memory" for e in memory_entries)

    resp_task = await test_app.get("/audit", params={"entity_type": "task"})
    assert resp_task.status_code == 200
    task_entries = resp_task.json()
    assert len(task_entries) > 0
    assert all(e["entity_type"] == "task" for e in task_entries)

    memory_entity_ids = {e["entity_id"] for e in memory_entries}
    task_entity_ids = {e["entity_id"] for e in task_entries}
    assert memory_entity_ids.isdisjoint(task_entity_ids)


async def test_audit_combined_filters(test_app, test_user):
    """GET /audit with entity_type + action + entity_id together returns correct entries."""
    memory_id = await _create_memory(test_app, test_user, "combined filter memory")

    await test_app.patch(
        f"/memories/{memory_id}",
        json={"is_pinned": True},
    )

    resp = await test_app.get(
        "/audit",
        params={
            "entity_type": "memory",
            "action": "updated",
            "entity_id": memory_id,
        },
    )
    assert resp.status_code == 200
    entries = resp.json()
    assert len(entries) > 0
    for entry in entries:
        assert entry["entity_type"] == "memory"
        assert entry["action"] == "updated"
        assert entry["entity_id"] == memory_id


async def test_audit_pagination(test_app, test_user):
    """Create several audit entries and verify limit and offset work correctly."""
    ids = []
    for i in range(5):
        mid = await _create_memory(test_app, test_user, f"pagination memory {i}")
        ids.append(mid)

    resp_page1 = await test_app.get("/audit", params={"limit": 2, "offset": 0})
    assert resp_page1.status_code == 200
    page1 = resp_page1.json()
    assert len(page1) == 2

    resp_page2 = await test_app.get("/audit", params={"limit": 2, "offset": 2})
    assert resp_page2.status_code == 200
    page2 = resp_page2.json()
    assert len(page2) == 2

    page1_ids = {e["id"] for e in page1}
    page2_ids = {e["id"] for e in page2}
    assert page1_ids.isdisjoint(page2_ids)


async def test_audit_default_limit(test_app, test_user):
    """GET /audit without limit returns entries (default limit is 100)."""
    await _create_memory(test_app, test_user, "default limit memory")

    resp = await test_app.get("/audit")
    assert resp.status_code == 200
    entries = resp.json()
    assert len(entries) > 0
    assert len(entries) <= 100


async def test_audit_actor_field(test_app, test_user):
    """Create a memory and verify the audit entry has the correct user_id field."""
    memory_id = await _create_memory(test_app, test_user, "actor field memory")

    resp = await test_app.get(
        "/audit",
        params={"entity_type": "memory", "entity_id": memory_id, "action": "created"},
    )
    assert resp.status_code == 200
    entries = resp.json()
    assert len(entries) == 1
    assert entries[0]["user_id"] == test_user
