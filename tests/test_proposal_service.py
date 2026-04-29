from datetime import UTC, datetime
from unittest.mock import MagicMock

from bearmemori.core.proposal_service import (
    ProposalAlreadyResolvedError,
    ProposalNotFoundError,
    ProposalService,
    ProposalValidationError,
)
from bearmemori.storage.models import MemoryCategory, MemoryRecord, ReflectionProposal


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


def _record(record_id: str, importance: int = 5, archived: bool = False) -> MemoryRecord:
    return MemoryRecord(
        id=record_id,
        category=MemoryCategory.GENERAL,
        title=f"Title {record_id}",
        content=f"Content {record_id}",
        created_at=datetime.now(UTC),
        importance=importance,
        archived=archived,
    )


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
    db = MagicMock()
    db.get_proposal.return_value = _proposal(status="approved", resolved_at=datetime.now(UTC))
    svc = ProposalService(db=db, vector_store=MagicMock())
    try:
        svc.reject("p1", reason=None)
    except ProposalAlreadyResolvedError:
        return
    raise AssertionError("expected ProposalAlreadyResolvedError")


def test_approve_archive_archives_the_memory():
    db = MagicMock()
    db.get_proposal.return_value = _proposal(proposal_type="archive", memory_ids=["mem_a"])
    db.get.return_value = _record("mem_a", archived=False)
    vs = MagicMock()
    svc = ProposalService(db=db, vector_store=vs)

    result = svc.approve("p1", overrides={})

    args, kwargs = db.update.call_args
    updated_record = args[0]
    assert updated_record.archived is True
    vs.delete.assert_called_once_with("mem_a")
    db.resolve_proposal.assert_called_once()
    assert result["applied"]["archived_ids"] == ["mem_a"]


def test_approve_archive_already_archived_is_noop_but_resolves_proposal():
    db = MagicMock()
    db.get_proposal.return_value = _proposal(proposal_type="archive", memory_ids=["mem_a"])
    db.get.return_value = _record("mem_a", archived=True)
    vs = MagicMock()
    svc = ProposalService(db=db, vector_store=vs)

    result = svc.approve("p1", overrides={})

    db.update.assert_not_called()
    vs.delete.assert_not_called()
    db.resolve_proposal.assert_called_once()
    assert result["applied"]["archived_ids"] == []


def test_approve_rerank_updates_importance():
    db = MagicMock()
    db.get_proposal.return_value = _proposal(
        proposal_type="rerank",
        memory_ids=["mem_b"],
        recommended_importance=7,
    )
    db.get.return_value = _record("mem_b", importance=5)
    vs = MagicMock()
    svc = ProposalService(db=db, vector_store=vs)

    result = svc.approve("p1", overrides={})

    args, _ = db.update.call_args
    updated = args[0]
    assert updated.importance == 7
    vs.update.assert_called_once_with(updated)
    assert result["applied"]["updated_ids"] == ["mem_b"]


def test_approve_rerank_with_user_override():
    db = MagicMock()
    db.get_proposal.return_value = _proposal(
        proposal_type="rerank", memory_ids=["mem_b"], recommended_importance=7
    )
    db.get.return_value = _record("mem_b", importance=5)
    svc = ProposalService(db=db, vector_store=MagicMock())

    svc.approve("p1", overrides={"importance": 9})

    updated = db.update.call_args[0][0]
    assert updated.importance == 9


def test_approve_rerank_invalid_importance_raises():
    db = MagicMock()
    db.get_proposal.return_value = _proposal(
        proposal_type="rerank", memory_ids=["mem_b"], recommended_importance=7
    )
    db.get.return_value = _record("mem_b", importance=5)
    svc = ProposalService(db=db, vector_store=MagicMock())

    try:
        svc.approve("p1", overrides={"importance": 99})
    except ProposalValidationError:
        return
    raise AssertionError("expected ProposalValidationError")


def test_approve_rerank_archived_memory_raises():
    db = MagicMock()
    db.get_proposal.return_value = _proposal(
        proposal_type="rerank", memory_ids=["mem_b"], recommended_importance=7
    )
    db.get.return_value = _record("mem_b", archived=True)
    svc = ProposalService(db=db, vector_store=MagicMock())

    try:
        svc.approve("p1", overrides={})
    except ProposalValidationError:
        return
    raise AssertionError("expected ProposalValidationError")


def test_approve_rerank_zero_importance_raises():
    db = MagicMock()
    db.get_proposal.return_value = _proposal(
        proposal_type="rerank", memory_ids=["mem_b"], recommended_importance=7
    )
    db.get.return_value = _record("mem_b", importance=5)
    svc = ProposalService(db=db, vector_store=MagicMock())

    try:
        svc.approve("p1", overrides={"importance": 0})
    except ProposalValidationError:
        return
    raise AssertionError("expected ProposalValidationError")


def test_approve_merge_archives_others_keeps_one():
    db = MagicMock()
    db.get_proposal.return_value = _proposal(
        proposal_type="merge",
        memory_ids=["mem_a", "mem_b", "mem_c"],
        recommended_keep_id="mem_a",
    )
    records = {
        "mem_a": _record("mem_a"),
        "mem_b": _record("mem_b"),
        "mem_c": _record("mem_c"),
    }
    db.get.side_effect = lambda mid: records[mid]
    vs = MagicMock()
    svc = ProposalService(db=db, vector_store=vs)

    result = svc.approve("p1", overrides={})

    archived_ids = sorted(result["applied"]["archived_ids"])
    assert archived_ids == ["mem_b", "mem_c"]

    updated_ids = [c.args[0].id for c in db.update.call_args_list]
    assert sorted(updated_ids) == ["mem_b", "mem_c"]
    vs.delete.assert_any_call("mem_b")
    vs.delete.assert_any_call("mem_c")


def test_approve_merge_with_keep_override():
    db = MagicMock()
    db.get_proposal.return_value = _proposal(
        proposal_type="merge",
        memory_ids=["mem_a", "mem_b"],
        recommended_keep_id="mem_a",
    )
    records = {"mem_a": _record("mem_a"), "mem_b": _record("mem_b")}
    db.get.side_effect = lambda mid: records[mid]
    svc = ProposalService(db=db, vector_store=MagicMock())

    result = svc.approve("p1", overrides={"keep_id": "mem_b"})

    assert result["applied"]["archived_ids"] == ["mem_a"]


def test_approve_merge_keep_id_not_in_group_raises():
    db = MagicMock()
    db.get_proposal.return_value = _proposal(
        proposal_type="merge",
        memory_ids=["mem_a", "mem_b"],
        recommended_keep_id="mem_a",
    )
    db.get.side_effect = lambda mid: {"mem_a": _record("mem_a"), "mem_b": _record("mem_b")}[mid]
    svc = ProposalService(db=db, vector_store=MagicMock())

    try:
        svc.approve("p1", overrides={"keep_id": "mem_xyz"})
    except ProposalValidationError:
        return
    raise AssertionError("expected ProposalValidationError")


def test_approve_merge_keep_id_already_archived_raises():
    db = MagicMock()
    db.get_proposal.return_value = _proposal(
        proposal_type="merge",
        memory_ids=["mem_a", "mem_b"],
        recommended_keep_id="mem_a",
    )
    db.get.side_effect = lambda mid: {
        "mem_a": _record("mem_a", archived=True),
        "mem_b": _record("mem_b"),
    }[mid]
    svc = ProposalService(db=db, vector_store=MagicMock())

    try:
        svc.approve("p1", overrides={})
    except ProposalValidationError:
        return
    raise AssertionError("expected ProposalValidationError")


def test_approve_merge_other_already_archived_is_skipped():
    """If one of the memories was already archived externally, don't fail — just continue."""
    db = MagicMock()
    db.get_proposal.return_value = _proposal(
        proposal_type="merge",
        memory_ids=["mem_a", "mem_b", "mem_c"],
        recommended_keep_id="mem_a",
    )
    db.get.side_effect = lambda mid: {
        "mem_a": _record("mem_a"),
        "mem_b": _record("mem_b", archived=True),
        "mem_c": _record("mem_c"),
    }[mid]
    svc = ProposalService(db=db, vector_store=MagicMock())

    result = svc.approve("p1", overrides={})
    assert result["applied"]["archived_ids"] == ["mem_c"]
