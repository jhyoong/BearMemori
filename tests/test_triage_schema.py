"""Tests for TriageRequest schema accepting current_time."""

from bearmemori.api.schemas import TriageRequest


def test_triage_request_accepts_current_time():
    """TriageRequest should accept an optional current_time field."""
    req = TriageRequest(
        conversation=[{"role": "user", "content": "hello"}],
        current_time="Monday, March 24, 2026, 07:33 PM +0800 (Asia/Singapore)",
    )
    assert req.current_time == "Monday, March 24, 2026, 07:33 PM +0800 (Asia/Singapore)"


def test_triage_request_current_time_defaults_to_none():
    """current_time should default to None when not provided."""
    req = TriageRequest(
        conversation=[{"role": "user", "content": "hello"}],
    )
    assert req.current_time is None


def test_triage_response_includes_reason_when_not_saved():
    """The triage API should return a reason when should_save is False."""
    from unittest.mock import AsyncMock, patch

    from fastapi.testclient import TestClient

    from bearmemori.api.routes import create_app
    from bearmemori.core.triage import TriageResult
    from bearmemori.storage.database import MemoryDatabase
    from bearmemori.storage.pending_store import PendingStore
    from bearmemori.storage.vector_store import VectorStore

    db = MemoryDatabase(":memory:")
    vs = VectorStore.__new__(VectorStore)
    ps = PendingStore()

    app = create_app(
        db,
        vs,
        ps,
        llm_base_url="http://localhost/v1",
        llm_api_key="test",
        llm_model="test",
    )
    client = TestClient(app)

    with patch(
        "bearmemori.api.routes.run_triage",
        new_callable=AsyncMock,
        return_value=TriageResult(should_save=False, reason="llm_decided_no"),
    ):
        resp = client.post(
            "/memory/triage",
            json={
                "conversation": [{"role": "user", "content": "hello"}],
            },
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["should_save"] is False
    assert data["reason"] == "llm_decided_no"
