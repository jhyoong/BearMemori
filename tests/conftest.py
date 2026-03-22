import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bearmemori.storage.database import MemoryDatabase
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
    # Create a valid session
    response = client.post(
        "/webapp/login",
        data={"secret": "test-secret"},
        follow_redirects=False,
    )
    # Store the cookie for subsequent requests
    client.cookies.update(response.cookies)
    return client
