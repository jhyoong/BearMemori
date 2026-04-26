from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from bearmemori.api.routes import create_app
from bearmemori.core.memory_service import MemoryService
from bearmemori.storage.database import MemoryDatabase
from bearmemori.storage.models import Actor, MemoryCategory, MemoryDraft
from bearmemori.storage.pending_store import PendingStore
from bearmemori.storage.vector_store import VectorStore


@pytest.fixture
def client(tmp_path):
    db = MemoryDatabase(str(tmp_path / "t.db"))
    db.initialize()
    vec = MagicMock(spec=VectorStore)
    vec.search.return_value = []
    pending = PendingStore()
    service = MemoryService(db=db, vector_store=vec)
    app = create_app(
        db=db,
        vector_store=vec,
        pending_store=pending,
        memory_service=service,
    )
    return TestClient(app), service, db


def _seed(service, title="t"):
    return service.create(
        MemoryDraft(category=MemoryCategory.GENERAL, title=title, content="c"),
        actor=Actor.API,
    )


def test_get_audit_returns_entries(client):
    api, service, db = client
    rec = _seed(service, title="hello")
    resp = api.get("/audit")
    assert resp.status_code == 200
    data = resp.json()
    assert data["limit"] == 50
    assert data["offset"] == 0
    assert any(e["memory_id"] == rec.id and e["action"] == "create" for e in data["entries"])


def test_get_audit_filter_by_actor(client):
    api, service, db = client
    rec = _seed(service)
    service.delete(rec.id, actor=Actor.WEBAPP)
    resp = api.get("/audit?actor=webapp")
    assert resp.status_code == 200
    actions = {e["action"] for e in resp.json()["entries"]}
    assert actions == {"delete"}


def test_get_audit_filter_by_action(client):
    api, service, db = client
    rec = _seed(service)
    service.delete(rec.id, actor=Actor.API)
    resp = api.get("/audit?action=delete")
    assert resp.status_code == 200
    assert all(e["action"] == "delete" for e in resp.json()["entries"])


def test_get_audit_filter_by_memory_id(client):
    api, service, db = client
    rec1 = _seed(service)
    _seed(service)
    resp = api.get(f"/audit?memory_id={rec1.id}")
    ids = {e["memory_id"] for e in resp.json()["entries"]}
    assert ids == {rec1.id}


def test_get_audit_invalid_actor_returns_400(client):
    api, _, _ = client
    resp = api.get("/audit?actor=invalid")
    assert resp.status_code == 400


def test_get_audit_pagination(client):
    api, service, _ = client
    for i in range(5):
        _seed(service, title=f"t{i}")
    resp = api.get("/audit?limit=2&offset=1")
    data = resp.json()
    assert len(data["entries"]) == 2
    assert data["limit"] == 2
    assert data["offset"] == 1
