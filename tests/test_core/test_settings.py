"""Tests for the settings endpoints."""

import asyncio


async def test_get_default_settings(test_app, test_user):
    """GET settings for a user with no settings row returns defaults."""
    resp = await test_app.get(f"/settings/{test_user}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["user_id"] == test_user
    assert data["timezone"] == "UTC"
    assert data["language"] == "en"


async def test_partial_update_timezone_only(test_app, test_user):
    """PUT with only timezone preserves default language."""
    resp = await test_app.put(
        f"/settings/{test_user}",
        json={"timezone": "Europe/Berlin"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["timezone"] == "Europe/Berlin"
    assert data["language"] == "en"

    get_resp = await test_app.get(f"/settings/{test_user}")
    get_data = get_resp.json()
    assert get_data["timezone"] == "Europe/Berlin"
    assert get_data["language"] == "en"


async def test_partial_update_language_only(test_app, test_user):
    """PUT with only language preserves default timezone."""
    resp = await test_app.put(
        f"/settings/{test_user}",
        json={"language": "fr"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["language"] == "fr"
    assert data["timezone"] == "UTC"

    get_resp = await test_app.get(f"/settings/{test_user}")
    get_data = get_resp.json()
    assert get_data["language"] == "fr"
    assert get_data["timezone"] == "UTC"


async def test_upsert_no_duplicate_rows(test_app, test_user, test_db):
    """PUT twice for same user results in exactly 1 row in user_settings."""
    await test_app.put(
        f"/settings/{test_user}",
        json={"timezone": "Asia/Tokyo", "language": "ja"},
    )
    await test_app.put(
        f"/settings/{test_user}",
        json={"timezone": "Asia/Seoul", "language": "ko"},
    )

    cursor = await test_db.execute(
        "SELECT COUNT(*) FROM user_settings WHERE user_id = ?",
        (test_user,),
    )
    count = (await cursor.fetchone())[0]
    assert count == 1, f"Expected 1 row but found {count}"

    cursor = await test_db.execute(
        "SELECT timezone, language FROM user_settings WHERE user_id = ?",
        (test_user,),
    )
    row = await cursor.fetchone()
    assert row["timezone"] == "Asia/Seoul"
    assert row["language"] == "ko"


async def test_multiple_users_isolation(test_app, test_user, test_db):
    """Settings for two different users are isolated from each other."""
    second_user = 99999
    await test_db.execute(
        "INSERT INTO users (telegram_user_id, display_name, is_allowed) "
        "VALUES (?, ?, ?)",
        (second_user, "Other User", 1),
    )
    await test_db.commit()

    await test_app.put(
        f"/settings/{test_user}",
        json={"timezone": "America/New_York", "language": "en"},
    )
    await test_app.put(
        f"/settings/{second_user}",
        json={"timezone": "Europe/London", "language": "fr"},
    )

    resp1 = await test_app.get(f"/settings/{test_user}")
    data1 = resp1.json()
    assert data1["timezone"] == "America/New_York"
    assert data1["language"] == "en"

    resp2 = await test_app.get(f"/settings/{second_user}")
    data2 = resp2.json()
    assert data2["timezone"] == "Europe/London"
    assert data2["language"] == "fr"


async def test_empty_update_preserves_values(test_app, test_user):
    """PUT with empty body preserves existing values and updates updated_at."""
    await test_app.put(
        f"/settings/{test_user}",
        json={"timezone": "Asia/Tokyo", "language": "ja"},
    )
    get_before = await test_app.get(f"/settings/{test_user}")
    before = get_before.json()

    await asyncio.sleep(0.05)

    resp = await test_app.put(
        f"/settings/{test_user}",
        json={},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["timezone"] == "Asia/Tokyo"
    assert data["language"] == "ja"
    assert data["updated_at"] >= before["updated_at"]


async def test_audit_log_for_settings(test_app, test_user, test_db):
    """PUT settings creates an audit log entry for user_settings entity_type."""
    await test_app.put(
        f"/settings/{test_user}",
        json={"timezone": "Pacific/Auckland", "language": "en"},
    )

    cursor = await test_db.execute(
        "SELECT entity_type, entity_id, action, actor FROM audit_log "
        "WHERE entity_type = ? AND entity_id = ?",
        ("user_settings", str(test_user)),
    )
    rows = await cursor.fetchall()
    assert len(rows) >= 1, "Expected at least 1 audit log entry"
    row = rows[0]
    assert row["entity_type"] == "user_settings"
    assert row["entity_id"] == str(test_user)
    assert row["action"] == "updated"


async def test_update_settings(test_app, test_user):
    """PUT timezone change persists on subsequent GET."""
    put_resp = await test_app.put(
        f"/settings/{test_user}",
        json={"timezone": "America/New_York"},
    )
    assert put_resp.status_code == 200
    assert put_resp.json()["timezone"] == "America/New_York"

    get_resp = await test_app.get(f"/settings/{test_user}")
    assert get_resp.json()["timezone"] == "America/New_York"


async def test_get_settings_auto_creates_user(test_app):
    """GET settings for a user not in the users table returns defaults (no error)."""
    # The settings endpoint returns defaults for unknown users without creating a row.
    unknown_user_id = 88888
    resp = await test_app.get(f"/settings/{unknown_user_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["user_id"] == unknown_user_id
    assert data["timezone"] == "UTC"
    assert data["language"] == "en"
