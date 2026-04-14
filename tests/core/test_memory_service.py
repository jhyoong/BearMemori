import pytest
from unittest.mock import MagicMock, AsyncMock
from bearmemori.core.memory_service import MemoryService
from bearmemori.storage.models import MemoryCategory, MemoryDraft, MemoryRecord


@pytest.fixture
def db():
    return MagicMock()


@pytest.fixture
def vector_store():
    return MagicMock()


@pytest.fixture
def service(db, vector_store):
    return MemoryService(db=db, vector_store=vector_store)


def test_search_delegates_to_vector_store(service, vector_store):
    vector_store.search.return_value = [{"id": "mem_1", "document": "test"}]
    results = service.search("query", top_k=3)
    vector_store.search.assert_called_once_with(query="query", top_k=3, category=None)
    assert len(results) == 1


def test_get_delegates_to_db(service, db):
    db.get.return_value = None
    result = service.get("mem_abc")
    db.get.assert_called_once_with("mem_abc")
    assert result is None


def test_delete_calls_db_and_vector_store(service, db, vector_store):
    db.get.return_value = MagicMock(image_path=None)
    db.delete.return_value = True
    service.delete("mem_abc")
    db.delete.assert_called_once_with("mem_abc")
    vector_store.delete.assert_called_once_with("mem_abc")


def test_retrieve_context_scores_results(service, vector_store, db):
    vector_store.search.return_value = [
        {"id": "mem_1", "document": "high imp", "distance": 0.1,
         "metadata": {"importance": 9}},
        {"id": "mem_2", "document": "low imp", "distance": 0.5,
         "metadata": {"importance": 1}},
    ]
    db.get_upcoming_events.return_value = []
    result = service.retrieve_context("query", top_k=5)
    # high importance item should appear in results
    assert any("high imp" in item["document"] for item in result["items"])
