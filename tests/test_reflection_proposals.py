import sqlite3
from datetime import UTC, datetime

from bearmemori.storage.database import MemoryDatabase
from bearmemori.storage.models import ReflectionProposal


def _new_db(tmp_path):
    db = MemoryDatabase(str(tmp_path / "test.db"))
    db.initialize()
    return db


def test_reflection_proposal_tables_exist(tmp_path):
    _new_db(tmp_path)
    conn = sqlite3.connect(str(tmp_path / "test.db"))
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name IN ('reflection_proposals', 'reflection_proposal_memories')"
    ).fetchall()
    names = {r[0] for r in rows}
    assert "reflection_proposals" in names
    assert "reflection_proposal_memories" in names


def _make_merge_proposal(ids: list[str]) -> ReflectionProposal:
    return ReflectionProposal(
        id="prop_merge_1",
        proposal_type="merge",
        status="pending",
        memory_ids=ids,
        recommended_keep_id=ids[0],
        reasoning="dup",
        created_at=datetime.now(UTC),
    )


def test_create_proposal_persists_row_and_helper(tmp_path):
    db = _new_db(tmp_path)
    p = _make_merge_proposal(["mem_a", "mem_b", "mem_c"])
    db.create_proposal(p)

    fetched = db.get_proposal("prop_merge_1")
    assert fetched is not None
    assert fetched.proposal_type == "merge"
    assert fetched.memory_ids == ["mem_a", "mem_b", "mem_c"]
    assert fetched.recommended_keep_id == "mem_a"
    assert fetched.status == "pending"

    pending_ids = db.memory_ids_in_pending_proposals()
    assert pending_ids == {"mem_a", "mem_b", "mem_c"}
