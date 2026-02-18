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
