from __future__ import annotations

from starlette.responses import Response
from starlette.types import ASGIApp, Receive, Scope, Send

from bearmemori.config import Settings
from bearmemori.storage.database import MemoryDatabase
from bearmemori.storage.vector_store import VectorStore


class BearerAuthMiddleware:
    """ASGI middleware that enforces Bearer token auth when a secret is configured."""

    def __init__(self, app: ASGIApp, secret: str) -> None:
        self.app = app
        self.secret = secret

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if self.secret and scope["type"] in ("http", "websocket"):
            headers = dict(scope.get("headers", []))
            auth = headers.get(b"authorization", b"").decode()
            if not auth.startswith("Bearer ") or auth[7:] != self.secret:
                response = Response("Unauthorized", status_code=401)
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


def create_mcp_app(
    db: MemoryDatabase,
    vector_store: VectorStore,
    settings: Settings,
):
    """Build and return the MCP ASGI sub-app."""
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("BearMemori")

    # Tools will be registered in subsequent tasks

    app = mcp.sse_app()
    if settings.webapp_secret:
        app = BearerAuthMiddleware(app, settings.webapp_secret)
    return app
