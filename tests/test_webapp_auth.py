import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from bearmemori.webapp.auth import WebappAuthMiddleware


def test_login_page_accessible_without_auth():
    """Login page should be accessible without a session (middleware passes through)."""
    app = FastAPI()

    @app.get("/webapp/login")
    async def login_page(request: Request):
        return {"status": "ok"}

    app.add_middleware(WebappAuthMiddleware, secret="test-secret")

    client = TestClient(app)
    response = client.get("/webapp/login")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_protected_route_redirects_without_auth():
    """Protected webapp routes should redirect to login without session."""
    app = FastAPI()

    @app.get("/webapp/memories")
    async def memories(request: Request):
        return {"memories": []}

    app.add_middleware(WebappAuthMiddleware, secret="test-secret")

    client = TestClient(app)
    response = client.get("/webapp/memories", follow_redirects=False)
    assert response.status_code == 302
    assert "/webapp/login" in response.headers["location"]


def test_protected_route_allowed_with_valid_session():
    """Protected routes should allow access with valid session cookie."""
    app = FastAPI()

    @app.get("/webapp/memories")
    async def memories(request: Request):
        return {"memories": []}

    app.add_middleware(WebappAuthMiddleware, secret="test-secret")

    client = TestClient(app)
    # Create a new middleware instance to get the valid token
    from bearmemori.webapp.auth import WebappAuthMiddleware as AuthMiddleware
    auth = AuthMiddleware(app, "test-secret")
    # Manually set the valid session cookie
    client.cookies.set("webapp_session", auth._token)
    response = client.get("/webapp/memories")
    assert response.status_code == 200
    assert response.json()["memories"] == []


def test_verify_secret_with_correct_secret():
    """verify_secret should return True for correct secret."""
    app = FastAPI()
    auth = WebappAuthMiddleware(app, "test-secret")

    assert auth.verify_secret("test-secret") is True
    assert auth.verify_secret("wrong-secret") is False


def test_non_webapp_routes_allowed_without_auth():
    """Non-webapp routes should be accessible without auth."""
    app = FastAPI()

    @app.get("/health")
    async def health(request: Request):
        return {"status": "ok"}

    app.add_middleware(WebappAuthMiddleware, secret="test-secret")

    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_static_files_accessible_without_auth():
    """Static files should be accessible without auth."""
    app = FastAPI()

    @app.get("/webapp/static/{path:path}")
    async def static_files(path: str):
        return {"path": path}

    app.add_middleware(WebappAuthMiddleware, secret="test-secret")

    client = TestClient(app)
    response = client.get("/webapp/static/css/style.css")
    assert response.status_code == 200
    assert response.json()["path"] == "css/style.css"
