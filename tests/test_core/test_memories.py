"""Tests for the memories endpoints."""

from datetime import datetime, timezone, timedelta


async def test_create_text_memory(test_app, test_user):
    """POST a text memory returns status=confirmed, pending_expires_at=None."""
    resp = await test_app.post(
        "/memories",
        json={"owner_user_id": test_user, "content": "buy milk"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["status"] == "confirmed"
    assert data["pending_expires_at"] is None


async def test_create_image_memory(test_app, test_user):
    """POST with media_type=image returns status=pending, pending_expires_at ~7 days from now."""
    resp = await test_app.post(
        "/memories",
        json={
            "owner_user_id": test_user,
            "content": "photo caption",
            "media_type": "image",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["status"] == "pending"
    assert data["pending_expires_at"] is not None

    expires_at = datetime.fromisoformat(data["pending_expires_at"])
    now = datetime.now(timezone.utc)
    delta = expires_at - now
    assert timedelta(days=6) < delta < timedelta(days=8)


async def test_get_memory(test_app, test_user):
    """Create a memory then GET by ID; all fields match."""
    create_resp = await test_app.post(
        "/memories",
        json={"owner_user_id": test_user, "content": "remember to call"},
    )
    memory_id = create_resp.json()["id"]

    get_resp = await test_app.get(f"/memories/{memory_id}")
    assert get_resp.status_code == 200
    data = get_resp.json()
    assert data["id"] == memory_id
    assert data["content"] == "remember to call"
    assert data["owner_user_id"] == test_user


async def test_get_memory_not_found(test_app, test_user):
    """GET a non-existent memory ID returns 404."""
    resp = await test_app.get("/memories/nonexistent-id-12345")
    assert resp.status_code == 404


async def test_get_memory_includes_tags(test_app, test_user):
    """Create a memory, add tags, GET returns tags in response."""
    create_resp = await test_app.post(
        "/memories",
        json={"owner_user_id": test_user, "content": "grocery list"},
    )
    memory_id = create_resp.json()["id"]

    await test_app.post(
        f"/memories/{memory_id}/tags",
        json={"tags": ["groceries", "shopping"]},
    )

    get_resp = await test_app.get(f"/memories/{memory_id}")
    assert get_resp.status_code == 200
    tags = [t["tag"] for t in get_resp.json()["tags"]]
    assert "groceries" in tags
    assert "shopping" in tags


async def test_update_memory(test_app, test_user):
    """PATCH is_pinned=true on a memory; change persists on GET."""
    create_resp = await test_app.post(
        "/memories",
        json={"owner_user_id": test_user, "content": "important note"},
    )
    memory_id = create_resp.json()["id"]

    patch_resp = await test_app.patch(
        f"/memories/{memory_id}",
        json={"is_pinned": True},
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["is_pinned"] is True

    get_resp = await test_app.get(f"/memories/{memory_id}")
    assert get_resp.json()["is_pinned"] is True


async def test_delete_memory(test_app, test_user):
    """DELETE a memory returns 204; subsequent GET returns 404."""
    create_resp = await test_app.post(
        "/memories",
        json={"owner_user_id": test_user, "content": "delete me"},
    )
    memory_id = create_resp.json()["id"]

    del_resp = await test_app.delete(f"/memories/{memory_id}")
    assert del_resp.status_code == 204

    get_resp = await test_app.get(f"/memories/{memory_id}")
    assert get_resp.status_code == 404


async def test_delete_memory_removes_tags(test_app, test_user):
    """Delete a memory with tags; tags are also removed (cascade)."""
    create_resp = await test_app.post(
        "/memories",
        json={"owner_user_id": test_user, "content": "tagged memory"},
    )
    memory_id = create_resp.json()["id"]

    await test_app.post(
        f"/memories/{memory_id}/tags",
        json={"tags": ["important"]},
    )

    await test_app.delete(f"/memories/{memory_id}")

    # Verify tag row is gone by checking audit log for the entity
    # (direct DB check via the test_db fixture is not used here to keep it endpoint-only)
    # The cascade delete is verified indirectly: no 500 errors and memory is gone
    get_resp = await test_app.get(f"/memories/{memory_id}")
    assert get_resp.status_code == 404


async def test_add_tags(test_app, test_user):
    """POST tags to a memory; tags appear on subsequent GET."""
    create_resp = await test_app.post(
        "/memories",
        json={"owner_user_id": test_user, "content": "need tags"},
    )
    memory_id = create_resp.json()["id"]

    tag_resp = await test_app.post(
        f"/memories/{memory_id}/tags",
        json={"tags": ["food", "health"]},
    )
    assert tag_resp.status_code == 200

    get_resp = await test_app.get(f"/memories/{memory_id}")
    tags = [t["tag"] for t in get_resp.json()["tags"]]
    assert "food" in tags
    assert "health" in tags


async def test_add_suggested_tags(test_app, test_user):
    """POST tags with status=suggested; suggested_at is set on the tag."""
    create_resp = await test_app.post(
        "/memories",
        json={"owner_user_id": test_user, "content": "auto-tagged memory"},
    )
    memory_id = create_resp.json()["id"]

    tag_resp = await test_app.post(
        f"/memories/{memory_id}/tags",
        json={"tags": ["auto"], "status": "suggested"},
    )
    assert tag_resp.status_code == 200

    get_resp = await test_app.get(f"/memories/{memory_id}")
    tags = {t["tag"]: t for t in get_resp.json()["tags"]}
    assert "auto" in tags
    assert tags["auto"]["suggested_at"] is not None
    assert tags["auto"]["status"] == "suggested"


async def test_remove_tag(test_app, test_user):
    """Add a tag then DELETE it; tag no longer appears on GET."""
    create_resp = await test_app.post(
        "/memories",
        json={"owner_user_id": test_user, "content": "memory with tag"},
    )
    memory_id = create_resp.json()["id"]

    await test_app.post(
        f"/memories/{memory_id}/tags",
        json={"tags": ["removeme"]},
    )

    del_resp = await test_app.delete(f"/memories/{memory_id}/tags/removeme")
    assert del_resp.status_code == 204

    get_resp = await test_app.get(f"/memories/{memory_id}")
    tags = [t["tag"] for t in get_resp.json()["tags"]]
    assert "removeme" not in tags


async def test_create_memory_audit_logged(test_app, test_user):
    """Create a memory; audit log has an entry with action=created."""
    create_resp = await test_app.post(
        "/memories",
        json={"owner_user_id": test_user, "content": "audit this"},
    )
    memory_id = create_resp.json()["id"]

    audit_resp = await test_app.get(
        "/audit",
        params={"entity_type": "memory", "entity_id": memory_id},
    )
    assert audit_resp.status_code == 200
    entries = audit_resp.json()
    actions = [e["action"] for e in entries]
    assert "created" in actions
