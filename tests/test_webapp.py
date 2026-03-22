from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from bearmemori.storage.database import MemoryDatabase
from bearmemori.storage.models import MemoryCategory, MemoryRecord
from bearmemori.storage.vector_store import VectorStore
from bearmemori.webapp.auth import WebappAuthMiddleware
from bearmemori.webapp.router import create_webapp_router


@pytest.fixture
def db():
    d = MemoryDatabase(":memory:")
    d.initialize()
    return d


@pytest.fixture
def vector_store():
    vs = VectorStore(":memory:")
    vs.init()
    return vs


@pytest.fixture
def webapp_client(db, vector_store):
    app = FastAPI()
    auth = WebappAuthMiddleware(app, "test-secret")
    router = create_webapp_router(db, vector_store, auth)
    app.include_router(router)
    app.add_middleware(WebappAuthMiddleware, secret="test-secret")
    return TestClient(app)


@pytest.fixture
def authed_webapp_client(db, vector_store):
    app = FastAPI()
    auth = WebappAuthMiddleware(app, "test-secret")
    router = create_webapp_router(db, vector_store, auth)
    app.include_router(router)
    app.add_middleware(WebappAuthMiddleware, secret="test-secret")

    client = TestClient(app)
    response = client.post(
        "/webapp/login",
        data={"secret": "test-secret"},
        follow_redirects=False,
    )
    client.cookies.update(response.cookies)
    return client


def test_login_page_returns_200(webapp_client):
    response = webapp_client.get("/webapp/login")
    assert response.status_code == 200


def test_memories_redirects_without_auth(webapp_client):
    response = webapp_client.get("/webapp/memories", follow_redirects=False)
    assert response.status_code == 302
    assert "/webapp/login" in response.headers["location"]


def test_login_with_correct_secret(webapp_client):
    response = webapp_client.post(
        "/webapp/login",
        data={"secret": "test-secret"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert "webapp_session" in response.cookies


def test_memories_page_with_auth(authed_webapp_client):
    response = authed_webapp_client.get("/webapp/memories")
    assert response.status_code == 200
    assert "Memories" in response.text


def test_create_memory_page(authed_webapp_client):
    response = authed_webapp_client.get("/webapp/memories/new")
    assert response.status_code == 200


def test_review_queue_page(authed_webapp_client):
    response = authed_webapp_client.get("/webapp/review")
    assert response.status_code == 200


def test_login_with_wrong_secret(webapp_client):
    response = webapp_client.post(
        "/webapp/login",
        data={"secret": "wrong-secret"},
        follow_redirects=False,
    )
    assert response.status_code == 401


def test_create_memory(authed_webapp_client, db, vector_store):
    response = authed_webapp_client.post(
        "/webapp/memories/new",
        data={
            "title": "Test Memory",
            "category": "general",
            "content": "Test content",
            "tags": "tag1, tag2",
        },
        follow_redirects=False,
    )
    assert response.status_code == 302
    memories = db.list_all()
    assert len(memories) == 1
    assert memories[0].title == "Test Memory"
    assert memories[0].tags == ["tag1", "tag2"]


def test_memory_detail(authed_webapp_client, db):
    record = MemoryRecord(
        id="mem_test1",
        category=MemoryCategory.GENERAL,
        title="Test Memory",
        content="Test content",
        created_at=datetime.now(UTC),
        tags=["test"],
    )
    db.create(record)
    response = authed_webapp_client.get("/webapp/memories/mem_test1")
    assert response.status_code == 200
    assert "Test Memory" in response.text


def test_memory_update(authed_webapp_client, db):
    record = MemoryRecord(
        id="mem_test1",
        category=MemoryCategory.GENERAL,
        title="Original Title",
        content="Original content",
        created_at=datetime.now(UTC),
        tags=["test"],
    )
    db.create(record)
    response = authed_webapp_client.post(
        "/webapp/memories/mem_test1",
        data={
            "title": "Updated Title",
            "category": "profile",
            "content": "Updated content",
            "tags": "updated",
            "needs_review": "on",
        },
        follow_redirects=False,
    )
    assert response.status_code == 302
    updated = db.get("mem_test1")
    assert updated.title == "Updated Title"
    assert updated.category.value == "profile"
    assert updated.needs_review is True


def test_memory_delete(authed_webapp_client, db):
    record = MemoryRecord(
        id="mem_test1",
        category=MemoryCategory.GENERAL,
        title="Test Memory",
        content="Test content",
        created_at=datetime.now(UTC),
        tags=["test"],
    )
    db.create(record)
    response = authed_webapp_client.delete("/webapp/memories/mem_test1")
    assert response.status_code == 200
    assert db.get("mem_test1") is None


def test_bulk_delete(authed_webapp_client, db):
    record1 = MemoryRecord(
        id="mem_test1",
        category=MemoryCategory.GENERAL,
        title="Memory 1",
        content="Content 1",
        created_at=datetime.now(UTC),
        tags=[],
    )
    record2 = MemoryRecord(
        id="mem_test2",
        category=MemoryCategory.GENERAL,
        title="Memory 2",
        content="Content 2",
        created_at=datetime.now(UTC),
        tags=[],
    )
    db.create(record1)
    db.create(record2)
    response = authed_webapp_client.post(
        "/webapp/memories/bulk/delete",
        data={"record_ids": ["mem_test1", "mem_test2"]},
    )
    assert response.status_code == 200
    assert db.get("mem_test1") is None
    assert db.get("mem_test2") is None


def test_bulk_clear_review(authed_webapp_client, db):
    record1 = MemoryRecord(
        id="mem_test1",
        category=MemoryCategory.GENERAL,
        title="Memory 1",
        content="Content 1",
        created_at=datetime.now(UTC),
        tags=[],
        needs_review=True,
    )
    record2 = MemoryRecord(
        id="mem_test2",
        category=MemoryCategory.GENERAL,
        title="Memory 2",
        content="Content 2",
        created_at=datetime.now(UTC),
        tags=[],
        needs_review=True,
    )
    db.create(record1)
    db.create(record2)
    response = authed_webapp_client.post(
        "/webapp/memories/bulk/clear-review",
        data={"record_ids": ["mem_test1", "mem_test2"]},
    )
    assert response.status_code == 200
    assert db.get("mem_test1").needs_review is False
    assert db.get("mem_test2").needs_review is False


def test_bulk_approve_review(authed_webapp_client, db):
    record1 = MemoryRecord(
        id="mem_test1",
        category=MemoryCategory.GENERAL,
        title="Memory 1",
        content="Content 1",
        created_at=datetime.now(UTC),
        tags=[],
        needs_review=True,
    )
    record2 = MemoryRecord(
        id="mem_test2",
        category=MemoryCategory.GENERAL,
        title="Memory 2",
        content="Content 2",
        created_at=datetime.now(UTC),
        tags=[],
        needs_review=True,
    )
    db.create(record1)
    db.create(record2)
    response = authed_webapp_client.post(
        "/webapp/review/bulk/approve",
        data={"record_ids": ["mem_test1", "mem_test2"]},
    )
    assert response.status_code == 200
    assert db.get("mem_test1").needs_review is False
    assert db.get("mem_test2").needs_review is False


def test_memories_htmx_partial(authed_webapp_client):
    response = authed_webapp_client.get(
        "/webapp/memories", headers={"HX-Request": "true"}
    )
    assert response.status_code == 200
    assert "<table>" in response.text


def test_review_queue_with_memories(authed_webapp_client, db):
    record = MemoryRecord(
        id="mem_review1",
        category=MemoryCategory.GENERAL,
        title="Needs Review",
        content="Content",
        created_at=datetime.now(UTC),
        tags=[],
        needs_review=True,
    )
    db.create(record)
    response = authed_webapp_client.get("/webapp/review")
    assert response.status_code == 200
    assert "Needs Review" in response.text
