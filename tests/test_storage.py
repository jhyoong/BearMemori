import pytest
from bearmemori.storage.database import MemoryDatabase
from bearmemori.storage.models import Memory


@pytest.fixture
def db(tmp_path):
    db_path = str(tmp_path / "test.db")
    database = MemoryDatabase(db_path)
    database.initialize()
    return database


def _make_memory(**overrides) -> Memory:
    defaults = {
        "id": "test-id-1",
        "content": "User prefers dark mode",
        "raw_input": "I like dark mode",
        "memory_type": "preference",
        "tags": ["ui", "preference"],
        "source": "telegram",
    }
    defaults.update(overrides)
    return Memory(**defaults)


def test_create_and_get_memory(db):
    memory = _make_memory()
    db.create(memory)
    result = db.get("test-id-1")
    assert result is not None
    assert result.content == "User prefers dark mode"
    assert result.tags == ["ui", "preference"]


def test_get_nonexistent_returns_none(db):
    assert db.get("nope") is None


def test_update_memory(db):
    memory = _make_memory()
    db.create(memory)
    memory.content = "User prefers light mode"
    memory.tags = ["ui", "preference", "updated"]
    db.update(memory)
    result = db.get("test-id-1")
    assert result.content == "User prefers light mode"
    assert "updated" in result.tags


def test_delete_memory(db):
    db.create(_make_memory())
    db.delete("test-id-1")
    assert db.get("test-id-1") is None


def test_list_memories(db):
    db.create(_make_memory(id="1", memory_type="preference"))
    db.create(_make_memory(id="2", memory_type="event"))
    db.create(_make_memory(id="3", memory_type="preference"))

    all_memories = db.list_memories()
    assert len(all_memories) == 3

    prefs = db.list_memories(memory_type="preference")
    assert len(prefs) == 2


def test_list_memories_by_tag(db):
    db.create(_make_memory(id="1", tags=["food", "preference"]))
    db.create(_make_memory(id="2", tags=["music"]))

    results = db.list_memories(tag="food")
    assert len(results) == 1
    assert results[0].id == "1"


def test_keyword_search(db):
    db.create(_make_memory(id="1", content="User likes pizza for dinner"))
    db.create(_make_memory(id="2", content="User prefers dark mode in editors"))
    db.create(_make_memory(id="3", content="Meeting with John on Friday"))

    results = db.search_keyword("pizza")
    assert len(results) == 1
    assert results[0].id == "1"


def test_keyword_search_no_results(db):
    db.create(_make_memory(id="1", content="User likes pizza"))
    results = db.search_keyword("sushi")
    assert len(results) == 0
