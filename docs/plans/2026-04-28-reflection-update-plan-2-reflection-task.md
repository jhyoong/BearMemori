# Reflection Update — Plan 2 of 3: ReflectionTask rewrite

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Prerequisite:** Plan 1 (`docs/plans/2026-04-28-reflection-update-plan-1-foundation.md`) is fully landed. The new tables, model, LLM method, and state file must exist before starting this plan.

**Goal:** Rewrite `bearmemori/core/reflection.py` so the nightly run produces proposals instead of mutating memory state. Two passes per run: a duplicate-detection pass (vector pre-filter + LLM confirmation -> `merge` proposals) and an age-based pass (existing candidate criteria + `reflect_memory` -> `archive` and `rerank` proposals).

**Architecture:** `ReflectionTask.run_once()` becomes structurally different. It loads scope (all on first run, only-new on subsequent runs), pulls a skip set of memories already referenced by pending proposals, then executes the two passes. Nothing in this plan mutates `memories.archived` or `memories.importance` — those state changes happen only in Plan 3 when a user approves a proposal.

**Tech Stack:** Python 3.12, SQLite, ChromaDB, OpenAI-compatible LLM client, pytest + pytest-asyncio. Project uses `uv`.

**Reference design doc:** `docs/plans/2026-04-28-reflection-update-design.md`

**Plan 3:** `docs/plans/2026-04-28-reflection-update-plan-3-api-webapp.md` adds REST endpoints, the webapp page, approve/reject execution, and doc updates.

---

## Working rules

- **TDD.** Write the failing test first. Run it. Implement. Run it again.
- **One commit per task.** Don't bundle.
- **After each task that touches reflection code, run:** `uv run pytest tests/test_reflection.py -v`
- **Lint before commit:** `uv run ruff check . && uv run ruff format .`
- **All commands run via `uv`:** `uv run python ...`, `uv run pytest ...`.

---

## Task 1: Replace `tests/test_reflection.py` and scaffold the new `run_once`

The current `tests/test_reflection.py` asserts the old behavior (auto-commit archive/rerank). Replace it with a fresh test file that exercises the new flow. This task lands the structural skeleton; later tasks fill in `_duplicate_pass` and `_archive_rerank_pass`.

**Files:**
- Modify: `bearmemori/core/reflection.py`
- Modify: `tests/test_reflection.py` (full rewrite)

**Step 1: Replace `tests/test_reflection.py`**

Overwrite the file with:

```python
import pytest
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

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
```

**Step 2: Run, verify the new tests fail**

```
uv run pytest tests/test_reflection.py::test_run_skips_memories_already_in_pending_proposals -v
```

Expected: FAIL — old `run_once` returns the legacy summary shape and never calls `memory_ids_in_pending_proposals`.

**Step 3: Replace `bearmemori/core/reflection.py`**

Overwrite the file with the new structure. Inner pass methods are placeholders; later tasks fill them in:

```python
import asyncio
import json
import logging
import uuid
import zoneinfo
from datetime import UTC, datetime
from pathlib import Path

from bearmemori.core.reflection_state import ReflectionState
from bearmemori.events.domain import SendMessage
from bearmemori.storage.models import MemoryRecord, ReflectionProposal

logger = logging.getLogger(__name__)


def _is_within_window(current_hour: int, start_hour: int, end_hour: int) -> bool:
    if start_hour == end_hour:
        return True
    return start_hour <= current_hour < end_hour


def _is_age_candidate(record: MemoryRecord, settings) -> bool:
    age_days = (datetime.now(UTC) - record.created_at).days
    if record.importance <= 2 and age_days >= settings.reflection_low_importance_age_days:
        return True
    if record.needs_review and age_days >= settings.reflection_needs_review_age_days:
        return True
    if 3 <= record.importance <= 7 and age_days >= settings.reflection_mid_importance_age_days:
        return True
    return False


class ReflectionTask:
    def __init__(self, db, vector_store, llm, bus, settings) -> None:
        self._db = db
        self._vector_store = vector_store
        self._llm = llm
        self._bus = bus
        self._settings = settings
        self._state = ReflectionState(settings.reflection_state_path)

    async def run_once(self, triggered_by: str = "scheduler") -> dict:
        run_id = f"ref_{uuid.uuid4().hex[:8]}"
        started_at = datetime.now(UTC)
        logger.info("Reflection run started: %s (triggered_by=%s)", run_id, triggered_by)

        last_run = self._state.load_last_run()
        all_records = self._db.list_all(limit=10000)

        if last_run is None:
            in_scope = list(all_records)
        else:
            in_scope = [r for r in all_records if r.created_at > last_run]

        skip_ids = self._db.memory_ids_in_pending_proposals()

        merge_count, consumed = await self._duplicate_pass(in_scope, all_records, skip_ids)
        archive_count, rerank_count = await self._archive_rerank_pass(
            in_scope, skip_ids, consumed
        )

        finished_at = datetime.now(UTC)
        self._state.save_last_run(finished_at)

        summary = {
            "run_id": run_id,
            "triggered_by": triggered_by,
            "started_at": started_at.isoformat(),
            "finished_at": finished_at.isoformat(),
            "scanned": len(in_scope),
            "skipped": len(skip_ids),
            "proposals_created": merge_count + archive_count + rerank_count,
            "merge_proposals": merge_count,
            "archive_proposals": archive_count,
            "rerank_proposals": rerank_count,
        }
        self._write_log(summary)
        await self._notify(summary)
        logger.info(
            "Reflection run complete: %s — proposals=%d (merge=%d archive=%d rerank=%d)",
            run_id, summary["proposals_created"], merge_count, archive_count, rerank_count,
        )
        return summary

    async def _duplicate_pass(self, in_scope, all_records, skip_ids):
        # Filled in by Task 2.
        return 0, set()

    async def _archive_rerank_pass(self, in_scope, skip_ids, consumed_ids):
        # Filled in by Task 3.
        return 0, 0

    def _write_log(self, summary: dict) -> None:
        log_path = self._settings.reflection_log_path
        if not log_path:
            return
        try:
            Path(log_path).parent.mkdir(parents=True, exist_ok=True)
            with open(log_path, "a") as f:
                f.write(json.dumps(summary) + "\n")
        except OSError as e:
            logger.error("Failed to write reflection log: %s", e)

    async def _notify(self, summary: dict) -> None:
        lines = [
            f"Reflection complete ({summary['run_id']}, triggered by {summary['triggered_by']}):",
            f"  Proposals created: {summary['proposals_created']}",
            f"    merge: {summary['merge_proposals']}",
            f"    archive: {summary['archive_proposals']}",
            f"    rerank: {summary['rerank_proposals']}",
        ]
        await self._bus.emit(SendMessage(chat_id="", text="\n".join(lines)))

    async def run(self) -> None:
        logger.info(
            "Reflection scheduler started (poll every %ds, window %d-%d)",
            self._settings.reflection_poll_interval_seconds,
            self._settings.reflection_start_hour,
            self._settings.reflection_end_hour,
        )
        while True:
            await asyncio.sleep(self._settings.reflection_poll_interval_seconds)
            try:
                tz = zoneinfo.ZoneInfo(self._settings.user_timezone)
                now_local_hour = datetime.now(tz).hour
            except Exception:
                now_local_hour = datetime.now(UTC).hour

            if _is_within_window(
                now_local_hour,
                self._settings.reflection_start_hour,
                self._settings.reflection_end_hour,
            ):
                try:
                    await self.run_once(triggered_by="scheduler")
                except Exception:
                    logger.exception("Error during reflection run")
```

**Step 4: Run all reflection tests**

```
uv run pytest tests/test_reflection.py -v
```

Expected: 4 PASS (skip-set test + 3 window helper tests).

**Step 5: Lint and commit**

```
uv run ruff check . && uv run ruff format .
git add bearmemori/core/reflection.py tests/test_reflection.py
git commit -m "refactor: scaffold propose-and-queue reflection flow"
```

---

## Task 2: Implement `_duplicate_pass`

**Files:**
- Modify: `bearmemori/core/reflection.py`
- Modify: `tests/test_reflection.py`

**Step 1: Append failing tests**

Add to `tests/test_reflection.py`:

```python
@pytest.mark.asyncio
async def test_duplicate_pass_writes_merge_proposal(db, vector_store, llm, bus, settings):
    a = _make_record("mem_a", importance=5, age_days=10)
    b = _make_record("mem_b", importance=5, age_days=5)
    db.list_all.return_value = [a, b]

    vector_store.search.return_value = [
        _vs_neighbor("mem_a", 0.0),
        _vs_neighbor("mem_b", 0.1),  # similarity 0.9 >= 0.85
    ]
    llm.reflect_duplicates = AsyncMock(
        return_value={"is_duplicate": True, "keep_id": "mem_a", "reasoning": "dup"}
    )

    task = ReflectionTask(db=db, vector_store=vector_store, llm=llm, bus=bus, settings=settings)
    summary = await task.run_once(triggered_by="api")

    assert summary["merge_proposals"] == 1
    db.create_proposal.assert_called_once()
    proposal = db.create_proposal.call_args[0][0]
    assert proposal.proposal_type == "merge"
    assert set(proposal.memory_ids) == {"mem_a", "mem_b"}
    assert proposal.recommended_keep_id == "mem_a"
    assert proposal.status == "pending"


@pytest.mark.asyncio
async def test_duplicate_pass_drops_below_threshold(db, vector_store, llm, bus, settings):
    a = _make_record("mem_a", importance=5)
    b = _make_record("mem_b", importance=5)
    db.list_all.return_value = [a, b]
    vector_store.search.return_value = [
        _vs_neighbor("mem_a", 0.0),
        _vs_neighbor("mem_b", 0.5),  # similarity 0.5 < 0.85
    ]
    task = ReflectionTask(db=db, vector_store=vector_store, llm=llm, bus=bus, settings=settings)
    summary = await task.run_once(triggered_by="api")
    assert summary["merge_proposals"] == 0


@pytest.mark.asyncio
async def test_duplicate_pass_drops_different_categories(db, vector_store, llm, bus, settings):
    a = _make_record("mem_a")
    b = _make_record("mem_b")
    b.category = MemoryCategory.EVENT
    db.list_all.return_value = [a, b]
    vector_store.search.return_value = [
        _vs_neighbor("mem_a", 0.0),
        _vs_neighbor("mem_b", 0.05),
    ]
    task = ReflectionTask(db=db, vector_store=vector_store, llm=llm, bus=bus, settings=settings)
    summary = await task.run_once(triggered_by="api")
    assert summary["merge_proposals"] == 0


@pytest.mark.asyncio
async def test_duplicate_pass_llm_says_not_duplicate(db, vector_store, llm, bus, settings):
    a = _make_record("mem_a")
    b = _make_record("mem_b")
    db.list_all.return_value = [a, b]
    vector_store.search.return_value = [
        _vs_neighbor("mem_a", 0.0),
        _vs_neighbor("mem_b", 0.05),
    ]
    llm.reflect_duplicates = AsyncMock(
        return_value={"is_duplicate": False, "keep_id": "", "reasoning": ""}
    )
    task = ReflectionTask(db=db, vector_store=vector_store, llm=llm, bus=bus, settings=settings)
    summary = await task.run_once(triggered_by="api")
    assert summary["merge_proposals"] == 0
    db.create_proposal.assert_not_called()


@pytest.mark.asyncio
async def test_duplicate_pass_skips_recently_rejected_group(db, vector_store, llm, bus, settings):
    a = _make_record("mem_a")
    b = _make_record("mem_b")
    db.list_all.return_value = [a, b]
    vector_store.search.return_value = [
        _vs_neighbor("mem_a", 0.0),
        _vs_neighbor("mem_b", 0.05),
    ]
    db.merge_group_recently_rejected.return_value = True

    task = ReflectionTask(db=db, vector_store=vector_store, llm=llm, bus=bus, settings=settings)
    summary = await task.run_once(triggered_by="api")
    assert summary["merge_proposals"] == 0
    llm.reflect_duplicates.assert_not_called()


@pytest.mark.asyncio
async def test_duplicate_pass_does_not_propose_same_group_twice(
    db, vector_store, llm, bus, settings
):
    """Visiting both A and B during the scan should still produce one merge proposal."""
    a = _make_record("mem_a")
    b = _make_record("mem_b")
    db.list_all.return_value = [a, b]
    vector_store.search.return_value = [
        _vs_neighbor("mem_a", 0.0),
        _vs_neighbor("mem_b", 0.05),
    ]
    llm.reflect_duplicates = AsyncMock(
        return_value={"is_duplicate": True, "keep_id": "mem_a", "reasoning": "dup"}
    )
    task = ReflectionTask(db=db, vector_store=vector_store, llm=llm, bus=bus, settings=settings)
    summary = await task.run_once(triggered_by="api")
    assert summary["merge_proposals"] == 1
    assert llm.reflect_duplicates.call_count == 1


@pytest.mark.asyncio
async def test_duplicate_pass_swallows_llm_failure(db, vector_store, llm, bus, settings):
    a = _make_record("mem_a")
    b = _make_record("mem_b")
    db.list_all.return_value = [a, b]
    vector_store.search.return_value = [
        _vs_neighbor("mem_a", 0.0),
        _vs_neighbor("mem_b", 0.05),
    ]
    llm.reflect_duplicates = AsyncMock(side_effect=RuntimeError("boom"))

    task = ReflectionTask(db=db, vector_store=vector_store, llm=llm, bus=bus, settings=settings)
    summary = await task.run_once(triggered_by="api")  # must not raise
    assert summary["merge_proposals"] == 0
```

**Step 2: Run, verify all the new tests fail**

```
uv run pytest tests/test_reflection.py -v -k duplicate_pass
```

Expected: FAIL — `_duplicate_pass` still returns `(0, set())`.

**Step 3: Implement `_duplicate_pass`**

Replace the placeholder body in `bearmemori/core/reflection.py`:

```python
async def _duplicate_pass(
    self,
    in_scope: list[MemoryRecord],
    all_records: list[MemoryRecord],
    skip_ids: set[str],
) -> tuple[int, set[str]]:
    threshold = self._settings.reflection_duplicate_similarity_threshold
    top_k = self._settings.reflection_duplicate_top_k
    cooldown = self._settings.reflection_reject_cooldown_days

    by_id = {r.id: r for r in all_records}
    seen_groups: set[tuple[str, ...]] = set()
    consumed: set[str] = set()
    proposals_created = 0

    for memory in in_scope:
        if memory.id in skip_ids or memory.id in consumed:
            continue

        query_text = f"{memory.title}: {memory.content}"
        try:
            neighbors = self._vector_store.search(query_text, top_k=top_k)
        except Exception as e:
            logger.warning("vector_store.search failed for %s: %s", memory.id, e)
            continue

        group_ids: set[str] = {memory.id}
        for n in neighbors:
            nid = n.get("id")
            if nid is None or nid == memory.id or nid in skip_ids:
                continue
            distance = n.get("distance")
            if distance is None:
                continue
            similarity = 1.0 - float(distance)
            if similarity < threshold:
                continue
            other = by_id.get(nid)
            if other is None or other.archived:
                continue
            if other.category != memory.category:
                continue
            group_ids.add(nid)

        if len(group_ids) < 2:
            continue

        key = tuple(sorted(group_ids))
        if key in seen_groups:
            continue
        seen_groups.add(key)

        if self._db.merge_group_recently_rejected(
            memory_ids=list(key), cooldown_days=cooldown
        ):
            continue

        records = [by_id[i] for i in key]
        try:
            decision = await self._llm.reflect_duplicates(records)
        except Exception as e:
            logger.warning("reflect_duplicates failed for %s: %s", key, e)
            continue

        if not decision.get("is_duplicate"):
            continue

        keep_id = decision.get("keep_id")
        if keep_id not in group_ids:
            keep_id = sorted(group_ids)[0]

        proposal = ReflectionProposal(
            id=f"prop_{uuid.uuid4().hex[:12]}",
            proposal_type="merge",
            status="pending",
            memory_ids=list(key),
            recommended_keep_id=keep_id,
            reasoning=decision.get("reasoning", ""),
            created_at=datetime.now(UTC),
        )
        self._db.create_proposal(proposal)
        proposals_created += 1
        consumed.update(group_ids)

    return proposals_created, consumed
```

**Step 4: Run tests**

```
uv run pytest tests/test_reflection.py -v
```

Expected: all PASS.

**Step 5: Lint and commit**

```
uv run ruff check . && uv run ruff format .
git add bearmemori/core/reflection.py tests/test_reflection.py
git commit -m "feat: duplicate detection pass writes merge proposals"
```

---

## Task 3: Implement `_archive_rerank_pass`

**Files:**
- Modify: `bearmemori/core/reflection.py`
- Modify: `tests/test_reflection.py`

**Step 1: Append failing tests**

```python
@pytest.mark.asyncio
async def test_archive_pass_writes_archive_proposal(db, vector_store, llm, bus, settings):
    a = _make_record("mem_old", importance=2, age_days=40)
    db.list_all.return_value = [a]
    vector_store.search.return_value = []  # no neighbors

    llm.reflect_memory = AsyncMock(
        return_value={"action": "archive", "new_importance": None, "reason": "obsolete"}
    )

    task = ReflectionTask(db=db, vector_store=vector_store, llm=llm, bus=bus, settings=settings)
    summary = await task.run_once(triggered_by="api")

    assert summary["archive_proposals"] == 1
    proposal = db.create_proposal.call_args[0][0]
    assert proposal.proposal_type == "archive"
    assert proposal.memory_ids == ["mem_old"]
    assert proposal.status == "pending"


@pytest.mark.asyncio
async def test_rerank_pass_writes_rerank_proposal(db, vector_store, llm, bus, settings):
    a = _make_record("mem_mid", importance=5, age_days=100)
    db.list_all.return_value = [a]
    vector_store.search.return_value = []

    llm.reflect_memory = AsyncMock(
        return_value={"action": "keep", "new_importance": 7, "reason": "still relevant"}
    )

    task = ReflectionTask(db=db, vector_store=vector_store, llm=llm, bus=bus, settings=settings)
    summary = await task.run_once(triggered_by="api")

    assert summary["rerank_proposals"] == 1
    proposal = db.create_proposal.call_args[0][0]
    assert proposal.proposal_type == "rerank"
    assert proposal.memory_ids == ["mem_mid"]
    assert proposal.recommended_importance == 7


@pytest.mark.asyncio
async def test_keep_unchanged_writes_no_proposal(db, vector_store, llm, bus, settings):
    a = _make_record("mem_keep", importance=5, age_days=100)
    db.list_all.return_value = [a]
    vector_store.search.return_value = []

    llm.reflect_memory = AsyncMock(
        return_value={"action": "keep", "new_importance": 5, "reason": "ok"}
    )

    task = ReflectionTask(db=db, vector_store=vector_store, llm=llm, bus=bus, settings=settings)
    summary = await task.run_once(triggered_by="api")
    assert summary["archive_proposals"] == 0
    assert summary["rerank_proposals"] == 0


@pytest.mark.asyncio
async def test_age_pass_skips_when_consumed_by_merge(db, vector_store, llm, bus, settings):
    """A memory in a merge proposal this run must not also get archive/rerank."""
    a = _make_record("mem_a", importance=2, age_days=40)
    b = _make_record("mem_b", importance=2, age_days=40)
    db.list_all.return_value = [a, b]
    vector_store.search.return_value = [
        _vs_neighbor("mem_a", 0.0),
        _vs_neighbor("mem_b", 0.05),
    ]
    llm.reflect_duplicates = AsyncMock(
        return_value={"is_duplicate": True, "keep_id": "mem_a", "reasoning": "dup"}
    )
    llm.reflect_memory = AsyncMock(
        return_value={"action": "archive", "new_importance": None, "reason": "old"}
    )

    task = ReflectionTask(db=db, vector_store=vector_store, llm=llm, bus=bus, settings=settings)
    summary = await task.run_once(triggered_by="api")

    assert summary["merge_proposals"] == 1
    assert summary["archive_proposals"] == 0
    llm.reflect_memory.assert_not_called()


@pytest.mark.asyncio
async def test_archive_pass_swallows_llm_failure(db, vector_store, llm, bus, settings):
    a = _make_record("mem_old", importance=2, age_days=40)
    db.list_all.return_value = [a]
    vector_store.search.return_value = []
    llm.reflect_memory = AsyncMock(side_effect=RuntimeError("boom"))

    task = ReflectionTask(db=db, vector_store=vector_store, llm=llm, bus=bus, settings=settings)
    summary = await task.run_once(triggered_by="api")
    assert summary["archive_proposals"] == 0
```

**Step 2: Run, verify fail**

```
uv run pytest tests/test_reflection.py -v -k "archive_pass or rerank_pass or keep_unchanged or consumed_by_merge"
```

Expected: FAIL.

**Step 3: Implement `_archive_rerank_pass`**

```python
async def _archive_rerank_pass(
    self,
    in_scope: list[MemoryRecord],
    skip_ids: set[str],
    consumed_ids: set[str],
) -> tuple[int, int]:
    archive_count = 0
    rerank_count = 0

    for record in in_scope:
        if record.id in skip_ids or record.id in consumed_ids:
            continue
        if not _is_age_candidate(record, self._settings):
            continue

        try:
            decision = await self._llm.reflect_memory(record)
        except Exception as e:
            logger.warning("reflect_memory failed for %s: %s", record.id, e)
            continue

        action = decision.get("action", "keep")
        new_importance = decision.get("new_importance")
        reason = decision.get("reason", "")

        if action == "archive":
            proposal = ReflectionProposal(
                id=f"prop_{uuid.uuid4().hex[:12]}",
                proposal_type="archive",
                status="pending",
                memory_ids=[record.id],
                reasoning=reason,
                created_at=datetime.now(UTC),
            )
            self._db.create_proposal(proposal)
            archive_count += 1
        elif new_importance is not None:
            try:
                clamped = max(1, min(10, int(new_importance)))
            except (TypeError, ValueError):
                continue
            if clamped != record.importance:
                proposal = ReflectionProposal(
                    id=f"prop_{uuid.uuid4().hex[:12]}",
                    proposal_type="rerank",
                    status="pending",
                    memory_ids=[record.id],
                    recommended_importance=clamped,
                    reasoning=reason,
                    created_at=datetime.now(UTC),
                )
                self._db.create_proposal(proposal)
                rerank_count += 1

    return archive_count, rerank_count
```

**Step 4: Run tests**

```
uv run pytest tests/test_reflection.py -v
```

Expected: all PASS.

**Step 5: Lint and commit**

```
uv run ruff check . && uv run ruff format .
git add bearmemori/core/reflection.py tests/test_reflection.py
git commit -m "feat: archive/rerank pass writes proposals"
```

---

## Task 4: Verify scope-by-last-run behavior

The `last_run` filter is implemented in `run_once` already, but is not yet covered by tests. Add tests to lock in the behavior.

**Files:**
- Modify: `tests/test_reflection.py`

**Step 1: Append failing tests**

```python
import json as _json


@pytest.mark.asyncio
async def test_run_persists_last_run_timestamp(
    db, vector_store, llm, bus, settings, tmp_path
):
    db.list_all.return_value = []
    task = ReflectionTask(db=db, vector_store=vector_store, llm=llm, bus=bus, settings=settings)
    await task.run_once(triggered_by="api")

    state_path = tmp_path / "reflection_state.json"
    assert state_path.exists()
    data = _json.loads(state_path.read_text())
    assert "last_run" in data


@pytest.mark.asyncio
async def test_subsequent_run_only_scans_new_memories(
    db, vector_store, llm, bus, settings, tmp_path
):
    """First run sets last_run to now. Second run should scan zero memories
    if the existing memory was created before that timestamp."""
    old = _make_record("mem_old", importance=2, age_days=40)
    db.list_all.return_value = [old]

    task = ReflectionTask(db=db, vector_store=vector_store, llm=llm, bus=bus, settings=settings)
    first = await task.run_once(triggered_by="api")
    assert first["scanned"] == 1

    db.create_proposal.reset_mock()
    llm.reflect_memory.reset_mock()

    second = await task.run_once(triggered_by="api")
    assert second["scanned"] == 0
    llm.reflect_memory.assert_not_called()
```

**Step 2: Run, verify**

```
uv run pytest tests/test_reflection.py -v -k "last_run or subsequent_run"
```

If they already pass: skip Step 3.
If they fail (e.g. because `last_run` filter has a bug), fix `run_once` so they pass.

**Step 3: Commit**

```
uv run ruff check . && uv run ruff format .
git add tests/test_reflection.py
git commit -m "test: lock in last_run scope behavior"
```

---

## Task 5: Sanity check the full test suite and the import path

After replacing the reflection task, other tests that touched the old summary shape may now fail.

**Step 1: Run everything**

```
uv run pytest -v
```

If any test fails, investigate. Likely culprits:
- `tests/mcp/test_reflection_tool.py` may reference the old summary keys (`archived`, `reranked`, `kept_unchanged`, `decisions`). Update assertions to match the new shape (`proposals_created`, `merge_proposals`, `archive_proposals`, `rerank_proposals`, `scanned`, `skipped`).
- Anything else that called `ReflectionTask` with positional args or expected the old behavior.

Fix per failing test, commit per fix:

```
git add <files>
git commit -m "test: align <name> with proposal-based reflection"
```

**Step 2: Smoke import**

```
uv run python -c "from bearmemori.core.reflection import ReflectionTask; print('imports ok')"
```

Expected: prints `imports ok`.

**Step 3: Boot the app once (quick smoke)**

If a `.env` is set up locally with at least `API_ONLY_MODE=true`:

```
uv run python -m bearmemori --help 2>&1 | head -20
```

Expected: CLI help renders without crash. Skip this step if no `.env` is configured.

---

## End of Plan 2

After Plan 2:
- `ReflectionTask.run_once()` writes `merge`, `archive`, and `rerank` proposals to `reflection_proposals`.
- No memory state is mutated by reflection.
- Skip set, dedupe, cooldown, scope-by-last-run, and merge-vs-age precedence are all correct.
- Tests cover happy and failure paths.

But: nothing reads the proposals yet. The user has no way to approve or reject them. Plan 3 wires REST endpoints, the webapp page, and the execution semantics that finally apply approved proposals to memory state.

**Next:** `docs/plans/2026-04-28-reflection-update-plan-3-api-webapp.md`.
