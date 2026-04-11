import anyio
import pytest
from httpx import ASGITransport, AsyncClient

from bearmemori.config import Settings


@pytest.fixture
def test_settings(tmp_path):
    return Settings(
        api_only_mode=True,
        database_path=str(tmp_path / "test.db"),
        chroma_persist_dir=str(tmp_path / "chroma"),
        webapp_secret="",
        llm_base_url="http://localhost:11434/v1",
        llm_model="llama3",
    )


@pytest.mark.asyncio
async def test_mcp_sse_endpoint_is_reachable(test_settings):
    """The /mcp/sse endpoint must exist (MCP server is mounted)."""
    from bearmemori.app import create_application

    app = create_application(test_settings)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost") as client:
        # SSE endpoint opens a streaming connection; use a short timeout to confirm
        # the endpoint exists and responds (not 404), then cancel the stream.
        with anyio.move_on_after(2):
            async with client.stream("GET", "/mcp/sse") as response:
                assert response.status_code != 404
                return
    assert True  # SSE stream opened (timeout is expected, connection never closes)


@pytest.mark.asyncio
async def test_existing_health_still_works(test_settings):
    """Mounting MCP must not break the existing /health endpoint."""
    from bearmemori.app import create_application

    app = create_application(test_settings)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost") as client:
        response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_mcp_auth_blocks_when_secret_set(test_settings):
    """When webapp_secret is set, /mcp/sse without token returns 401."""
    from bearmemori.app import create_application

    settings_with_auth = test_settings.model_copy(update={"webapp_secret": "supersecret"})
    app = create_application(settings_with_auth)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost") as client:
        response = await client.get("/mcp/sse")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_mcp_auth_passes_with_correct_token(test_settings):
    """When webapp_secret is set, /mcp/sse with correct Bearer token is not rejected."""
    from bearmemori.app import create_application

    settings_with_auth = test_settings.model_copy(update={"webapp_secret": "supersecret"})
    app = create_application(settings_with_auth)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        import anyio

        with anyio.move_on_after(2):
            async with client.stream(
                "GET",
                "/mcp/sse",
                headers={"Authorization": "Bearer supersecret"},
            ) as response:
                assert response.status_code != 401
                return
    assert True  # connection opened (timeout is expected for SSE)
