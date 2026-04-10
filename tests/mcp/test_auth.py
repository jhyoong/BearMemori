import pytest
from httpx import ASGITransport, AsyncClient
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from bearmemori.mcp.server import BearerAuthMiddleware


def _make_dummy_app():
    """A minimal ASGI app that returns 200 OK."""

    async def homepage(request):
        return PlainTextResponse("ok")

    return Starlette(routes=[Route("/", homepage)])


@pytest.mark.asyncio
async def test_auth_middleware_no_secret_allows_all():
    """When secret is empty, all requests pass through."""
    app = BearerAuthMiddleware(_make_dummy_app(), secret="")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_auth_middleware_with_secret_rejects_missing_header():
    """When secret is set and Authorization header is absent, return 401."""
    app = BearerAuthMiddleware(_make_dummy_app(), secret="mysecret")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_auth_middleware_with_secret_rejects_wrong_token():
    """When secret is set and token is wrong, return 401."""
    app = BearerAuthMiddleware(_make_dummy_app(), secret="mysecret")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/", headers={"Authorization": "Bearer wrongtoken"})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_auth_middleware_with_secret_allows_correct_token():
    """When secret is set and token matches, request passes through."""
    app = BearerAuthMiddleware(_make_dummy_app(), secret="mysecret")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/", headers={"Authorization": "Bearer mysecret"})
    assert response.status_code == 200
