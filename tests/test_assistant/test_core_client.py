import httpx
import pytest
import pytest_asyncio

from assistant_svc.core_client import (
    AssistantCoreClient,
    CoreClientError,
    CoreNotFoundError,
    CoreUnavailableError,
)

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

MEMORY_JSON = {
    "id": "m1",
    "owner_user_id": 1,
    "content": "test memory",
    "media_type": None,
    "media_file_id": None,
    "media_local_path": None,
    "status": "confirmed",
    "pending_expires_at": None,
    "is_pinned": False,
    "created_at": "2026-01-01T00:00:00",
    "updated_at": "2026-01-01T00:00:00",
    "tags": [],
    "confirmed_at": None,
}

TASK_JSON = {
    "id": "t1",
    "memory_id": "m1",
    "owner_user_id": 1,
    "description": "do something",
    "state": "NOT_DONE",
    "due_at": None,
    "recurrence_minutes": None,
    "completed_at": None,
    "created_at": "2026-01-01T00:00:00",
    "updated_at": "2026-01-01T00:00:00",
}

REMINDER_JSON = {
    "id": "r1",
    "memory_id": "m1",
    "owner_user_id": 1,
    "text": "remember this",
    "fire_at": "2026-06-01T09:00:00",
    "recurrence_minutes": None,
    "fired": False,
    "created_at": "2026-01-01T00:00:00",
    "updated_at": None,
}

EVENT_JSON = {
    "id": "e1",
    "memory_id": "m1",
    "owner_user_id": 1,
    "event_time": "2026-06-01T10:00:00",
    "description": "team meeting",
    "status": "confirmed",
    "source_type": "manual",
    "source_detail": None,
    "reminder_id": None,
    "created_at": "2026-01-01T00:00:00",
    "updated_at": "2026-01-01T00:00:00",
}

SETTINGS_JSON = {
    "user_id": 1,
    "timezone": "UTC",
    "language": "en",
    "created_at": "2026-01-01T00:00:00",
    "updated_at": "2026-01-01T00:00:00",
}


class MockTransport(httpx.AsyncBaseTransport):
    def __init__(self):
        self.requests: list[httpx.Request] = []
        self.responses: dict[str, tuple[int, object]] = {}

    def set_response(self, method_path: str, status: int, json_data: object) -> None:
        self.responses[method_path] = (status, json_data)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        key = f"{request.method} {request.url.path}"
        if key not in self.responses:
            return httpx.Response(404, json={"detail": "not found"}, request=request)
        status, data = self.responses[key]
        return httpx.Response(status, json=data, request=request)


@pytest_asyncio.fixture
async def mock_transport() -> MockTransport:
    return MockTransport()


@pytest_asyncio.fixture
async def client(mock_transport: MockTransport):
    http = httpx.AsyncClient(transport=mock_transport, base_url="http://test")
    c = AssistantCoreClient.__new__(AssistantCoreClient)
    c._client = http
    yield c
    await http.aclose()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_memories(client: AssistantCoreClient, mock_transport: MockTransport):
    mock_transport.set_response(
        "GET /search",
        200,
        [{"memory": MEMORY_JSON, "score": 1.0}],
    )

    results = await client.search_memories(query="test", owner_user_id=1)

    assert len(results) == 1
    assert results[0].memory.id == "m1"
    assert results[0].score == 1.0

    sent = mock_transport.requests[0]
    assert "q=test" in str(sent.url)
    assert "owner=1" in str(sent.url)


@pytest.mark.asyncio
async def test_search_memories_error(client: AssistantCoreClient, mock_transport: MockTransport):
    mock_transport.set_response("GET /search", 500, {"detail": "server error"})

    with pytest.raises(CoreClientError):
        await client.search_memories(query="test", owner_user_id=1)


@pytest.mark.asyncio
async def test_get_memory(client: AssistantCoreClient, mock_transport: MockTransport):
    mock_transport.set_response("GET /memories/m1", 200, MEMORY_JSON)

    memory = await client.get_memory("m1")

    assert memory is not None
    assert memory.id == "m1"
    assert memory.content == "test memory"
    assert mock_transport.requests[0].url.path == "/memories/m1"


@pytest.mark.asyncio
async def test_get_memory_not_found(client: AssistantCoreClient, mock_transport: MockTransport):
    mock_transport.set_response("GET /memories/missing", 404, {"detail": "not found"})

    result = await client.get_memory("missing")

    assert result is None


@pytest.mark.asyncio
async def test_get_memory_server_error(client: AssistantCoreClient, mock_transport: MockTransport):
    mock_transport.set_response("GET /memories/m1", 500, {"detail": "error"})

    with pytest.raises(CoreClientError):
        await client.get_memory("m1")


@pytest.mark.asyncio
async def test_list_tasks(client: AssistantCoreClient, mock_transport: MockTransport):
    mock_transport.set_response("GET /tasks", 200, [TASK_JSON])

    tasks = await client.list_tasks(owner_user_id=1)

    assert len(tasks) == 1
    assert tasks[0].id == "t1"
    assert tasks[0].description == "do something"

    sent = mock_transport.requests[0]
    assert "owner_user_id=1" in str(sent.url)


@pytest.mark.asyncio
async def test_list_tasks_with_state(client: AssistantCoreClient, mock_transport: MockTransport):
    mock_transport.set_response("GET /tasks", 200, [TASK_JSON])

    tasks = await client.list_tasks(owner_user_id=1, state="NOT_DONE")

    assert len(tasks) == 1
    sent = mock_transport.requests[0]
    assert "state=NOT_DONE" in str(sent.url)


@pytest.mark.asyncio
async def test_list_reminders(client: AssistantCoreClient, mock_transport: MockTransport):
    mock_transport.set_response("GET /reminders", 200, [REMINDER_JSON])

    reminders = await client.list_reminders(owner_user_id=1)

    assert len(reminders) == 1
    assert reminders[0].id == "r1"
    assert reminders[0].text == "remember this"

    sent = mock_transport.requests[0]
    assert "owner_user_id=1" in str(sent.url)


@pytest.mark.asyncio
async def test_list_reminders_with_filters(
    client: AssistantCoreClient, mock_transport: MockTransport
):
    mock_transport.set_response("GET /reminders", 200, [REMINDER_JSON])

    reminders = await client.list_reminders(owner_user_id=1, fired=False, upcoming_only=True)

    assert len(reminders) == 1
    sent = mock_transport.requests[0]
    url_str = str(sent.url)
    assert "fired=False" in url_str or "fired=false" in url_str
    assert "upcoming_only=True" in url_str or "upcoming_only=true" in url_str


@pytest.mark.asyncio
async def test_list_events(client: AssistantCoreClient, mock_transport: MockTransport):
    mock_transport.set_response("GET /events", 200, [EVENT_JSON])

    events = await client.list_events(owner_user_id=1)

    assert len(events) == 1
    assert events[0].id == "e1"
    assert events[0].description == "team meeting"

    sent = mock_transport.requests[0]
    assert "owner_user_id=1" in str(sent.url)


@pytest.mark.asyncio
async def test_list_events_with_status(
    client: AssistantCoreClient, mock_transport: MockTransport
):
    mock_transport.set_response("GET /events", 200, [EVENT_JSON])

    events = await client.list_events(owner_user_id=1, status="confirmed")

    assert len(events) == 1
    sent = mock_transport.requests[0]
    assert "status=confirmed" in str(sent.url)


@pytest.mark.asyncio
async def test_create_task(client: AssistantCoreClient, mock_transport: MockTransport):
    mock_transport.set_response("POST /tasks", 201, TASK_JSON)

    task = await client.create_task(
        memory_id="m1",
        owner_user_id=1,
        description="do something",
    )

    assert task.id == "t1"
    assert task.memory_id == "m1"
    assert task.description == "do something"

    sent = mock_transport.requests[0]
    assert sent.method == "POST"
    assert sent.url.path == "/tasks"


@pytest.mark.asyncio
async def test_create_task_not_found(client: AssistantCoreClient, mock_transport: MockTransport):
    mock_transport.set_response("POST /tasks", 404, {"detail": "memory not found"})

    with pytest.raises(CoreNotFoundError):
        await client.create_task(
            memory_id="missing",
            owner_user_id=1,
            description="do something",
        )


@pytest.mark.asyncio
async def test_create_reminder(client: AssistantCoreClient, mock_transport: MockTransport):
    mock_transport.set_response("POST /reminders", 201, REMINDER_JSON)

    reminder = await client.create_reminder(
        memory_id="m1",
        owner_user_id=1,
        text="remember this",
        fire_at="2026-06-01T09:00:00",
    )

    assert reminder.id == "r1"
    assert reminder.text == "remember this"
    assert reminder.memory_id == "m1"

    sent = mock_transport.requests[0]
    assert sent.method == "POST"
    assert sent.url.path == "/reminders"


@pytest.mark.asyncio
async def test_create_reminder_not_found(
    client: AssistantCoreClient, mock_transport: MockTransport
):
    mock_transport.set_response("POST /reminders", 404, {"detail": "memory not found"})

    with pytest.raises(CoreNotFoundError):
        await client.create_reminder(
            memory_id="missing",
            owner_user_id=1,
            text="remember this",
            fire_at="2026-06-01T09:00:00",
        )


@pytest.mark.asyncio
async def test_get_settings(client: AssistantCoreClient, mock_transport: MockTransport):
    mock_transport.set_response("GET /settings/1", 200, SETTINGS_JSON)

    settings = await client.get_settings(user_id=1)

    assert settings.user_id == 1
    assert settings.timezone == "UTC"
    assert settings.language == "en"

    sent = mock_transport.requests[0]
    assert sent.url.path == "/settings/1"


@pytest.mark.asyncio
async def test_get_settings_not_found(client: AssistantCoreClient, mock_transport: MockTransport):
    mock_transport.set_response("GET /settings/999", 404, {"detail": "not found"})

    with pytest.raises(CoreNotFoundError):
        await client.get_settings(user_id=999)


@pytest.mark.asyncio
async def test_unavailable_error_on_connect_error(mock_transport: MockTransport):
    """ConnectError from httpx should be wrapped in CoreUnavailableError."""

    class ErrorTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused")

    http = httpx.AsyncClient(transport=ErrorTransport(), base_url="http://test")
    c = AssistantCoreClient.__new__(AssistantCoreClient)
    c._client = http

    try:
        with pytest.raises(CoreUnavailableError):
            await c.search_memories(query="test", owner_user_id=1)
    finally:
        await http.aclose()
