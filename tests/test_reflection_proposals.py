import sqlite3

from bearmemori.storage.database import MemoryDatabase


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
