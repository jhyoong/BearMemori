from datetime import UTC, datetime

from bearmemori.storage.models import MemoryCategory, MemoryRecord
from bearmemori.storage.vector_store import VectorStore


def test_vector_store_includes_importance_in_metadata():
    vs = VectorStore()
    vs.init()

    record = MemoryRecord(
        id="mem_vs_test",
        category=MemoryCategory.GENERAL,
        title="Important fact",
        content="The sky is blue",
        created_at=datetime.now(UTC),
        importance=9,
    )
    vs.add(record)

    results = vs.search("sky", top_k=1)
    assert len(results) == 1
    assert results[0]["metadata"]["importance"] == 9
