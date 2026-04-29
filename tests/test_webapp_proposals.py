from datetime import UTC, datetime
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from bearmemori.core.proposal_service import ProposalService
from bearmemori.storage.models import MemoryCategory, MemoryRecord, ReflectionProposal
from bearmemori.webapp.auth import WebappAuthMiddleware
from bearmemori.webapp.router import create_webapp_router


def _record(record_id: str) -> MemoryRecord:
    return MemoryRecord(
        id=record_id,
        category=MemoryCategory.GENERAL,
        title=f"T {record_id}",
        content=f"C {record_id}",
        created_at=datetime.now(UTC),
        importance=5,
    )


def _proposal(proposal_type="merge"):
    return ReflectionProposal(
        id="p1",
        proposal_type=proposal_type,
        status="pending",
        memory_ids=["mem_a", "mem_b"] if proposal_type == "merge" else ["mem_a"],
        recommended_keep_id="mem_a" if proposal_type == "merge" else None,
        recommended_importance=7 if proposal_type == "rerank" else None,
        reasoning="reason",
        created_at=datetime.now(UTC),
    )


def _make_client(proposal):
    db = MagicMock()
    db.list_proposals.return_value = [proposal]
    db.count_proposals.return_value = 1
    db.get_proposal.return_value = proposal
    db.get.side_effect = lambda mid: _record(mid)
    vs = MagicMock()
    auth = WebappAuthMiddleware(None, "secret")
    proposal_service = ProposalService(db=db, vector_store=vs)
    router = create_webapp_router(
        db,
        vs,
        auth,
        memory_service=MagicMock(),
        proposal_service=proposal_service,
    )
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    # bypass auth by injecting cookie directly (same pattern as test_webapp_auth.py)
    client.cookies.set("webapp_session", auth._token)
    return client, db


def test_proposals_page_renders_merge():
    client, _ = _make_client(_proposal("merge"))
    res = client.get("/webapp/proposals")
    assert res.status_code == 200
    assert "Possible duplicates" in res.text
    assert "mem_a" in res.text


def test_proposals_page_renders_archive():
    client, _ = _make_client(_proposal("archive"))
    res = client.get("/webapp/proposals")
    assert res.status_code == 200
    assert "Suggested archive" in res.text


def test_proposals_page_renders_rerank():
    client, _ = _make_client(_proposal("rerank"))
    res = client.get("/webapp/proposals")
    assert res.status_code == 200
    assert "importance" in res.text.lower()
