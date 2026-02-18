"""Tests for the backup status endpoint."""

from datetime import datetime, timezone


async def test_backup_status_not_found(test_app, test_user):
    """GET /backup/status/{user_id} returns 404 when no backups exist."""
    resp = await test_app.get(f"/backup/status/{test_user}")
    assert resp.status_code == 404


async def test_backup_status_completed(test_app, test_user, test_db):
    """GET returns a completed backup with all expected fields."""
    started_at = datetime.now(timezone.utc).isoformat()
    completed_at = datetime.now(timezone.utc).isoformat()
    await test_db.execute(
        "INSERT INTO backup_jobs (backup_id, user_id, started_at, completed_at, status, file_path, error_message) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("backup-001", test_user, started_at, completed_at, "completed", "/backups/test.zip", None),
    )
    await test_db.commit()

    resp = await test_app.get(f"/backup/status/{test_user}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["backup_id"] == "backup-001"
    assert data["user_id"] == test_user
    assert data["status"] == "completed"
    assert data["file_path"] == "/backups/test.zip"
    assert data["error_message"] is None
    assert data["started_at"] is not None
    assert data["completed_at"] is not None


async def test_backup_status_in_progress(test_app, test_user, test_db):
    """In-progress backup has null completed_at and file_path."""
    started_at = datetime.now(timezone.utc).isoformat()
    await test_db.execute(
        "INSERT INTO backup_jobs (backup_id, user_id, started_at, completed_at, status, file_path, error_message) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("backup-002", test_user, started_at, None, "in_progress", None, None),
    )
    await test_db.commit()

    resp = await test_app.get(f"/backup/status/{test_user}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["backup_id"] == "backup-002"
    assert data["status"] == "in_progress"
    assert data["completed_at"] is None
    assert data["file_path"] is None
    assert data["error_message"] is None


async def test_backup_status_failed(test_app, test_user, test_db):
    """Failed backup includes error_message and correct status."""
    started_at = datetime.now(timezone.utc).isoformat()
    completed_at = datetime.now(timezone.utc).isoformat()
    await test_db.execute(
        "INSERT INTO backup_jobs (backup_id, user_id, started_at, completed_at, status, file_path, error_message) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("backup-003", test_user, started_at, completed_at, "failed", None, "Disk space full"),
    )
    await test_db.commit()

    resp = await test_app.get(f"/backup/status/{test_user}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["backup_id"] == "backup-003"
    assert data["status"] == "failed"
    assert data["file_path"] is None
    assert data["error_message"] == "Disk space full"
    assert data["started_at"] is not None
    assert data["completed_at"] is not None


async def test_backup_status_most_recent(test_app, test_user, test_db):
    """When multiple backups exist, the most recent is returned."""
    await test_db.execute(
        "INSERT INTO backup_jobs (backup_id, user_id, started_at, completed_at, status, file_path, error_message) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("backup-old", test_user, "2024-01-01T10:00:00Z", "2024-01-01T10:30:00Z", "completed", "/backups/old.zip", None),
    )
    await test_db.execute(
        "INSERT INTO backup_jobs (backup_id, user_id, started_at, completed_at, status, file_path, error_message) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("backup-middle", test_user, "2024-06-15T14:00:00Z", "2024-06-15T14:30:00Z", "completed", "/backups/middle.zip", None),
    )
    recent_started = datetime.now(timezone.utc).isoformat()
    recent_completed = datetime.now(timezone.utc).isoformat()
    await test_db.execute(
        "INSERT INTO backup_jobs (backup_id, user_id, started_at, completed_at, status, file_path, error_message) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("backup-recent", test_user, recent_started, recent_completed, "completed", "/backups/recent.zip", None),
    )
    await test_db.commit()

    resp = await test_app.get(f"/backup/status/{test_user}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["backup_id"] == "backup-recent"
    assert data["file_path"] == "/backups/recent.zip"


async def test_backup_status_multiple_users(test_app, test_user, test_db):
    """Backups are isolated per user."""
    other_user_id = 99999
    await test_db.execute(
        "INSERT INTO users (telegram_user_id, display_name, is_allowed) VALUES (?, ?, ?)",
        (other_user_id, "Other User", 1),
    )

    started = datetime.now(timezone.utc).isoformat()
    completed = datetime.now(timezone.utc).isoformat()
    await test_db.execute(
        "INSERT INTO backup_jobs (backup_id, user_id, started_at, completed_at, status, file_path, error_message) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("backup-user1", test_user, started, completed, "completed", "/backups/user1.zip", None),
    )
    await test_db.execute(
        "INSERT INTO backup_jobs (backup_id, user_id, started_at, completed_at, status, file_path, error_message) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("backup-user2", other_user_id, started, completed, "completed", "/backups/user2.zip", None),
    )
    await test_db.commit()

    resp1 = await test_app.get(f"/backup/status/{test_user}")
    assert resp1.status_code == 200
    data1 = resp1.json()
    assert data1["backup_id"] == "backup-user1"
    assert data1["file_path"] == "/backups/user1.zip"

    resp2 = await test_app.get(f"/backup/status/{other_user_id}")
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["backup_id"] == "backup-user2"
    assert data2["file_path"] == "/backups/user2.zip"


async def test_backup_datetime_parsing(test_app, test_user, test_db):
    """Datetime fields are correctly parsed in the response."""
    started_at = "2024-01-15T10:30:45Z"
    completed_at = "2024-01-15T11:45:30Z"
    await test_db.execute(
        "INSERT INTO backup_jobs (backup_id, user_id, started_at, completed_at, status, file_path, error_message) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("backup-datetime", test_user, started_at, completed_at, "completed", "/backups/test.zip", None),
    )
    await test_db.commit()

    resp = await test_app.get(f"/backup/status/{test_user}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["started_at"] is not None
    assert data["completed_at"] is not None
    assert "2024-01-15" in data["started_at"]
    assert "2024-01-15" in data["completed_at"]


async def test_backup_null_completed_at(test_app, test_user, test_db):
    """In-progress backup has null completed_at in the JSON response."""
    started_at = datetime.now(timezone.utc).isoformat()
    await test_db.execute(
        "INSERT INTO backup_jobs (backup_id, user_id, started_at, completed_at, status, file_path, error_message) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("backup-null", test_user, started_at, None, "in_progress", None, None),
    )
    await test_db.commit()

    resp = await test_app.get(f"/backup/status/{test_user}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["completed_at"] is None
    assert data["started_at"] is not None


async def test_backup_all_optional_fields(test_app, test_user, test_db):
    """Failed backup with all fields populated returns every field correctly."""
    started_at = datetime.now(timezone.utc).isoformat()
    completed_at = datetime.now(timezone.utc).isoformat()
    await test_db.execute(
        "INSERT INTO backup_jobs (backup_id, user_id, started_at, completed_at, status, file_path, error_message) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("backup-full", test_user, started_at, completed_at, "failed", "/backups/attempt.zip", "Connection timeout"),
    )
    await test_db.commit()

    resp = await test_app.get(f"/backup/status/{test_user}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["backup_id"] == "backup-full"
    assert data["user_id"] == test_user
    assert data["status"] == "failed"
    assert data["file_path"] == "/backups/attempt.zip"
    assert data["error_message"] == "Connection timeout"
    assert data["started_at"] is not None
    assert data["completed_at"] is not None
