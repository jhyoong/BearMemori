import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from bearmemori.core.reflection import ReflectionTask
from bearmemori.llm.client import LLMClient
from bearmemori.storage.database import MemoryDatabase
from bearmemori.storage.models import MemoryCategory, MemoryRecord
from bearmemori.storage.vector_store import VectorStore


def _make_record(
    record_id: str, importance: int, age_days: int, needs_review: bool = False
) -> MemoryRecord:
    return MemoryRecord(
        id=record_id,
        category=MemoryCategory.GENERAL,
        title=f"Memory {record_id}",
        content="Some content",
        created_at=datetime.now(UTC) - timedelta(days=age_days),
        importance=importance,
        needs_review=needs_review,
    )


@pytest.fixture
def db():
    return MagicMock(spec=MemoryDatabase)


@pytest.fixture
def vector_store():
    return MagicMock(spec=VectorStore)


@pytest.fixture
def llm():
    return MagicMock(spec=LLMClient)


@pytest.fixture
def bus():
    m = MagicMock()
    m.emit = AsyncMock()
    return m


@pytest.fixture
def settings():
    s = MagicMock()
    s.reflection_low_importance_age_days = 30
    s.reflection_needs_review_age_days = 21
    s.reflection_mid_importance_age_days = 90
    s.reflection_log_path = ""  # empty = no file write in tests
    s.reflection_start_hour = 2
    s.reflection_end_hour = 6
    s.reflection_poll_interval_seconds = 3600
    s.user_timezone = "UTC"
    return s


@pytest.mark.asyncio
async def test_run_once_archives_low_importance_old_memory(
    db, vector_store, llm, bus, settings, tmp_path
):
    settings.reflection_log_path = str(tmp_path / "reflection.log")
    candidate = _make_record("mem_001", importance=2, age_days=40)
    db.list_all.return_value = [candidate]

    llm.reflect_memory = AsyncMock(
        return_value={
            "action": "archive",
            "new_importance": None,
            "reason": "Old and trivial",
        }
    )

    task = ReflectionTask(db=db, vector_store=vector_store, llm=llm, bus=bus, settings=settings)
    summary = await task.run_once(triggered_by="api")

    assert summary["archived"] == 1
    assert summary["kept_unchanged"] == 0
    db.update.assert_called_once()
    updated_record = db.update.call_args[0][0]
    assert updated_record.archived is True


@pytest.mark.asyncio
async def test_run_once_reranks_mid_importance_old_memory(
    db, vector_store, llm, bus, settings, tmp_path
):
    settings.reflection_log_path = str(tmp_path / "reflection.log")
    candidate = _make_record("mem_002", importance=5, age_days=100)
    db.list_all.return_value = [candidate]

    llm.reflect_memory = AsyncMock(
        return_value={
            "action": "keep",
            "new_importance": 7,
            "reason": "Still relevant",
        }
    )

    task = ReflectionTask(db=db, vector_store=vector_store, llm=llm, bus=bus, settings=settings)
    summary = await task.run_once(triggered_by="api")

    assert summary["reranked"] == 1
    db.update.assert_called_once()
    updated_record = db.update.call_args[0][0]
    assert updated_record.importance == 7
    assert updated_record.archived is False


@pytest.mark.asyncio
async def test_run_once_skips_high_importance_recent_memory(
    db, vector_store, llm, bus, settings, tmp_path
):
    settings.reflection_log_path = str(tmp_path / "reflection.log")
    # importance=8, only 10 days old — should not be a candidate
    non_candidate = _make_record("mem_003", importance=8, age_days=10)
    db.list_all.return_value = [non_candidate]

    llm.reflect_memory = AsyncMock()

    task = ReflectionTask(db=db, vector_store=vector_store, llm=llm, bus=bus, settings=settings)
    summary = await task.run_once(triggered_by="api")

    assert summary["candidates_evaluated"] == 0
    llm.reflect_memory.assert_not_called()


@pytest.mark.asyncio
async def test_run_once_writes_log_entry(db, vector_store, llm, bus, settings, tmp_path):
    log_path = tmp_path / "reflection.log"
    settings.reflection_log_path = str(log_path)

    candidate = _make_record("mem_004", importance=2, age_days=40)
    db.list_all.return_value = [candidate]
    llm.reflect_memory = AsyncMock(
        return_value={
            "action": "archive",
            "new_importance": None,
            "reason": "Obsolete",
        }
    )

    task = ReflectionTask(db=db, vector_store=vector_store, llm=llm, bus=bus, settings=settings)
    await task.run_once(triggered_by="scheduler")

    assert log_path.exists()
    entry = json.loads(log_path.read_text().strip())
    assert entry["triggered_by"] == "scheduler"
    assert entry["archived"] == 1
    assert len(entry["decisions"]) == 1
    assert entry["decisions"][0]["memory_id"] == "mem_004"


@pytest.mark.asyncio
async def test_run_once_needs_review_old_memory_is_candidate(
    db, vector_store, llm, bus, settings, tmp_path
):
    settings.reflection_log_path = str(tmp_path / "reflection.log")
    # needs_review=True, 25 days old — threshold is 21
    candidate = _make_record("mem_005", importance=6, age_days=25, needs_review=True)
    db.list_all.return_value = [candidate]
    llm.reflect_memory = AsyncMock(
        return_value={
            "action": "keep",
            "new_importance": None,
            "reason": "Still valid",
        }
    )

    task = ReflectionTask(db=db, vector_store=vector_store, llm=llm, bus=bus, settings=settings)
    summary = await task.run_once(triggered_by="api")

    assert summary["candidates_evaluated"] == 1


def test_is_within_window_true():
    from bearmemori.core.reflection import _is_within_window

    # 3am is within 2-6 window
    assert _is_within_window(current_hour=3, start_hour=2, end_hour=6) is True


def test_is_within_window_false():
    from bearmemori.core.reflection import _is_within_window

    # 10am is outside 2-6 window
    assert _is_within_window(current_hour=10, start_hour=2, end_hour=6) is False


def test_is_within_window_equals_start_equals_end_always_true():
    from bearmemori.core.reflection import _is_within_window

    # start == end means no restriction
    assert _is_within_window(current_hour=15, start_hour=4, end_hour=4) is True
