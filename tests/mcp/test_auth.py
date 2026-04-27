from fastapi import FastAPI
from fastapi.testclient import TestClient

from bearmemori.webapp.auth import WebappAuthMiddleware


def _make_mcp_app(secret: str) -> TestClient:
    app = FastAPI()

    @app.get("/mcp/sse")
    async def mcp_sse():
        return {"status": "ok"}

    app.add_middleware(WebappAuthMiddleware, secret=secret)
    return TestClient(app, raise_server_exceptions=False)


def test_mcp_auth_rejects_missing_header():
    """When Authorization header is absent, /mcp paths return 401."""
    client = _make_mcp_app("mysecret")
    response = client.get("/mcp/sse")
    assert response.status_code == 401


def test_mcp_auth_rejects_wrong_token():
    """When token is wrong, /mcp paths return 401."""
    client = _make_mcp_app("mysecret")
    response = client.get("/mcp/sse", headers={"Authorization": "Bearer wrongtoken"})
    assert response.status_code == 401


def test_mcp_auth_allows_correct_token():
    """When token matches secret, /mcp paths return 200."""
    client = _make_mcp_app("mysecret")
    response = client.get("/mcp/sse", headers={"Authorization": "Bearer mysecret"})
    assert response.status_code == 200
