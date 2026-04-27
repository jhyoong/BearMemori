import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bearmemori.core.memory_service import MemoryService
from bearmemori.storage.database import MemoryDatabase
from bearmemori.storage.models import Actor, MemoryCategory, MemoryDraft
from bearmemori.storage.vector_store import VectorStore
from bearmemori.webapp.auth import WebappAuthMiddleware
from bearmemori.webapp.router import create_webapp_router


@pytest.fixture
def client(tmp_path):
    db = MemoryDatabase(str(tmp_path / "t.db"))
    db.initialize()
    vec = VectorStore(persist_dir=str(tmp_path / "chroma"))
    vec.init()
    service = MemoryService(db=db, vector_store=vec)
    app = FastAPI()
    auth = WebappAuthMiddleware(app, "test-secret")
    app.include_router(
        create_webapp_router(db=db, vector_store=vec, auth=auth, memory_service=service)
    )
    app.add_middleware(WebappAuthMiddleware, secret="test-secret")
    api = TestClient(app)
    # bypass auth: post login to get session cookie
    response = api.post("/webapp/login", data={"secret": "test-secret"}, follow_redirects=False)
    api.cookies.update(response.cookies)
    return api, service, db


def test_audit_page_renders(client):
    api, service, db = client
    rec = service.create(
        MemoryDraft(category=MemoryCategory.GENERAL, title="hello", content="c"),
        actor=Actor.API,
    )
    resp = api.get("/webapp/audit")
    assert resp.status_code == 200
    assert "hello" in resp.text
    assert rec.id in resp.text


def test_audit_rows_partial(client):
    api, service, db = client
    service.create(
        MemoryDraft(category=MemoryCategory.GENERAL, title="hello", content="c"),
        actor=Actor.WEBAPP,
    )
    resp = api.get("/webapp/audit/rows?actor=webapp", headers={"HX-Request": "true"})
    assert resp.status_code == 200
    assert "hello" in resp.text


def test_audit_rows_deleted_memory_marked(client):
    api, service, db = client
    rec = service.create(
        MemoryDraft(category=MemoryCategory.GENERAL, title="goodbye", content="c"),
        actor=Actor.API,
    )
    service.delete(rec.id, actor=Actor.API)
    resp = api.get("/webapp/audit")
    assert resp.status_code == 200
    assert "(deleted)" in resp.text
