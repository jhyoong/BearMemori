import pytest
from fastapi.testclient import TestClient
from bearmemori.api.routes import create_app
from bearmemori.storage.database import MemoryDatabase
from bearmemori.storage.models import Memory


@pytest.fixture
def db(tmp_path):
    db_path = str(tmp_path / "test.db")
    database = MemoryDatabase(db_path)
    database.initialize()
    return database


@pytest.fixture
def client(db):
    app = create_app(db)
    return TestClient(app)


@pytest.fixture
def seeded_db(db):
    db.create(Memory(
        id="mem-1",
        content="User prefers dark mode",
        raw_input="I like dark mode",
        memory_type="preference",
        tags=["ui", "preference"],
        source="telegram",
    ))
    db.create(Memory(
        id="mem-2",
        content="Meeting with John on Friday",
        raw_input="meeting john friday",
        memory_type="event",
        tags=["meeting", "john"],
        source="telegram",
    ))
    return db


def test_get_memory(client, seeded_db):
    response = client.get("/memories/mem-1")
    assert response.status_code == 200
    data = response.json()
    assert data["content"] == "User prefers dark mode"


def test_get_memory_not_found(client):
    response = client.get("/memories/nope")
    assert response.status_code == 404


def test_list_memories(client, seeded_db):
    response = client.get("/memories")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2


def test_list_memories_filter_by_type(client, seeded_db):
    response = client.get("/memories?memory_type=preference")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["memory_type"] == "preference"


def test_create_memory(client):
    response = client.post("/memories", json={
        "content": "Likes coffee",
        "memory_type": "preference",
        "tags": ["food"],
    })
    assert response.status_code == 201
    data = response.json()
    assert data["content"] == "Likes coffee"
    assert data["id"]


def test_update_memory(client, seeded_db):
    response = client.put("/memories/mem-1", json={
        "content": "User prefers light mode",
    })
    assert response.status_code == 200
    data = response.json()
    assert data["content"] == "User prefers light mode"


def test_delete_memory(client, seeded_db):
    response = client.delete("/memories/mem-1")
    assert response.status_code == 204
    assert client.get("/memories/mem-1").status_code == 404


def test_search_keyword(client, seeded_db):
    response = client.post("/memories/search", json={
        "query": "dark mode",
        "mode": "keyword",
    })
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1
