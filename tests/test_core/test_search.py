"""Tests for the search endpoint (FTS5)."""


async def _create_confirmed_memory(client, user_id: int, content: str) -> str:
    """Helper to create a confirmed memory and return its ID."""
    resp = await client.post(
        "/memories",
        json={"owner_user_id": user_id, "content": content},
    )
    return resp.json()["id"]


async def test_search_finds_memory(test_app, test_user):
    """Confirmed memory with matching content appears in search results."""
    await _create_confirmed_memory(test_app, test_user, "buy butter at the store")

    resp = await test_app.get("/search", params={"q": "butter", "owner": test_user})
    assert resp.status_code == 200
    results = resp.json()
    contents = [r["memory"]["content"] for r in results]
    assert any("butter" in c for c in contents)


async def test_search_ignores_pending(test_app, test_user):
    """Pending memories do not appear in search results."""
    resp = await test_app.post(
        "/memories",
        json={
            "owner_user_id": test_user,
            "content": "zxqwerty_pending_unique",
            "media_type": "image",
        },
    )
    assert resp.json()["status"] == "pending"

    search_resp = await test_app.get(
        "/search",
        params={"q": "zxqwerty_pending_unique", "owner": test_user},
    )
    assert search_resp.status_code == 200
    assert search_resp.json() == []


async def test_search_pin_boost(test_app, test_user):
    """Pinned memory with matching content appears before unpinned one."""
    # Create two memories with similar content
    unpinned_id = await _create_confirmed_memory(
        test_app, test_user, "reminder to review report document"
    )
    pinned_id = await _create_confirmed_memory(
        test_app, test_user, "reminder to review report document"
    )

    # Pin the second one
    await test_app.patch(f"/memories/{pinned_id}", json={"is_pinned": True})

    resp = await test_app.get(
        "/search", params={"q": "review report", "owner": test_user}
    )
    assert resp.status_code == 200
    results = resp.json()
    assert len(results) >= 2

    result_ids = [r["memory"]["id"] for r in results]
    pinned_pos = result_ids.index(pinned_id)
    unpinned_pos = result_ids.index(unpinned_id)
    assert pinned_pos < unpinned_pos


async def test_search_by_tag(test_app, test_user):
    """Memory with a confirmed tag matching query appears in results."""
    memory_id = await _create_confirmed_memory(
        test_app, test_user, "weekly errands list"
    )
    await test_app.post(
        f"/memories/{memory_id}/tags",
        json={"tags": ["groceries"]},
    )

    resp = await test_app.get("/search", params={"q": "groceries", "owner": test_user})
    assert resp.status_code == 200
    results = resp.json()
    result_ids = [r["memory"]["id"] for r in results]
    assert memory_id in result_ids


async def test_search_owner_filter(test_app, test_db):
    """Memories belonging to a different owner are excluded from results."""
    # Create a second user
    await test_db.execute(
        "INSERT INTO users (telegram_user_id, display_name, is_allowed) VALUES (?, ?, ?)",
        (99999, "Other User", 1),
    )
    await test_db.commit()

    user_a = 12345
    user_b = 99999

    # Insert user_a manually (same as test_user fixture)
    await test_db.execute(
        "INSERT OR IGNORE INTO users (telegram_user_id, display_name, is_allowed) VALUES (?, ?, ?)",
        (user_a, "Test User", 1),
    )
    await test_db.commit()

    await _create_confirmed_memory(test_app, user_a, "user_a unique_xyzabc memory")
    await _create_confirmed_memory(test_app, user_b, "user_b unique_xyzabc memory")

    resp = await test_app.get("/search", params={"q": "unique_xyzabc", "owner": user_a})
    assert resp.status_code == 200
    results = resp.json()
    assert all(r["memory"]["owner_user_id"] == user_a for r in results)


async def test_search_empty_query_returns_400(test_app, test_user):
    """Search with empty q returns 400."""
    resp = await test_app.get("/search", params={"q": "", "owner": test_user})
    assert resp.status_code == 400


async def test_search_pinned_empty_query(test_app, test_user):
    """Search with empty q but pinned=true returns all pinned memories."""
    # Create a confirmed memory and pin it
    memory_id = await _create_confirmed_memory(
        test_app, test_user, "important meeting notes"
    )
    await test_app.patch(f"/memories/{memory_id}", json={"is_pinned": True})

    # Search with empty query but pinned=true should return the pinned memory
    resp = await test_app.get(
        "/search", params={"q": "", "owner": test_user, "pinned": "true"}
    )
    assert resp.status_code == 200
    results = resp.json()
    assert len(results) == 1
    assert results[0]["memory"]["id"] == memory_id
    assert results[0]["memory"]["is_pinned"] is True


async def test_targeted_index_and_remove(test_app, test_user):
    """Targeted FTS5 insert/delete: add 3, search finds all 3, remove 1, search finds 2."""
    id_a = await _create_confirmed_memory(
        test_app, test_user, "targeted_unique_alpha document"
    )
    id_b = await _create_confirmed_memory(
        test_app, test_user, "targeted_unique_beta document"
    )
    id_c = await _create_confirmed_memory(
        test_app, test_user, "targeted_unique_gamma document"
    )

    # All 3 should be findable
    resp = await test_app.get(
        "/search", params={"q": "targeted_unique", "owner": test_user}
    )
    assert resp.status_code == 200
    result_ids = [r["memory"]["id"] for r in resp.json()]
    assert id_a in result_ids
    assert id_b in result_ids
    assert id_c in result_ids

    # Delete memory id_b via the API (DELETE removes it from FTS5 via remove_from_index)
    del_resp = await test_app.delete(f"/memories/{id_b}")
    assert del_resp.status_code == 204

    # Now only 2 should appear
    resp2 = await test_app.get(
        "/search", params={"q": "targeted_unique", "owner": test_user}
    )
    assert resp2.status_code == 200
    result_ids2 = [r["memory"]["id"] for r in resp2.json()]
    assert id_a in result_ids2
    assert id_c in result_ids2
    assert id_b not in result_ids2
