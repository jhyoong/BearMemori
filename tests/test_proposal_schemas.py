from bearmemori.api.schemas import (
    ApproveProposalRequest,
    ProposalSummary,
    RejectProposalRequest,
)


def test_proposal_summary_basic():
    s = ProposalSummary(
        id="p1",
        proposal_type="merge",
        status="pending",
        created_at="2026-04-28T00:00:00+00:00",
        memory_count=2,
        reasoning_preview="Same dentist appointment.",
    )
    assert s.memory_count == 2


def test_approve_request_optional_overrides():
    r = ApproveProposalRequest()
    assert r.keep_id is None
    assert r.importance is None

    r2 = ApproveProposalRequest(keep_id="mem_a", importance=5)
    assert r2.keep_id == "mem_a"


def test_reject_request_optional_reason():
    r = RejectProposalRequest()
    assert r.reason is None
