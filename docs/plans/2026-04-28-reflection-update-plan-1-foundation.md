# Reflection Update — Plan 1 of 3: Foundation primitives

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build the storage primitives, LLM helper, and state persistence that the new propose-and-queue reflection flow depends on. Plan 1 does NOT touch `ReflectionTask` itself — that's Plan 2.

**Architecture:** Reflection will become a proposal generator. Plan 1 lays the foundation: config flags, the `ReflectionProposal` model, two new SQLite tables (`reflection_proposals` and a helper join table), CRUD methods, the new `LLMClient.reflect_duplicates()` method, and a small state file for last-run timestamp persistence.

**Tech Stack:** Python 3.12, SQLite, ChromaDB, OpenAI-compatible LLM client, pytest + pytest-asyncio. Project uses `uv`.

**Reference design doc:** `docs/plans/2026-04-28-reflection-update-design.md`

**Plan 2:** `docs/plans/2026-04-28-reflection-update-plan-2-reflection-task.md` rewrites `ReflectionTask` to consume the primitives built here.

**Plan 3:** `docs/plans/2026-04-28-reflection-update-plan-3-api-webapp.md` adds REST endpoints, the webapp `/proposals` page, approve/reject execution, and doc updates.

---

## Working rules

- **TDD.** Write the failing test first. Run it. Implement. Run it again.
- **One commit per task.** Don't bundle.
- **Run all reflection tests after each task that touches reflection code:** `uv run pytest tests/test_reflection.py tests/test_reflection_proposals.py tests/test_reflection_config.py -v`
- **Lint before commit:** `uv run ruff check . && uv run ruff format .`
- **Activate venv-style:** the project uses `uv`. Run python via `uv run python ...` and tests via `uv run pytest ...`.

---

## Task 1: Add new settings to `Settings`

**Files:**
- Modify: `bearmemori/config.py`
- Modify: `tests/test_reflection_config.py`
- Modify: `.env.example`

**Step 1: Write the failing test**

Add to `tests/test_reflection_config.py` (create the file if it does not exist; if it does, append):

```python
from bearmemori.config import Settings


def _settings_with_required(**overrides):
    return Settings(api_only_mode=True, **overrides)


def test_reflection_duplicate_settings_have_defaults():
    s = _settings_with_required()
    assert s.reflection_duplicate_similarity_threshold == 0.85
    assert s.reflection_duplicate_top_k == 5
    assert s.reflection_reject_cooldown_days == 30
    assert s.reflection_state_path == "data/reflection_state.json"


def test_reflection_duplicate_settings_can_be_overridden(monkeypatch):
    monkeypatch.setenv("REFLECTION_DUPLICATE_SIMILARITY_THRESHOLD", "0.9")
    monkeypatch.setenv("REFLECTION_DUPLICATE_TOP_K", "10")
    s = _settings_with_required()
    assert s.reflection_duplicate_similarity_threshold == 0.9
    assert s.reflection_duplicate_top_k == 10
```

**Step 2: Run the test, verify it fails**

```
uv run pytest tests/test_reflection_config.py::test_reflection_duplicate_settings_have_defaults -v
```

Expected: FAIL — `AttributeError` on the new attribute names.

**Step 3: Add the four settings to `bearmemori/config.py`**

Insert after `reflection_log_path: str = "data/reflection.log"` (currently line 44):

```python
reflection_duplicate_similarity_threshold: float = 0.85
reflection_duplicate_top_k: int = 5
reflection_reject_cooldown_days: int = 30
reflection_state_path: str = "data/reflection_state.json"
```

**Step 4: Run the tests, verify pass**

```
uv run pytest tests/test_reflection_config.py -v
```

Expected: PASS for both new tests.

**Step 5: Update `.env.example`**

Append to the reflection block:

```
REFLECTION_DUPLICATE_SIMILARITY_THRESHOLD=0.85
REFLECTION_DUPLICATE_TOP_K=5
REFLECTION_REJECT_COOLDOWN_DAYS=30
REFLECTION_STATE_PATH=data/reflection_state.json
```

**Step 6: Lint and commit**

```
uv run ruff check . && uv run ruff format .
git add bearmemori/config.py tests/test_reflection_config.py .env.example
git commit -m "feat: add reflection duplicate-detection settings"
```

---

## Task 2: Add `ReflectionProposal` model

**Files:**
- Modify: `bearmemori/storage/models.py`
- Create: `tests/test_reflection_models.py`

**Step 1: Write the failing test**

Create `tests/test_reflection_models.py`:

```python
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
```

**Step 2: Run the test, verify it fails**

```
uv run pytest tests/test_reflection_models.py -v
```

Expected: FAIL — `ImportError: cannot import name 'ReflectionProposal'`.

**Step 3: Add the model**

Append to `bearmemori/storage/models.py`:

```python
class ReflectionProposal(BaseModel):
    id: str
    proposal_type: Literal["merge", "archive", "rerank"]
    status: Literal["pending", "approved", "rejected"]
    memory_ids: list[str]
    recommended_keep_id: str | None = None
    recommended_importance: int | None = None
    reasoning: str
    resolution_note: str | None = None
    created_at: datetime
    resolved_at: datetime | None = None
```

**Step 4: Run tests**

```
uv run pytest tests/test_reflection_models.py -v
```

Expected: PASS.

**Step 5: Lint and commit**

```
uv run ruff check . && uv run ruff format .
git add bearmemori/storage/models.py tests/test_reflection_models.py
git commit -m "feat: add ReflectionProposal model"
```

---

## Task 3: Add proposal tables to the database

**Files:**
- Modify: `bearmemori/storage/database.py`

**Step 1: Write a smoke test for the new tables**

Append to `tests/test_reflection_models.py` (or create `tests/test_reflection_proposals.py` — use the latter going forward):

Create `tests/test_reflection_proposals.py`:

```python
import sqlite3

from bearmemori.storage.database import MemoryDatabase


def _new_db(tmp_path):
    db = MemoryDatabase(str(tmp_path / "test.db"))
    db.initialize()
    return db


def test_reflection_proposal_tables_exist(tmp_path):
    db = _new_db(tmp_path)
    conn = sqlite3.connect(str(tmp_path / "test.db"))
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name IN ('reflection_proposals', 'reflection_proposal_memories')"
    ).fetchall()
    names = {r[0] for r in rows}
    assert "reflection_proposals" in names
    assert "reflection_proposal_memories" in names
```

**Step 2: Run, verify fail**

```
uv run pytest tests/test_reflection_proposals.py::test_reflection_proposal_tables_exist -v
```

Expected: FAIL — tables don't exist.

**Step 3: Create the tables**

In `bearmemori/storage/database.py`, inside `initialize()`, after the `audit_log` index creation block and **before** `self._conn.commit()` (currently line 117), insert:

```python
self._conn.execute("""
    CREATE TABLE IF NOT EXISTS reflection_proposals (
        id TEXT PRIMARY KEY,
        proposal_type TEXT NOT NULL,
        status TEXT NOT NULL,
        memory_ids TEXT NOT NULL,
        recommended_keep_id TEXT,
        recommended_importance INTEGER,
        reasoning TEXT NOT NULL,
        resolution_note TEXT,
        created_at TEXT NOT NULL,
        resolved_at TEXT
    )
""")
self._conn.execute("""
    CREATE INDEX IF NOT EXISTS idx_reflection_proposals_status
    ON reflection_proposals (status)
""")
self._conn.execute("""
    CREATE TABLE IF NOT EXISTS reflection_proposal_memories (
        proposal_id TEXT NOT NULL,
        memory_id TEXT NOT NULL,
        PRIMARY KEY (proposal_id, memory_id),
        FOREIGN KEY (proposal_id) REFERENCES reflection_proposals(id) ON DELETE CASCADE
    )
""")
self._conn.execute("""
    CREATE INDEX IF NOT EXISTS idx_reflection_proposal_memories_memory
    ON reflection_proposal_memories (memory_id)
""")
```

Also enable foreign keys on connect. In `initialize()`, just after `self._conn.execute("PRAGMA journal_mode=WAL")` (currently line 33), add:

```python
self._conn.execute("PRAGMA foreign_keys=ON")
```

**Step 4: Run, verify pass**

```
uv run pytest tests/test_reflection_proposals.py -v
```

Expected: PASS.

Run full DB tests to confirm nothing else broke:

```
uv run pytest tests/ -k "database or reflection" -v
```

Expected: all PASS.

**Step 5: Lint and commit**

```
uv run ruff check . && uv run ruff format .
git add bearmemori/storage/database.py tests/test_reflection_proposals.py
git commit -m "feat: add reflection_proposals tables"
```

---

## Task 4: Add `create_proposal` CRUD method

**Files:**
- Modify: `bearmemori/storage/database.py`
- Modify: `tests/test_reflection_proposals.py`

**Step 1: Write the failing test**

Append to `tests/test_reflection_proposals.py`:

```python
from datetime import UTC, datetime

from bearmemori.storage.models import ReflectionProposal


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
```

This test will reference `db.create_proposal`, `db.get_proposal`, and `db.memory_ids_in_pending_proposals`. They don't exist yet.

**Step 2: Run, verify fail**

```
uv run pytest tests/test_reflection_proposals.py::test_create_proposal_persists_row_and_helper -v
```

Expected: FAIL — `AttributeError: 'MemoryDatabase' object has no attribute 'create_proposal'`.

**Step 3: Implement the three methods**

In `bearmemori/storage/database.py`, add at the bottom of `MemoryDatabase`:

```python
def create_proposal(self, proposal) -> None:
    """Insert a ReflectionProposal and its memory_id rows in one transaction."""
    self._conn.execute(
        """INSERT INTO reflection_proposals
           (id, proposal_type, status, memory_ids, recommended_keep_id,
            recommended_importance, reasoning, resolution_note,
            created_at, resolved_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            proposal.id,
            proposal.proposal_type,
            proposal.status,
            json.dumps(proposal.memory_ids),
            proposal.recommended_keep_id,
            proposal.recommended_importance,
            proposal.reasoning,
            proposal.resolution_note,
            proposal.created_at.isoformat(),
            proposal.resolved_at.isoformat() if proposal.resolved_at else None,
        ),
    )
    for memory_id in proposal.memory_ids:
        self._conn.execute(
            """INSERT INTO reflection_proposal_memories (proposal_id, memory_id)
               VALUES (?, ?)""",
            (proposal.id, memory_id),
        )
    self._conn.commit()


def _row_to_proposal(self, row):
    from bearmemori.storage.models import ReflectionProposal

    return ReflectionProposal(
        id=row["id"],
        proposal_type=row["proposal_type"],
        status=row["status"],
        memory_ids=json.loads(row["memory_ids"]),
        recommended_keep_id=row["recommended_keep_id"],
        recommended_importance=row["recommended_importance"],
        reasoning=row["reasoning"],
        resolution_note=row["resolution_note"],
        created_at=datetime.fromisoformat(row["created_at"]),
        resolved_at=datetime.fromisoformat(row["resolved_at"])
        if row["resolved_at"]
        else None,
    )


def get_proposal(self, proposal_id: str):
    row = self._conn.execute(
        "SELECT * FROM reflection_proposals WHERE id = ?", (proposal_id,)
    ).fetchone()
    return self._row_to_proposal(row) if row else None


def memory_ids_in_pending_proposals(self) -> set[str]:
    rows = self._conn.execute(
        """SELECT DISTINCT m.memory_id
           FROM reflection_proposal_memories m
           JOIN reflection_proposals p ON p.id = m.proposal_id
           WHERE p.status = 'pending'"""
    ).fetchall()
    return {r["memory_id"] for r in rows}
```

**Step 4: Run tests**

```
uv run pytest tests/test_reflection_proposals.py -v
```

Expected: PASS.

**Step 5: Lint and commit**

```
uv run ruff check . && uv run ruff format .
git add bearmemori/storage/database.py tests/test_reflection_proposals.py
git commit -m "feat: create_proposal, get_proposal, memory_ids_in_pending_proposals"
```

---

## Task 5: Add `list_proposals` and `count_proposals`

**Files:**
- Modify: `bearmemori/storage/database.py`
- Modify: `tests/test_reflection_proposals.py`

**Step 1: Write the failing tests**

Append to `tests/test_reflection_proposals.py`:

```python
def test_list_proposals_filters_by_status_and_type(tmp_path):
    db = _new_db(tmp_path)
    db.create_proposal(_make_merge_proposal(["mem_a", "mem_b"]))

    archive_p = ReflectionProposal(
        id="prop_arc_1",
        proposal_type="archive",
        status="pending",
        memory_ids=["mem_x"],
        reasoning="old",
        created_at=datetime.now(UTC),
    )
    db.create_proposal(archive_p)

    pending = db.list_proposals(status="pending")
    assert len(pending) == 2
    pending_merge = db.list_proposals(status="pending", proposal_type="merge")
    assert len(pending_merge) == 1
    assert pending_merge[0].proposal_type == "merge"


def test_count_proposals(tmp_path):
    db = _new_db(tmp_path)
    db.create_proposal(_make_merge_proposal(["mem_a", "mem_b"]))
    assert db.count_proposals(status="pending") == 1
    assert db.count_proposals(status="approved") == 0
```

**Step 2: Run, verify fail**

```
uv run pytest tests/test_reflection_proposals.py::test_list_proposals_filters_by_status_and_type -v
```

Expected: FAIL.

**Step 3: Add `list_proposals` and `count_proposals`**

In `bearmemori/storage/database.py`:

```python
def list_proposals(
    self,
    status: str | None = None,
    proposal_type: str | None = None,
    offset: int = 0,
    limit: int = 50,
) -> list:
    clauses: list[str] = []
    params: list = []
    if status is not None:
        clauses.append("status = ?")
        params.append(status)
    if proposal_type is not None:
        clauses.append("proposal_type = ?")
        params.append(proposal_type)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    params.extend([limit, offset])
    rows = self._conn.execute(
        f"SELECT * FROM reflection_proposals{where} "
        f"ORDER BY created_at DESC LIMIT ? OFFSET ?",
        params,
    ).fetchall()
    return [self._row_to_proposal(r) for r in rows]


def count_proposals(self, status: str | None = None) -> int:
    if status is None:
        row = self._conn.execute(
            "SELECT COUNT(*) FROM reflection_proposals"
        ).fetchone()
    else:
        row = self._conn.execute(
            "SELECT COUNT(*) FROM reflection_proposals WHERE status = ?",
            (status,),
        ).fetchone()
    return row[0]
```

**Step 4: Run tests**

```
uv run pytest tests/test_reflection_proposals.py -v
```

Expected: PASS.

**Step 5: Lint and commit**

```
uv run ruff check . && uv run ruff format .
git add bearmemori/storage/database.py tests/test_reflection_proposals.py
git commit -m "feat: list_proposals and count_proposals"
```

---

## Task 6: Add proposal status update method

**Files:**
- Modify: `bearmemori/storage/database.py`
- Modify: `tests/test_reflection_proposals.py`

**Step 1: Write the failing test**

Append to `tests/test_reflection_proposals.py`:

```python
def test_resolve_proposal_sets_status_and_resolved_at(tmp_path):
    db = _new_db(tmp_path)
    db.create_proposal(_make_merge_proposal(["mem_a", "mem_b"]))

    db.resolve_proposal("prop_merge_1", status="approved", note=None)
    fetched = db.get_proposal("prop_merge_1")
    assert fetched.status == "approved"
    assert fetched.resolved_at is not None
    assert fetched.resolution_note is None


def test_resolve_proposal_with_note(tmp_path):
    db = _new_db(tmp_path)
    db.create_proposal(_make_merge_proposal(["mem_a", "mem_b"]))

    db.resolve_proposal("prop_merge_1", status="rejected", note="not duplicates")
    fetched = db.get_proposal("prop_merge_1")
    assert fetched.status == "rejected"
    assert fetched.resolution_note == "not duplicates"


def test_resolve_proposal_removes_from_pending_set(tmp_path):
    db = _new_db(tmp_path)
    db.create_proposal(_make_merge_proposal(["mem_a", "mem_b"]))
    db.resolve_proposal("prop_merge_1", status="approved", note=None)
    assert db.memory_ids_in_pending_proposals() == set()
```

**Step 2: Run, verify fail**

```
uv run pytest tests/test_reflection_proposals.py::test_resolve_proposal_sets_status_and_resolved_at -v
```

Expected: FAIL — no `resolve_proposal` method.

**Step 3: Implement**

In `bearmemori/storage/database.py`:

```python
def resolve_proposal(self, proposal_id: str, status: str, note: str | None) -> None:
    self._conn.execute(
        """UPDATE reflection_proposals
           SET status = ?, resolved_at = ?, resolution_note = ?
           WHERE id = ?""",
        (status, datetime.now(UTC).isoformat(), note, proposal_id),
    )
    self._conn.commit()
```

**Step 4: Run tests**

```
uv run pytest tests/test_reflection_proposals.py -v
```

Expected: PASS.

**Step 5: Lint and commit**

```
uv run ruff check . && uv run ruff format .
git add bearmemori/storage/database.py tests/test_reflection_proposals.py
git commit -m "feat: resolve_proposal updates status and timestamp"
```

---

## Task 7: Add cooldown lookup for rejected merge groups

**Files:**
- Modify: `bearmemori/storage/database.py`
- Modify: `tests/test_reflection_proposals.py`

This supports "don't re-propose a merge group that was rejected within N days."

**Step 1: Write the failing test**

```python
from datetime import timedelta


def test_recently_rejected_merge_group_lookup(tmp_path):
    db = _new_db(tmp_path)
    db.create_proposal(_make_merge_proposal(["mem_a", "mem_b"]))
    db.resolve_proposal("prop_merge_1", status="rejected", note=None)

    # exact same group: should be flagged as recently rejected
    assert db.merge_group_recently_rejected(
        memory_ids=["mem_a", "mem_b"], cooldown_days=30
    ) is True

    # different group: not flagged
    assert db.merge_group_recently_rejected(
        memory_ids=["mem_a", "mem_x"], cooldown_days=30
    ) is False
```

**Step 2: Run, verify fail**

```
uv run pytest tests/test_reflection_proposals.py::test_recently_rejected_merge_group_lookup -v
```

Expected: FAIL.

**Step 3: Implement**

The match is on the exact set of memory IDs for `proposal_type='merge'` rejected within the cutoff. The simplest correct implementation: find rejected merge proposals within the window, fetch their `memory_ids`, compare as sets in Python.

```python
def merge_group_recently_rejected(
    self, memory_ids: list[str], cooldown_days: int
) -> bool:
    cutoff = (
        datetime.now(UTC) - timedelta(days=cooldown_days)
    ).isoformat()
    rows = self._conn.execute(
        """SELECT memory_ids FROM reflection_proposals
           WHERE proposal_type = 'merge'
             AND status = 'rejected'
             AND resolved_at IS NOT NULL
             AND resolved_at >= ?""",
        (cutoff,),
    ).fetchall()
    target = set(memory_ids)
    for row in rows:
        if set(json.loads(row["memory_ids"])) == target:
            return True
    return False
```

**Step 4: Run tests**

```
uv run pytest tests/test_reflection_proposals.py -v
```

Expected: PASS.

**Step 5: Lint and commit**

```
uv run ruff check . && uv run ruff format .
git add bearmemori/storage/database.py tests/test_reflection_proposals.py
git commit -m "feat: merge_group_recently_rejected lookup"
```

---

## Task 8: Add `reflect_duplicates` method to `LLMClient`

**Files:**
- Modify: `bearmemori/llm/client.py`
- Create: `tests/test_reflect_duplicates.py`

**Step 1: Write the failing test**

Create `tests/test_reflect_duplicates.py`:

```python
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bearmemori.llm.client import LLMClient
from bearmemori.storage.models import MemoryCategory, MemoryRecord


def _make_record(record_id: str, title: str, content: str) -> MemoryRecord:
    return MemoryRecord(
        id=record_id,
        category=MemoryCategory.GENERAL,
        title=title,
        content=content,
        created_at=datetime.now(UTC),
        importance=5,
    )


def _mock_openai(content: str):
    msg = SimpleNamespace(content=content, reasoning_content=None)
    choice = SimpleNamespace(message=msg)
    response = SimpleNamespace(choices=[choice])

    fake = SimpleNamespace()
    fake.chat = SimpleNamespace()
    fake.chat.completions = SimpleNamespace()
    fake.chat.completions.create = AsyncMock(return_value=response)
    return fake


@pytest.mark.asyncio
async def test_reflect_duplicates_returns_parsed_json():
    fake = _mock_openai(
        '{"is_duplicate": true, "keep_id": "mem_a", "reasoning": "Same fact."}'
    )
    client = LLMClient(base_url="x", model="m", _client=fake)
    group = [
        _make_record("mem_a", "Pizza preference", "User likes pepperoni"),
        _make_record("mem_b", "Pizza pref", "User prefers pepperoni"),
    ]
    result = await client.reflect_duplicates(group)
    assert result["is_duplicate"] is True
    assert result["keep_id"] == "mem_a"
    assert "Same fact" in result["reasoning"]


@pytest.mark.asyncio
async def test_reflect_duplicates_handles_negative():
    fake = _mock_openai(
        '{"is_duplicate": false, "keep_id": "", "reasoning": "Different topics."}'
    )
    client = LLMClient(base_url="x", model="m", _client=fake)
    group = [
        _make_record("mem_a", "A", "alpha"),
        _make_record("mem_b", "B", "beta"),
    ]
    result = await client.reflect_duplicates(group)
    assert result["is_duplicate"] is False
```

**Step 2: Run, verify fail**

```
uv run pytest tests/test_reflect_duplicates.py -v
```

Expected: FAIL — `AttributeError: 'LLMClient' object has no attribute 'reflect_duplicates'`.

**Step 3: Add the prompt and method**

In `bearmemori/llm/client.py`, after `_REFLECT_SYSTEM_PROMPT` (around line 217) add:

```python
_REFLECT_DUPLICATES_SYSTEM_PROMPT = """\
You are a memory deduplication agent. The following memories were flagged as candidate \
duplicates by similarity scan. Decide whether they describe the same fact, event, or entity.

If they are duplicates, choose which memory to keep. Prefer the most complete, most recent, \
and highest-importance memory. The other memories will be archived.

Respond with a single valid JSON object and nothing else. No explanation, no commentary, \
no markdown formatting.

{"is_duplicate": <true|false>, "keep_id": "<id of memory to keep, or empty string if not duplicates>", "reasoning": "<one-sentence explanation>"}
"""
```

Then add the method on `LLMClient` (after `reflect_memory`):

```python
async def reflect_duplicates(self, group) -> dict:
    from datetime import UTC, datetime

    parts = []
    for r in group:
        age_days = (datetime.now(UTC) - r.created_at).days
        parts.append(
            f"- id: {r.id}\n"
            f"  title: {r.title}\n"
            f"  category: {r.category.value}\n"
            f"  content: {r.content}\n"
            f"  tags: {', '.join(r.tags) if r.tags else 'none'}\n"
            f"  importance: {r.importance}/10\n"
            f"  age_days: {age_days}"
        )
    user_text = "Candidate duplicate group:\n" + "\n".join(parts)
    response = await self._client.chat.completions.create(
        model=self._model,
        messages=[
            {"role": "system", "content": _REFLECT_DUPLICATES_SYSTEM_PROMPT},
            {"role": "user", "content": user_text},
        ],
        temperature=0.1,
    )
    raw = _get_content(response.choices[0].message)
    logger.debug("Reflect duplicates raw output: %s", raw)
    return extract_json(raw)
```

**Step 4: Run tests**

```
uv run pytest tests/test_reflect_duplicates.py -v
```

Expected: PASS.

**Step 5: Lint and commit**

```
uv run ruff check . && uv run ruff format .
git add bearmemori/llm/client.py tests/test_reflect_duplicates.py
git commit -m "feat: add LLMClient.reflect_duplicates"
```

---

## Task 9: Add reflection state file (last_run timestamp)

**Files:**
- Create: `bearmemori/core/reflection_state.py`
- Create: `tests/test_reflection_state.py`

**Step 1: Write the failing test**

Create `tests/test_reflection_state.py`:

```python
from datetime import UTC, datetime

from bearmemori.core.reflection_state import ReflectionState


def test_load_returns_none_when_missing(tmp_path):
    state = ReflectionState(str(tmp_path / "state.json"))
    assert state.load_last_run() is None


def test_save_then_load_roundtrip(tmp_path):
    state = ReflectionState(str(tmp_path / "state.json"))
    now = datetime.now(UTC)
    state.save_last_run(now)
    loaded = state.load_last_run()
    assert loaded is not None
    assert loaded.isoformat() == now.isoformat()


def test_save_creates_parent_dirs(tmp_path):
    nested = tmp_path / "deep" / "deeper" / "state.json"
    state = ReflectionState(str(nested))
    state.save_last_run(datetime.now(UTC))
    assert nested.exists()
```

**Step 2: Run, verify fail**

```
uv run pytest tests/test_reflection_state.py -v
```

Expected: FAIL — module does not exist.

**Step 3: Implement**

Create `bearmemori/core/reflection_state.py`:

```python
import json
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


class ReflectionState:
    def __init__(self, path: str) -> None:
        self._path = Path(path)

    def load_last_run(self) -> datetime | None:
        if not self._path.exists():
            return None
        try:
            data = json.loads(self._path.read_text())
            ts = data.get("last_run")
            if ts is None:
                return None
            return datetime.fromisoformat(ts)
        except (OSError, ValueError, json.JSONDecodeError) as e:
            logger.warning("Failed to read reflection state at %s: %s", self._path, e)
            return None

    def save_last_run(self, when: datetime) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps({"last_run": when.isoformat()}))
        except OSError as e:
            logger.error("Failed to write reflection state at %s: %s", self._path, e)
```

**Step 4: Run tests**

```
uv run pytest tests/test_reflection_state.py -v
```

Expected: PASS.

**Step 5: Lint and commit**

```
uv run ruff check . && uv run ruff format .
git add bearmemori/core/reflection_state.py tests/test_reflection_state.py
git commit -m "feat: ReflectionState for last_run persistence"
```

---

## End of Plan 1

After Plan 1:
- `Settings` carries the four new reflection settings.
- `ReflectionProposal` is a typed model in `storage/models.py`.
- `reflection_proposals` and `reflection_proposal_memories` tables exist with foreign-key cascade.
- `MemoryDatabase` has `create_proposal`, `get_proposal`, `list_proposals`, `count_proposals`, `resolve_proposal`, `memory_ids_in_pending_proposals`, and `merge_group_recently_rejected`.
- `LLMClient.reflect_duplicates(group)` returns a parsed `is_duplicate` decision.
- `ReflectionState` persists the last-run timestamp to disk.

`ReflectionTask` has not been touched yet — it still exhibits the old auto-commit behavior. Plan 2 rewrites it to use the primitives above and produce proposals instead of mutating memories. Until Plan 2 is finished, the system remains functionally unchanged from a user standpoint, so Plan 1 can land independently.

**Next:** `docs/plans/2026-04-28-reflection-update-plan-2-reflection-task.md`.
