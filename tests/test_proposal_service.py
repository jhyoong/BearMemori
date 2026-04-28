from datetime import UTC, datetime
from unittest.mock import MagicMock

from bearmemori.core.proposal_service import ProposalNotFoundError, ProposalService
from bearmemori.storage.models import ReflectionProposal


def _proposal(**overrides):
    base = dict(
        id="p1",
        proposal_type="archive",
        status="pending",
        memory_ids=["mem_a"],
        reasoning="old",
        created_at=datetime.now(UTC),
    )
    base.update(overrides)
    return ReflectionProposal(**base)


def test_reject_resolves_proposal_with_note():
    db = MagicMock()
    db.get_proposal.return_value = _proposal()
    vs = MagicMock()
    svc = ProposalService(db=db, vector_store=vs)

    result = svc.reject("p1", reason="not duplicates")

    db.resolve_proposal.assert_called_once_with("p1", status="rejected", note="not duplicates")
    assert result["status"] == "rejected"


def test_reject_missing_proposal_raises():
    db = MagicMock()
    db.get_proposal.return_value = None
    svc = ProposalService(db=db, vector_store=MagicMock())
    try:
        svc.reject("missing", reason=None)
    except ProposalNotFoundError:
        return
    raise AssertionError("expected ProposalNotFoundError")


def test_reject_already_resolved_raises():
    from bearmemori.core.proposal_service import ProposalAlreadyResolvedError

    db = MagicMock()
    db.get_proposal.return_value = _proposal(status="approved", resolved_at=datetime.now(UTC))
    svc = ProposalService(db=db, vector_store=MagicMock())
    try:
        svc.reject("p1", reason=None)
    except ProposalAlreadyResolvedError:
        return
    raise AssertionError("expected ProposalAlreadyResolvedError")
