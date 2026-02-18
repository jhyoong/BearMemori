"""Tests for the settings endpoints."""


async def test_get_default_settings(test_app, test_user):
    """GET settings for a user with no settings row returns defaults."""
    resp = await test_app.get(f"/settings/{test_user}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["user_id"] == test_user
    assert data["timezone"] == "UTC"
    assert data["language"] == "en"


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
