# Reflection Update — Plan 3 of 3: API, webapp, execution

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Prerequisite:** Plans 1 and 2 are fully landed. Reflection writes proposals; nothing reads them yet.

**Goal:** Wire user-facing review and execution. REST endpoints to list/get/approve/reject proposals; a webapp page to browse and act; execution code that applies approved proposals to memory state inside a transaction.

**Architecture:** A new module `bearmemori/core/proposal_service.py` owns the approve/reject logic so it can be unit-tested in isolation and called from both the REST handler and any future webapp form-post. The webapp page is HTMX-driven, matching existing patterns (`review_queue.html`, `audit.html`).

**Tech Stack:** FastAPI, Pydantic v2, Jinja2, HTMX, Pico CSS, pytest + pytest-asyncio. Project uses `uv`.

**Reference design doc:** `docs/plans/2026-04-28-reflection-update-design.md`

---

## Working rules

- **TDD.** Write the failing test first. Run it. Implement. Run it again.
- **One commit per task.** Don't bundle.
- **After each task that touches code, run:** `uv run pytest -v -k "proposal or reflection"`
- **Lint before commit:** `uv run ruff check . && uv run ruff format .`
- All commands run via `uv`.

---

## Task 1: Add API schemas

**Files:**
- Modify: `bearmemori/api/schemas.py`
- Create: `tests/test_proposal_schemas.py`

**Step 1: Write failing tests**

```python
from bearmemori.api.schemas import (
    ApproveProposalRequest,
    ProposalSummary,
    RejectProposalRequest,
)


def test_proposal_summary_basic():
    s = ProposalSummary(
        id="p1",
        proposal_type="merge",
        status="pending",
        created_at="2026-04-28T00:00:00+00:00",
        memory_count=2,
        reasoning_preview="Same dentist appointment.",
    )
    assert s.memory_count == 2


def test_approve_request_optional_overrides():
    r = ApproveProposalRequest()
    assert r.keep_id is None
    assert r.importance is None

    r2 = ApproveProposalRequest(keep_id="mem_a", importance=5)
    assert r2.keep_id == "mem_a"


def test_reject_request_optional_reason():
    r = RejectProposalRequest()
    assert r.reason is None
```

**Step 2: Run, verify fail**

```
uv run pytest tests/test_proposal_schemas.py -v
```

Expected: FAIL — `ImportError`.

**Step 3: Add schemas**

Append to `bearmemori/api/schemas.py`:

```python
class ProposalSummary(BaseModel):
    id: str
    proposal_type: str
    status: str
    created_at: str
    memory_count: int
    reasoning_preview: str


class ApproveProposalRequest(BaseModel):
    keep_id: str | None = None
    importance: int | None = None


class RejectProposalRequest(BaseModel):
    reason: str | None = None
```

**Step 4: Run tests**

```
uv run pytest tests/test_proposal_schemas.py -v
```

Expected: PASS.

**Step 5: Lint and commit**

```
uv run ruff check . && uv run ruff format .
git add bearmemori/api/schemas.py tests/test_proposal_schemas.py
git commit -m "feat: proposal API schemas"
```

---

## Task 2: Create `ProposalService` with `reject`

The service module bundles approve/reject logic so the API handler stays thin.

**Files:**
- Create: `bearmemori/core/proposal_service.py`
- Create: `tests/test_proposal_service.py`

**Step 1: Write failing test**

```python
from datetime import UTC, datetime
from unittest.mock import MagicMock

from bearmemori.core.proposal_service import ProposalNotFoundError, ProposalService
from bearmemori.storage.models import ReflectionProposal


def _proposal(**overrides):
    base = dict(
        id="p1",
        proposal_type="archive",
        status="pending",
        memory_ids=["mem_a"],
        reasoning="old",
        created_at=datetime.now(UTC),
    )
    base.update(overrides)
    return ReflectionProposal(**base)


def test_reject_resolves_proposal_with_note():
    db = MagicMock()
    db.get_proposal.return_value = _proposal()
    vs = MagicMock()
    svc = ProposalService(db=db, vector_store=vs)

    result = svc.reject("p1", reason="not duplicates")

    db.resolve_proposal.assert_called_once_with(
        "p1", status="rejected", note="not duplicates"
    )
    assert result["status"] == "rejected"


def test_reject_missing_proposal_raises():
    db = MagicMock()
    db.get_proposal.return_value = None
    svc = ProposalService(db=db, vector_store=MagicMock())
    try:
        svc.reject("missing", reason=None)
    except ProposalNotFoundError:
        return
    raise AssertionError("expected ProposalNotFoundError")


def test_reject_already_resolved_raises():
    from bearmemori.core.proposal_service import ProposalAlreadyResolvedError

    db = MagicMock()
    db.get_proposal.return_value = _proposal(status="approved", resolved_at=datetime.now(UTC))
    svc = ProposalService(db=db, vector_store=MagicMock())
    try:
        svc.reject("p1", reason=None)
    except ProposalAlreadyResolvedError:
        return
    raise AssertionError("expected ProposalAlreadyResolvedError")
```

**Step 2: Run, verify fail**

```
uv run pytest tests/test_proposal_service.py -v
```

Expected: FAIL — module does not exist.

**Step 3: Implement**

Create `bearmemori/core/proposal_service.py`:

```python
import logging

from bearmemori.storage.models import Actor

logger = logging.getLogger(__name__)


class ProposalNotFoundError(Exception):
    pass


class ProposalAlreadyResolvedError(Exception):
    pass


class ProposalValidationError(Exception):
    pass


class ProposalService:
    def __init__(self, db, vector_store) -> None:
        self._db = db
        self._vector_store = vector_store

    def reject(self, proposal_id: str, reason: str | None) -> dict:
        proposal = self._db.get_proposal(proposal_id)
        if proposal is None:
            raise ProposalNotFoundError(proposal_id)
        if proposal.status != "pending":
            raise ProposalAlreadyResolvedError(proposal_id)
        self._db.resolve_proposal(proposal_id, status="rejected", note=reason)
        return {"status": "rejected"}
```

**Step 4: Run tests**

```
uv run pytest tests/test_proposal_service.py -v
```

Expected: PASS.

**Step 5: Lint and commit**

```
uv run ruff check . && uv run ruff format .
git add bearmemori/core/proposal_service.py tests/test_proposal_service.py
git commit -m "feat: ProposalService with reject and error types"
```

---

## Task 3: Implement `approve_archive`

**Files:**
- Modify: `bearmemori/core/proposal_service.py`
- Modify: `tests/test_proposal_service.py`

**Step 1: Append failing tests**

```python
from bearmemori.storage.models import MemoryCategory, MemoryRecord


def _record(record_id: str, importance: int = 5, archived: bool = False) -> MemoryRecord:
    return MemoryRecord(
        id=record_id,
        category=MemoryCategory.GENERAL,
        title=f"Title {record_id}",
        content=f"Content {record_id}",
        created_at=datetime.now(UTC),
        importance=importance,
        archived=archived,
    )


def test_approve_archive_archives_the_memory():
    db = MagicMock()
    db.get_proposal.return_value = _proposal(
        proposal_type="archive", memory_ids=["mem_a"]
    )
    db.get.return_value = _record("mem_a", archived=False)
    vs = MagicMock()
    svc = ProposalService(db=db, vector_store=vs)

    result = svc.approve("p1", overrides={})

    # memory archived in DB
    args, kwargs = db.update.call_args
    updated_record = args[0]
    assert updated_record.archived is True
    # vector store deleted
    vs.delete.assert_called_once_with("mem_a")
    # proposal resolved
    db.resolve_proposal.assert_called_once()
    assert result["applied"]["archived_ids"] == ["mem_a"]


def test_approve_archive_already_archived_is_noop_but_resolves_proposal():
    db = MagicMock()
    db.get_proposal.return_value = _proposal(
        proposal_type="archive", memory_ids=["mem_a"]
    )
    db.get.return_value = _record("mem_a", archived=True)
    vs = MagicMock()
    svc = ProposalService(db=db, vector_store=vs)

    result = svc.approve("p1", overrides={})

    db.update.assert_not_called()
    vs.delete.assert_not_called()
    db.resolve_proposal.assert_called_once()
    assert result["applied"]["archived_ids"] == []
```

**Step 2: Run, verify fail**

```
uv run pytest tests/test_proposal_service.py -v -k approve_archive
```

Expected: FAIL — no `approve` method.

**Step 3: Add `approve` and `_approve_archive`**

Append to `bearmemori/core/proposal_service.py`:

```python
def approve(self, proposal_id: str, overrides: dict | None = None) -> dict:
    overrides = overrides or {}
    proposal = self._db.get_proposal(proposal_id)
    if proposal is None:
        raise ProposalNotFoundError(proposal_id)
    if proposal.status != "pending":
        raise ProposalAlreadyResolvedError(proposal_id)

    if proposal.proposal_type == "archive":
        applied = self._approve_archive(proposal)
    elif proposal.proposal_type == "rerank":
        applied = self._approve_rerank(proposal, overrides)
    elif proposal.proposal_type == "merge":
        applied = self._approve_merge(proposal, overrides)
    else:
        raise ProposalValidationError(f"unknown proposal_type: {proposal.proposal_type}")

    note = self._build_resolution_note(proposal, overrides)
    self._db.resolve_proposal(proposal_id, status="approved", note=note)
    return {"status": "approved", "applied": applied}

def _approve_archive(self, proposal) -> dict:
    memory_id = proposal.memory_ids[0]
    record = self._db.get(memory_id)
    if record is None or record.archived:
        return {"archived_ids": [], "updated_ids": []}
    record.archived = True
    self._db.update(record, actor=Actor.REFLECTION)
    self._vector_store.delete(memory_id)
    return {"archived_ids": [memory_id], "updated_ids": []}

def _build_resolution_note(self, proposal, overrides: dict) -> str | None:
    """Record overrides if the user changed the recommendation on approval."""
    notes = []
    if proposal.proposal_type == "merge":
        rec_keep = proposal.recommended_keep_id
        used_keep = overrides.get("keep_id") or rec_keep
        if used_keep and used_keep != rec_keep:
            notes.append(f"keep_id override: {rec_keep} -> {used_keep}")
    if proposal.proposal_type == "rerank":
        rec_imp = proposal.recommended_importance
        used_imp = overrides.get("importance") or rec_imp
        if used_imp and used_imp != rec_imp:
            notes.append(f"importance override: {rec_imp} -> {used_imp}")
    return "; ".join(notes) if notes else None
```

**Step 4: Run tests**

```
uv run pytest tests/test_proposal_service.py -v
```

Expected: PASS.

**Step 5: Lint and commit**

```
uv run ruff check . && uv run ruff format .
git add bearmemori/core/proposal_service.py tests/test_proposal_service.py
git commit -m "feat: ProposalService.approve_archive"
```

---

## Task 4: Implement `approve_rerank`

**Files:**
- Modify: `bearmemori/core/proposal_service.py`
- Modify: `tests/test_proposal_service.py`

**Step 1: Append failing tests**

```python
def test_approve_rerank_updates_importance():
    db = MagicMock()
    db.get_proposal.return_value = _proposal(
        proposal_type="rerank",
        memory_ids=["mem_b"],
        recommended_importance=7,
    )
    db.get.return_value = _record("mem_b", importance=5)
    vs = MagicMock()
    svc = ProposalService(db=db, vector_store=vs)

    result = svc.approve("p1", overrides={})

    args, _ = db.update.call_args
    updated = args[0]
    assert updated.importance == 7
    vs.update.assert_called_once_with(updated)
    assert result["applied"]["updated_ids"] == ["mem_b"]


def test_approve_rerank_with_user_override():
    db = MagicMock()
    db.get_proposal.return_value = _proposal(
        proposal_type="rerank", memory_ids=["mem_b"], recommended_importance=7
    )
    db.get.return_value = _record("mem_b", importance=5)
    svc = ProposalService(db=db, vector_store=MagicMock())

    svc.approve("p1", overrides={"importance": 9})

    updated = db.update.call_args[0][0]
    assert updated.importance == 9


def test_approve_rerank_invalid_importance_raises():
    db = MagicMock()
    db.get_proposal.return_value = _proposal(
        proposal_type="rerank", memory_ids=["mem_b"], recommended_importance=7
    )
    db.get.return_value = _record("mem_b", importance=5)
    svc = ProposalService(db=db, vector_store=MagicMock())

    try:
        svc.approve("p1", overrides={"importance": 99})
    except ProposalValidationError:
        return
    raise AssertionError("expected ProposalValidationError")


def test_approve_rerank_archived_memory_raises():
    db = MagicMock()
    db.get_proposal.return_value = _proposal(
        proposal_type="rerank", memory_ids=["mem_b"], recommended_importance=7
    )
    db.get.return_value = _record("mem_b", archived=True)
    svc = ProposalService(db=db, vector_store=MagicMock())

    try:
        svc.approve("p1", overrides={})
    except ProposalValidationError:
        return
    raise AssertionError("expected ProposalValidationError")
```

**Step 2: Run, verify fail**

```
uv run pytest tests/test_proposal_service.py -v -k approve_rerank
```

Expected: FAIL.

**Step 3: Implement**

Add to `bearmemori/core/proposal_service.py`:

```python
def _approve_rerank(self, proposal, overrides: dict) -> dict:
    memory_id = proposal.memory_ids[0]
    record = self._db.get(memory_id)
    if record is None:
        raise ProposalValidationError(f"memory not found: {memory_id}")
    if record.archived:
        raise ProposalValidationError(f"memory is archived: {memory_id}")

    new_importance = overrides.get("importance") or proposal.recommended_importance
    if new_importance is None:
        raise ProposalValidationError("importance is required for rerank")
    if not (1 <= int(new_importance) <= 10):
        raise ProposalValidationError(f"importance out of range: {new_importance}")

    record.importance = int(new_importance)
    self._db.update(record, actor=Actor.REFLECTION)
    self._vector_store.update(record)
    return {"archived_ids": [], "updated_ids": [memory_id]}
```

**Step 4: Run tests**

```
uv run pytest tests/test_proposal_service.py -v
```

Expected: PASS.

**Step 5: Lint and commit**

```
uv run ruff check . && uv run ruff format .
git add bearmemori/core/proposal_service.py tests/test_proposal_service.py
git commit -m "feat: ProposalService.approve_rerank with override"
```

---

## Task 5: Implement `approve_merge`

**Files:**
- Modify: `bearmemori/core/proposal_service.py`
- Modify: `tests/test_proposal_service.py`

**Step 1: Append failing tests**

```python
def test_approve_merge_archives_others_keeps_one():
    db = MagicMock()
    db.get_proposal.return_value = _proposal(
        proposal_type="merge",
        memory_ids=["mem_a", "mem_b", "mem_c"],
        recommended_keep_id="mem_a",
    )
    records = {
        "mem_a": _record("mem_a"),
        "mem_b": _record("mem_b"),
        "mem_c": _record("mem_c"),
    }
    db.get.side_effect = lambda mid: records[mid]
    vs = MagicMock()
    svc = ProposalService(db=db, vector_store=vs)

    result = svc.approve("p1", overrides={})

    archived_ids = sorted(result["applied"]["archived_ids"])
    assert archived_ids == ["mem_b", "mem_c"]

    updated_ids = [c.args[0].id for c in db.update.call_args_list]
    assert sorted(updated_ids) == ["mem_b", "mem_c"]
    vs.delete.assert_any_call("mem_b")
    vs.delete.assert_any_call("mem_c")


def test_approve_merge_with_keep_override():
    db = MagicMock()
    db.get_proposal.return_value = _proposal(
        proposal_type="merge",
        memory_ids=["mem_a", "mem_b"],
        recommended_keep_id="mem_a",
    )
    records = {"mem_a": _record("mem_a"), "mem_b": _record("mem_b")}
    db.get.side_effect = lambda mid: records[mid]
    svc = ProposalService(db=db, vector_store=MagicMock())

    result = svc.approve("p1", overrides={"keep_id": "mem_b"})

    assert result["applied"]["archived_ids"] == ["mem_a"]


def test_approve_merge_keep_id_not_in_group_raises():
    db = MagicMock()
    db.get_proposal.return_value = _proposal(
        proposal_type="merge",
        memory_ids=["mem_a", "mem_b"],
        recommended_keep_id="mem_a",
    )
    db.get.side_effect = lambda mid: {"mem_a": _record("mem_a"), "mem_b": _record("mem_b")}[mid]
    svc = ProposalService(db=db, vector_store=MagicMock())

    try:
        svc.approve("p1", overrides={"keep_id": "mem_xyz"})
    except ProposalValidationError:
        return
    raise AssertionError("expected ProposalValidationError")


def test_approve_merge_keep_id_already_archived_raises():
    db = MagicMock()
    db.get_proposal.return_value = _proposal(
        proposal_type="merge",
        memory_ids=["mem_a", "mem_b"],
        recommended_keep_id="mem_a",
    )
    db.get.side_effect = lambda mid: {
        "mem_a": _record("mem_a", archived=True),
        "mem_b": _record("mem_b"),
    }[mid]
    svc = ProposalService(db=db, vector_store=MagicMock())

    try:
        svc.approve("p1", overrides={})
    except ProposalValidationError:
        return
    raise AssertionError("expected ProposalValidationError")


def test_approve_merge_other_already_archived_is_skipped():
    """If one of the memories was already archived externally, don't fail — just continue."""
    db = MagicMock()
    db.get_proposal.return_value = _proposal(
        proposal_type="merge",
        memory_ids=["mem_a", "mem_b", "mem_c"],
        recommended_keep_id="mem_a",
    )
    db.get.side_effect = lambda mid: {
        "mem_a": _record("mem_a"),
        "mem_b": _record("mem_b", archived=True),
        "mem_c": _record("mem_c"),
    }[mid]
    svc = ProposalService(db=db, vector_store=MagicMock())

    result = svc.approve("p1", overrides={})
    assert result["applied"]["archived_ids"] == ["mem_c"]
```

**Step 2: Run, verify fail**

```
uv run pytest tests/test_proposal_service.py -v -k approve_merge
```

Expected: FAIL.

**Step 3: Implement**

Add to `bearmemori/core/proposal_service.py`:

```python
def _approve_merge(self, proposal, overrides: dict) -> dict:
    keep_id = overrides.get("keep_id") or proposal.recommended_keep_id
    if keep_id not in proposal.memory_ids:
        raise ProposalValidationError(
            f"keep_id {keep_id} not in proposal memory_ids"
        )
    keeper = self._db.get(keep_id)
    if keeper is None:
        raise ProposalValidationError(f"keep memory not found: {keep_id}")
    if keeper.archived:
        raise ProposalValidationError(f"keep memory already archived: {keep_id}")

    archived_ids: list[str] = []
    for mid in proposal.memory_ids:
        if mid == keep_id:
            continue
        record = self._db.get(mid)
        if record is None or record.archived:
            continue
        record.archived = True
        self._db.update(record, actor=Actor.REFLECTION)
        self._vector_store.delete(mid)
        archived_ids.append(mid)

    return {"archived_ids": sorted(archived_ids), "updated_ids": []}
```

**Step 4: Run tests**

```
uv run pytest tests/test_proposal_service.py -v
```

Expected: PASS.

**Step 5: Lint and commit**

```
uv run ruff check . && uv run ruff format .
git add bearmemori/core/proposal_service.py tests/test_proposal_service.py
git commit -m "feat: ProposalService.approve_merge with override"
```

---

## Task 6: Wire REST endpoints

**Files:**
- Modify: `bearmemori/api/routes.py`
- Modify: `bearmemori/app.py`
- Create: `tests/test_proposal_api.py`

**Step 1: Write failing API tests**

```python
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from bearmemori.api.routes import create_app
from bearmemori.core.proposal_service import ProposalService
from bearmemori.storage.models import MemoryCategory, MemoryRecord, ReflectionProposal


def _record(record_id: str) -> MemoryRecord:
    return MemoryRecord(
        id=record_id,
        category=MemoryCategory.GENERAL,
        title=f"T {record_id}",
        content=f"C {record_id}",
        created_at=datetime.now(UTC),
        importance=5,
    )


@pytest.fixture
def app_and_db():
    db = MagicMock()
    vs = MagicMock()
    pending_store = MagicMock()
    memory_service = MagicMock()
    proposal_service = ProposalService(db=db, vector_store=vs)
    app = create_app(
        db=db,
        vector_store=vs,
        pending_store=pending_store,
        memory_service=memory_service,
        proposal_service=proposal_service,
    )
    return app, db, vs


def test_list_proposals_returns_summaries(app_and_db):
    app, db, _ = app_and_db
    db.list_proposals.return_value = [
        ReflectionProposal(
            id="p1",
            proposal_type="merge",
            status="pending",
            memory_ids=["mem_a", "mem_b"],
            recommended_keep_id="mem_a",
            reasoning="dup",
            created_at=datetime.now(UTC),
        )
    ]
    db.count_proposals.return_value = 1
    client = TestClient(app)
    res = client.get("/reflection/proposals?status=pending")
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 1
    assert body["proposals"][0]["id"] == "p1"
    assert body["proposals"][0]["memory_count"] == 2


def test_get_proposal_hydrates_memories(app_and_db):
    app, db, _ = app_and_db
    db.get_proposal.return_value = ReflectionProposal(
        id="p1",
        proposal_type="merge",
        status="pending",
        memory_ids=["mem_a", "mem_b"],
        recommended_keep_id="mem_a",
        reasoning="dup",
        created_at=datetime.now(UTC),
    )
    db.get.side_effect = lambda mid: _record(mid)
    client = TestClient(app)
    res = client.get("/reflection/proposals/p1")
    assert res.status_code == 200
    body = res.json()
    assert body["proposal"]["id"] == "p1"
    assert len(body["memories"]) == 2


def test_approve_endpoint(app_and_db):
    app, db, vs = app_and_db
    db.get_proposal.return_value = ReflectionProposal(
        id="p1",
        proposal_type="archive",
        status="pending",
        memory_ids=["mem_a"],
        reasoning="old",
        created_at=datetime.now(UTC),
    )
    db.get.return_value = _record("mem_a")
    client = TestClient(app)
    res = client.post("/reflection/proposals/p1/approve", json={})
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "approved"


def test_reject_endpoint(app_and_db):
    app, db, _ = app_and_db
    db.get_proposal.return_value = ReflectionProposal(
        id="p1",
        proposal_type="archive",
        status="pending",
        memory_ids=["mem_a"],
        reasoning="old",
        created_at=datetime.now(UTC),
    )
    client = TestClient(app)
    res = client.post(
        "/reflection/proposals/p1/reject", json={"reason": "wrong"}
    )
    assert res.status_code == 200
    assert res.json()["status"] == "rejected"


def test_approve_missing_returns_404(app_and_db):
    app, db, _ = app_and_db
    db.get_proposal.return_value = None
    client = TestClient(app)
    res = client.post("/reflection/proposals/missing/approve", json={})
    assert res.status_code == 404


def test_approve_validation_error_returns_400(app_and_db):
    app, db, _ = app_and_db
    db.get_proposal.return_value = ReflectionProposal(
        id="p1",
        proposal_type="merge",
        status="pending",
        memory_ids=["mem_a", "mem_b"],
        recommended_keep_id="mem_a",
        reasoning="dup",
        created_at=datetime.now(UTC),
    )
    db.get.side_effect = lambda mid: _record(mid)
    client = TestClient(app)
    res = client.post(
        "/reflection/proposals/p1/approve", json={"keep_id": "mem_xyz"}
    )
    assert res.status_code == 400
```

**Step 2: Run, verify fail**

```
uv run pytest tests/test_proposal_api.py -v
```

Expected: FAIL — `create_app` does not accept `proposal_service`, and the routes don't exist.

**Step 3: Update `create_app` signature in `bearmemori/api/routes.py`**

Add `proposal_service` to the `create_app` signature (next to `reflection_task`). Then add the four endpoints.

In imports, add:

```python
from bearmemori.api.schemas import (
    ApproveProposalRequest,
    BulkDeleteRequest,
    BulkUpdateRequest,
    ConfirmRequest,
    ProposalSummary,
    RejectProposalRequest,
    TriageRequest,
    UpdateMemoryRequest,
)
from bearmemori.core.proposal_service import (
    ProposalAlreadyResolvedError,
    ProposalNotFoundError,
    ProposalService,
    ProposalValidationError,
)
```

In the signature (around line 41), add:

```python
proposal_service: ProposalService | None = None,
```

After the `run_reflection` endpoint (around line 151), add:

```python
def _proposal_to_summary(p) -> ProposalSummary:
    preview = (p.reasoning or "")[:200]
    return ProposalSummary(
        id=p.id,
        proposal_type=p.proposal_type,
        status=p.status,
        created_at=p.created_at.isoformat(),
        memory_count=len(p.memory_ids),
        reasoning_preview=preview,
    )

@app.get("/reflection/proposals")
def list_proposals(
    status: str | None = "pending",
    type: str | None = None,
    offset: int = 0,
    limit: int = 50,
):
    limit = min(limit, 200)
    proposals = db.list_proposals(
        status=status, proposal_type=type, offset=offset, limit=limit
    )
    return {
        "proposals": [_proposal_to_summary(p).model_dump() for p in proposals],
        "total": db.count_proposals(status=status),
        "offset": offset,
        "limit": limit,
    }

@app.get("/reflection/proposals/{proposal_id}")
def get_proposal_detail(proposal_id: str):
    p = db.get_proposal(proposal_id)
    if p is None:
        raise HTTPException(status_code=404, detail="Proposal not found")
    memories = []
    for mid in p.memory_ids:
        record = db.get(mid)
        if record is not None:
            memories.append(record.model_dump(mode="json"))
    return {
        "proposal": {
            "id": p.id,
            "proposal_type": p.proposal_type,
            "status": p.status,
            "memory_ids": p.memory_ids,
            "recommended_keep_id": p.recommended_keep_id,
            "recommended_importance": p.recommended_importance,
            "reasoning": p.reasoning,
            "resolution_note": p.resolution_note,
            "created_at": p.created_at.isoformat(),
            "resolved_at": p.resolved_at.isoformat() if p.resolved_at else None,
        },
        "memories": memories,
    }

@app.post("/reflection/proposals/{proposal_id}/approve")
def approve_proposal(proposal_id: str, request: ApproveProposalRequest):
    if proposal_service is None:
        raise HTTPException(status_code=503, detail="Proposals not configured")
    overrides = request.model_dump(exclude_none=True)
    try:
        return proposal_service.approve(proposal_id, overrides=overrides)
    except ProposalNotFoundError:
        raise HTTPException(status_code=404, detail="Proposal not found")
    except ProposalAlreadyResolvedError:
        raise HTTPException(status_code=409, detail="Proposal already resolved")
    except ProposalValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/reflection/proposals/{proposal_id}/reject")
def reject_proposal(proposal_id: str, request: RejectProposalRequest):
    if proposal_service is None:
        raise HTTPException(status_code=503, detail="Proposals not configured")
    try:
        return proposal_service.reject(proposal_id, reason=request.reason)
    except ProposalNotFoundError:
        raise HTTPException(status_code=404, detail="Proposal not found")
    except ProposalAlreadyResolvedError:
        raise HTTPException(status_code=409, detail="Proposal already resolved")
```

**Step 4: Wire `ProposalService` in `bearmemori/app.py`**

In `create_application()`, after `memory_service = MemoryService(...)` (around line 113), add:

```python
proposal_service = ProposalService(db=db, vector_store=vector_store)
```

Add the import at the top:

```python
from bearmemori.core.proposal_service import ProposalService
```

Pass it through to `create_api_app(... proposal_service=proposal_service, ...)`.

**Step 5: Run tests**

```
uv run pytest tests/test_proposal_api.py -v
```

Expected: PASS.

Run the broader API suite to confirm nothing else broke:

```
uv run pytest tests/ -k api -v
```

Expected: PASS.

**Step 6: Lint and commit**

```
uv run ruff check . && uv run ruff format .
git add bearmemori/api/routes.py bearmemori/app.py tests/test_proposal_api.py
git commit -m "feat: REST endpoints for reflection proposals"
```

---

## Task 7: Webapp `/proposals` route and template

**Files:**
- Modify: `bearmemori/webapp/router.py`
- Create: `bearmemori/webapp/templates/proposals.html`
- Create: `tests/test_webapp_proposals.py`

**Step 1: Write failing webapp tests**

```python
from datetime import UTC, datetime
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from bearmemori.core.proposal_service import ProposalService
from bearmemori.storage.models import MemoryCategory, MemoryRecord, ReflectionProposal
from bearmemori.webapp.auth import WebappAuthMiddleware
from bearmemori.webapp.router import create_webapp_router


def _record(record_id: str) -> MemoryRecord:
    return MemoryRecord(
        id=record_id,
        category=MemoryCategory.GENERAL,
        title=f"T {record_id}",
        content=f"C {record_id}",
        created_at=datetime.now(UTC),
        importance=5,
    )


def _proposal(proposal_type="merge"):
    return ReflectionProposal(
        id="p1",
        proposal_type=proposal_type,
        status="pending",
        memory_ids=["mem_a", "mem_b"] if proposal_type == "merge" else ["mem_a"],
        recommended_keep_id="mem_a" if proposal_type == "merge" else None,
        recommended_importance=7 if proposal_type == "rerank" else None,
        reasoning="reason",
        created_at=datetime.now(UTC),
    )


def _make_client(proposal):
    db = MagicMock()
    db.list_proposals.return_value = [proposal]
    db.count_proposals.return_value = 1
    db.get_proposal.return_value = proposal
    db.get.side_effect = lambda mid: _record(mid)
    vs = MagicMock()
    auth = WebappAuthMiddleware(None, "secret")
    proposal_service = ProposalService(db=db, vector_store=vs)
    router = create_webapp_router(
        db, vs, auth,
        memory_service=MagicMock(),
        proposal_service=proposal_service,
    )
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    # bypass auth by injecting cookie
    client.cookies.set("webapp_session", auth.create_session_token())
    return client, db


def test_proposals_page_renders_merge():
    client, _ = _make_client(_proposal("merge"))
    res = client.get("/webapp/proposals")
    assert res.status_code == 200
    assert "Possible duplicates" in res.text
    assert "mem_a" in res.text


def test_proposals_page_renders_archive():
    client, _ = _make_client(_proposal("archive"))
    res = client.get("/webapp/proposals")
    assert res.status_code == 200
    assert "Suggested archive" in res.text


def test_proposals_page_renders_rerank():
    client, _ = _make_client(_proposal("rerank"))
    res = client.get("/webapp/proposals")
    assert res.status_code == 200
    assert "importance" in res.text.lower()
```

If `WebappAuthMiddleware` doesn't expose a `create_session_token()` helper, read the existing `webapp/auth.py` and use whatever helper login uses (`create_session_cookie` on a `Response`, then read the cookie). Adjust the fixture to match.

**Step 2: Run, verify fail**

```
uv run pytest tests/test_webapp_proposals.py -v
```

Expected: FAIL — `create_webapp_router` does not accept `proposal_service`, route does not exist, template does not exist.

**Step 3: Update `bearmemori/webapp/router.py`**

Add `proposal_service: ProposalService | None = None` to the `create_webapp_router` signature.

Add the routes. Place them next to `/review` (around line 182) so they fit the existing review pattern:

```python
@r.get("/proposals", response_class=HTMLResponse)
async def proposals_page(
    request: Request,
    status: str = "pending",
    type: str | None = None,
):
    proposals = db.list_proposals(status=status, proposal_type=type, limit=100)
    items = []
    for p in proposals:
        memories = []
        for mid in p.memory_ids:
            record = db.get(mid)
            if record is not None:
                memories.append(record)
        items.append({"proposal": p, "memories": memories})
    return templates.TemplateResponse(
        request,
        "proposals.html",
        {
            "items": items,
            "status_filter": status,
            "type_filter": type or "",
        },
    )

@r.post("/proposals/{proposal_id}/approve", response_class=HTMLResponse)
async def proposals_approve(
    request: Request,
    proposal_id: str,
    keep_id: str = Form(""),
    importance: int | None = Form(None),
):
    if proposal_service is None:
        return HTMLResponse("Proposals not configured", status_code=503)
    overrides = {}
    if keep_id:
        overrides["keep_id"] = keep_id
    if importance is not None:
        overrides["importance"] = importance
    try:
        proposal_service.approve(proposal_id, overrides=overrides)
        return HTMLResponse(f'<p class="contrast">Approved {proposal_id}</p>')
    except Exception as e:
        return HTMLResponse(f'<p class="error">Error: {e}</p>', status_code=400)

@r.post("/proposals/{proposal_id}/reject", response_class=HTMLResponse)
async def proposals_reject(
    request: Request,
    proposal_id: str,
    reason: str = Form(""),
):
    if proposal_service is None:
        return HTMLResponse("Proposals not configured", status_code=503)
    try:
        proposal_service.reject(proposal_id, reason=reason or None)
        return HTMLResponse(f'<p class="secondary">Rejected {proposal_id}</p>')
    except Exception as e:
        return HTMLResponse(f'<p class="error">Error: {e}</p>', status_code=400)
```

In `bearmemori/app.py`, pass `proposal_service` into `create_webapp_router(... proposal_service=proposal_service, ...)`.

**Step 4: Create `bearmemori/webapp/templates/proposals.html`**

```html
{% extends "base.html" %}
{% block title %}Proposals - BearMemori{% endblock %}
{% block content %}
<h2>Reflection Proposals</h2>

<form method="get" action="/webapp/proposals">
    <fieldset role="group">
        <select name="status">
            <option value="pending" {% if status_filter == "pending" %}selected{% endif %}>Pending</option>
            <option value="approved" {% if status_filter == "approved" %}selected{% endif %}>Approved</option>
            <option value="rejected" {% if status_filter == "rejected" %}selected{% endif %}>Rejected</option>
        </select>
        <select name="type">
            <option value="" {% if not type_filter %}selected{% endif %}>All types</option>
            <option value="merge" {% if type_filter == "merge" %}selected{% endif %}>Merge</option>
            <option value="archive" {% if type_filter == "archive" %}selected{% endif %}>Archive</option>
            <option value="rerank" {% if type_filter == "rerank" %}selected{% endif %}>Rerank</option>
        </select>
        <button type="submit">Filter</button>
    </fieldset>
</form>

<p>{{ items | length }} proposal(s).</p>

{% for item in items %}
{% set p = item.proposal %}
<article id="proposal-{{ p.id }}">
    {% if p.proposal_type == "merge" %}
        <h3>Possible duplicates</h3>
        <p><em>Recommended to keep: <strong>{{ p.recommended_keep_id }}</strong></em></p>
        <div class="grid">
            {% for m in item.memories %}
            <div class="memory-card{% if m.id == p.recommended_keep_id %} highlight{% endif %}">
                <strong>{{ m.title }}</strong>
                <p>{{ m.content }}</p>
                <small>id: {{ m.id }} | category: {{ m.category.value }} | importance: {{ m.importance }}/10</small>
            </div>
            {% endfor %}
        </div>
        <p><em>Reason: {{ p.reasoning }}</em></p>
        <form hx-post="/webapp/proposals/{{ p.id }}/approve" hx-target="#proposal-{{ p.id }}" hx-swap="outerHTML">
            <label>Keep memory:
                <select name="keep_id">
                    {% for m in item.memories %}
                    <option value="{{ m.id }}"{% if m.id == p.recommended_keep_id %} selected{% endif %}>{{ m.id }} — {{ m.title }}</option>
                    {% endfor %}
                </select>
            </label>
            <button type="submit" class="contrast">Approve</button>
        </form>
        <form hx-post="/webapp/proposals/{{ p.id }}/reject" hx-target="#proposal-{{ p.id }}" hx-swap="outerHTML">
            <button type="submit" class="secondary">Reject</button>
        </form>

    {% elif p.proposal_type == "archive" %}
        <h3>Suggested archive</h3>
        {% set m = item.memories[0] %}
        <div class="memory-card">
            <strong>{{ m.title }}</strong>
            <p>{{ m.content }}</p>
            <small>id: {{ m.id }} | importance: {{ m.importance }}/10</small>
        </div>
        <p><em>Reason: {{ p.reasoning }}</em></p>
        <form hx-post="/webapp/proposals/{{ p.id }}/approve" hx-target="#proposal-{{ p.id }}" hx-swap="outerHTML">
            <button type="submit" class="contrast">Approve archive</button>
        </form>
        <form hx-post="/webapp/proposals/{{ p.id }}/reject" hx-target="#proposal-{{ p.id }}" hx-swap="outerHTML">
            <button type="submit" class="secondary">Reject</button>
        </form>

    {% elif p.proposal_type == "rerank" %}
        {% set m = item.memories[0] %}
        <h3>Suggested importance change: {{ m.importance }} → {{ p.recommended_importance }}</h3>
        <div class="memory-card">
            <strong>{{ m.title }}</strong>
            <p>{{ m.content }}</p>
            <small>id: {{ m.id }} | category: {{ m.category.value }}</small>
        </div>
        <p><em>Reason: {{ p.reasoning }}</em></p>
        <form hx-post="/webapp/proposals/{{ p.id }}/approve" hx-target="#proposal-{{ p.id }}" hx-swap="outerHTML">
            <label>New importance:
                <input type="number" name="importance" min="1" max="10" value="{{ p.recommended_importance }}">
            </label>
            <button type="submit" class="contrast">Approve</button>
        </form>
        <form hx-post="/webapp/proposals/{{ p.id }}/reject" hx-target="#proposal-{{ p.id }}" hx-swap="outerHTML">
            <button type="submit" class="secondary">Reject</button>
        </form>
    {% endif %}
</article>
<hr>
{% endfor %}
{% endblock %}
```

**Step 5: Run tests**

```
uv run pytest tests/test_webapp_proposals.py -v
```

Expected: PASS.

**Step 6: Lint and commit**

```
uv run ruff check . && uv run ruff format .
git add bearmemori/webapp/router.py bearmemori/webapp/templates/proposals.html bearmemori/app.py tests/test_webapp_proposals.py
git commit -m "feat: webapp /proposals page with HTMX approve/reject"
```

---

## Task 8: Add navigation link

**Files:**
- Modify: `bearmemori/webapp/templates/base.html`

**Step 1: Edit `base.html`**

Find the nav `<ul>` near line 16-22. After the `<li><a href="/webapp/review">Review Queue</a></li>` line, insert:

```html
<li><a href="/webapp/proposals">Proposals</a></li>
```

**Step 2: Manual smoke test**

```
uv run python -c "
from jinja2 import Environment, FileSystemLoader
env = Environment(loader=FileSystemLoader('bearmemori/webapp/templates'))
t = env.get_template('base.html')
out = t.render()
assert '/webapp/proposals' in out
print('nav link present')
"
```

Expected: `nav link present`.

**Step 3: Commit**

```
git add bearmemori/webapp/templates/base.html
git commit -m "feat: add Proposals link to webapp navigation"
```

---

## Task 9: Update CLAUDE.md and double-check `.env.example`

**Files:**
- Modify: `CLAUDE.md`
- Verify: `.env.example`

**Step 1: Update CLAUDE.md**

In `CLAUDE.md`, locate the Architecture section. Under `core/` add a brief note that reflection now writes proposals. Under "Key Design Decisions", add a single bullet:

```
- Reflection produces review-gated proposals (merge / archive / rerank); user approves or rejects them in the webapp before any state change is applied
```

**Step 2: Verify `.env.example`**

Confirm the four reflection settings added in Plan 1 Task 1 are present:

```
REFLECTION_DUPLICATE_SIMILARITY_THRESHOLD=0.85
REFLECTION_DUPLICATE_TOP_K=5
REFLECTION_REJECT_COOLDOWN_DAYS=30
REFLECTION_STATE_PATH=data/reflection_state.json
```

If missing, add them.

**Step 3: Commit**

```
git add CLAUDE.md .env.example
git commit -m "docs: note review-gated reflection in CLAUDE.md"
```

---

## Task 10: Final integration smoke test

**Step 1: Run the full suite**

```
uv run pytest -v
```

Expected: all PASS.

**Step 2: Lint**

```
uv run ruff check . && uv run ruff format .
```

**Step 3: Boot the app (optional, requires local `.env`)**

If a local `.env` is configured with `API_ONLY_MODE=true`, `WEBAPP_SECRET=<something>`, and a reachable LLM endpoint:

```
uv run python -m bearmemori serve --port 8100 --no-telegram
```

In another shell:

```
curl -s http://localhost:8100/health
curl -s -X POST http://localhost:8100/memory/reflection/run
curl -s 'http://localhost:8100/reflection/proposals?status=pending' | python -m json.tool
```

Expected: a reflection run completes with the new summary shape; proposals list returns successfully (likely empty unless test data is present).

**Step 4: Visit the webapp**

Open `http://localhost:8100/webapp/login`, log in, click "Proposals" in the nav, confirm the page renders.

**Step 5: Final commit if anything was tweaked**

```
git add <files>
git commit -m "chore: integration tweaks for proposals end-to-end"
```

---

## End of Plan 3

After Plan 3:
- `GET /reflection/proposals`, `GET /reflection/proposals/{id}`, `POST .../approve`, `POST .../reject` all work.
- `ProposalService` applies approve/reject decisions to memory state with proper validation.
- The webapp `/proposals` page renders all three proposal types with HTMX approve/reject buttons.
- Navigation link added.
- Docs updated.

The full reflection rework is complete. Reflection no longer mutates memory state on its own — every change goes through the user's review queue.
