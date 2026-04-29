from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from bearmemori.api.routes import create_app
from bearmemori.core.proposal_service import ProposalService
from bearmemori.storage.models import MemoryCategory, MemoryRecord, ReflectionProposal


def _record(record_id: str) -> MemoryRecord:
    return MemoryRecord(
        id=record_id,
        category=MemoryCategory.GENERAL,
        title=f"T {record_id}",
        content=f"C {record_id}",
        created_at=datetime.now(UTC),
        importance=5,
    )


@pytest.fixture
def app_and_db():
    db = MagicMock()
    vs = MagicMock()
    pending_store = MagicMock()
    memory_service = MagicMock()
    proposal_service = ProposalService(db=db, vector_store=vs)
    app = create_app(
        db=db,
        vector_store=vs,
        pending_store=pending_store,
        memory_service=memory_service,
        proposal_service=proposal_service,
    )
    return app, db, vs


def test_list_proposals_returns_summaries(app_and_db):
    app, db, _ = app_and_db
    db.list_proposals.return_value = [
        ReflectionProposal(
            id="p1",
            proposal_type="merge",
            status="pending",
            memory_ids=["mem_a", "mem_b"],
            recommended_keep_id="mem_a",
            reasoning="dup",
            created_at=datetime.now(UTC),
        )
    ]
    db.count_proposals.return_value = 1
    client = TestClient(app)
    res = client.get("/reflection/proposals?status=pending")
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 1
    assert body["proposals"][0]["id"] == "p1"
    assert body["proposals"][0]["memory_count"] == 2


def test_get_proposal_hydrates_memories(app_and_db):
    app, db, _ = app_and_db
    db.get_proposal.return_value = ReflectionProposal(
        id="p1",
        proposal_type="merge",
        status="pending",
        memory_ids=["mem_a", "mem_b"],
        recommended_keep_id="mem_a",
        reasoning="dup",
        created_at=datetime.now(UTC),
    )
    db.get.side_effect = lambda mid: _record(mid)
    client = TestClient(app)
    res = client.get("/reflection/proposals/p1")
    assert res.status_code == 200
    body = res.json()
    assert body["proposal"]["id"] == "p1"
    assert len(body["memories"]) == 2


def test_approve_endpoint(app_and_db):
    app, db, vs = app_and_db
    db.get_proposal.return_value = ReflectionProposal(
        id="p1",
        proposal_type="archive",
        status="pending",
        memory_ids=["mem_a"],
        reasoning="old",
        created_at=datetime.now(UTC),
    )
    db.get.return_value = _record("mem_a")
    client = TestClient(app)
    res = client.post("/reflection/proposals/p1/approve", json={})
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "approved"


def test_reject_endpoint(app_and_db):
    app, db, _ = app_and_db
    db.get_proposal.return_value = ReflectionProposal(
        id="p1",
        proposal_type="archive",
        status="pending",
        memory_ids=["mem_a"],
        reasoning="old",
        created_at=datetime.now(UTC),
    )
    client = TestClient(app)
    res = client.post("/reflection/proposals/p1/reject", json={"reason": "wrong"})
    assert res.status_code == 200
    assert res.json()["status"] == "rejected"


def test_approve_missing_returns_404(app_and_db):
    app, db, _ = app_and_db
    db.get_proposal.return_value = None
    client = TestClient(app)
    res = client.post("/reflection/proposals/missing/approve", json={})
    assert res.status_code == 404


def test_approve_validation_error_returns_400(app_and_db):
    app, db, _ = app_and_db
    db.get_proposal.return_value = ReflectionProposal(
        id="p1",
        proposal_type="merge",
        status="pending",
        memory_ids=["mem_a", "mem_b"],
        recommended_keep_id="mem_a",
        reasoning="dup",
        created_at=datetime.now(UTC),
    )
    db.get.side_effect = lambda mid: _record(mid)
    client = TestClient(app)
    res = client.post("/reflection/proposals/p1/approve", json={"keep_id": "mem_xyz"})
    assert res.status_code == 400
