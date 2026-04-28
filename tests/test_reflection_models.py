from datetime import UTC, datetime

from bearmemori.storage.models import ReflectionProposal


def test_reflection_proposal_minimal_merge():
    p = ReflectionProposal(
        id="prop_001",
        proposal_type="merge",
        status="pending",
        memory_ids=["mem_a", "mem_b"],
        recommended_keep_id="mem_a",
        reasoning="Same dentist appointment.",
        created_at=datetime.now(UTC),
    )
    assert p.proposal_type == "merge"
    assert p.status == "pending"
    assert p.recommended_importance is None
    assert p.resolved_at is None
    assert p.resolution_note is None


def test_reflection_proposal_archive():
    p = ReflectionProposal(
        id="prop_002",
        proposal_type="archive",
        status="pending",
        memory_ids=["mem_x"],
        reasoning="Trivial and old.",
        created_at=datetime.now(UTC),
    )
    assert p.recommended_keep_id is None


def test_reflection_proposal_rerank():
    p = ReflectionProposal(
        id="prop_003",
        proposal_type="rerank",
        status="pending",
        memory_ids=["mem_y"],
        recommended_importance=3,
        reasoning="Fading relevance.",
        created_at=datetime.now(UTC),
    )
    assert p.recommended_importance == 3
