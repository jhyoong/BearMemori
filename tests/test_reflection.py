from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from bearmemori.core.reflection import ReflectionTask
from bearmemori.llm.client import LLMClient
from bearmemori.storage.database import MemoryDatabase
from bearmemori.storage.models import MemoryCategory, MemoryRecord
from bearmemori.storage.vector_store import VectorStore


def _make_record(
    record_id: str, importance: int = 5, age_days: int = 0, needs_review: bool = False
) -> MemoryRecord:
    return MemoryRecord(
        id=record_id,
        category=MemoryCategory.GENERAL,
        title=f"Title {record_id}",
        content=f"Content for {record_id}",
        created_at=datetime.now(UTC) - timedelta(days=age_days),
        importance=importance,
        needs_review=needs_review,
    )


def _vs_neighbor(memory_id: str, distance: float) -> dict:
    """Vector store search result. distance: 0 = identical, 1 = orthogonal."""
    return {"id": memory_id, "document": "", "metadata": {}, "distance": distance}


@pytest.fixture
def db():
    m = MagicMock(spec=MemoryDatabase)
    m.list_all.return_value = []
    m.memory_ids_in_pending_proposals.return_value = set()
    m.merge_group_recently_rejected.return_value = False
    return m


@pytest.fixture
def vector_store():
    m = MagicMock(spec=VectorStore)
    m.search.return_value = []
    return m


@pytest.fixture
def llm():
    m = MagicMock(spec=LLMClient)
    m.reflect_memory = AsyncMock(
        return_value={"action": "keep", "new_importance": None, "reason": ""}
    )
    m.reflect_duplicates = AsyncMock(
        return_value={"is_duplicate": False, "keep_id": "", "reasoning": ""}
    )
    return m


@pytest.fixture
def bus():
    m = MagicMock()
    m.emit = AsyncMock()
    return m


@pytest.fixture
def settings(tmp_path):
    s = MagicMock()
    s.reflection_low_importance_age_days = 30
    s.reflection_needs_review_age_days = 21
    s.reflection_mid_importance_age_days = 90
    s.reflection_log_path = ""
    s.reflection_state_path = str(tmp_path / "reflection_state.json")
    s.reflection_start_hour = 2
    s.reflection_end_hour = 6
    s.reflection_poll_interval_seconds = 3600
    s.user_timezone = "UTC"
    s.reflection_duplicate_similarity_threshold = 0.85
    s.reflection_duplicate_top_k = 5
    s.reflection_reject_cooldown_days = 30
    return s


@pytest.mark.asyncio
async def test_run_skips_memories_already_in_pending_proposals(
    db, vector_store, llm, bus, settings
):
    candidate = _make_record("mem_skip", importance=2, age_days=40)
    db.list_all.return_value = [candidate]
    db.memory_ids_in_pending_proposals.return_value = {"mem_skip"}

    task = ReflectionTask(db=db, vector_store=vector_store, llm=llm, bus=bus, settings=settings)
    summary = await task.run_once(triggered_by="api")

    llm.reflect_memory.assert_not_called()
    llm.reflect_duplicates.assert_not_called()
    db.create_proposal.assert_not_called()
    assert summary["proposals_created"] == 0


def test_is_within_window_true():
    from bearmemori.core.reflection import _is_within_window

    assert _is_within_window(current_hour=3, start_hour=2, end_hour=6) is True


def test_is_within_window_false():
    from bearmemori.core.reflection import _is_within_window

    assert _is_within_window(current_hour=10, start_hour=2, end_hour=6) is False


def test_is_within_window_equal_means_no_restriction():
    from bearmemori.core.reflection import _is_within_window

    assert _is_within_window(current_hour=15, start_hour=4, end_hour=4) is True
