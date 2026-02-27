"""Tests for assistant tool registry and tool functions."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from assistant_svc.tools import ToolRegistry
from assistant_svc.tools.memories import (
    SEARCH_MEMORIES_SCHEMA,
    GET_MEMORY_SCHEMA,
    search_memories,
    get_memory,
)
from assistant_svc.tools.tasks import (
    LIST_TASKS_SCHEMA,
    CREATE_TASK_SCHEMA,
    list_tasks,
    create_task,
)
from assistant_svc.tools.reminders import (
    LIST_REMINDERS_SCHEMA,
    CREATE_REMINDER_SCHEMA,
    list_reminders,
    create_reminder,
)
from assistant_svc.tools.events import (
    LIST_EVENTS_SCHEMA,
    list_events,
)


# ---------------------------------------------------------------------------
# ToolRegistry tests
# ---------------------------------------------------------------------------


class TestToolRegistry:
    def _make_registry(self) -> tuple[ToolRegistry, AsyncMock, dict]:
        """Return a registry with one registered tool, the mock func, and schema."""
        registry = ToolRegistry()
        mock_func = AsyncMock(return_value={"result": "ok"})
        schema = {"type": "function", "function": {"name": "my_tool"}}
        registry.register("my_tool", mock_func, schema)
        return registry, mock_func, schema

    def test_register_and_tool_names(self):
        registry, _, _ = self._make_registry()
        assert registry.tool_names() == ["my_tool"]

    def test_get_schema(self):
        registry, _, schema = self._make_registry()
        assert registry.get_schema("my_tool") == schema

    def test_get_function(self):
        registry, mock_func, _ = self._make_registry()
        assert registry.get_function("my_tool") is mock_func

    def test_get_all_schemas(self):
        registry, _, schema = self._make_registry()
        schemas = registry.get_all_schemas()
        assert len(schemas) == 1
        assert schemas[0] == schema

    def test_get_all_schemas_multiple(self):
        registry = ToolRegistry()
        schema_a = {"type": "function", "function": {"name": "tool_a"}}
        schema_b = {"type": "function", "function": {"name": "tool_b"}}
        registry.register("tool_a", AsyncMock(), schema_a)
        registry.register("tool_b", AsyncMock(), schema_b)
        schemas = registry.get_all_schemas()
        assert len(schemas) == 2

    @pytest.mark.asyncio
    async def test_execute_calls_function(self):
        registry, mock_func, _ = self._make_registry()
        client = MagicMock()
        result = await registry.execute("my_tool", client, foo="bar")
        mock_func.assert_called_once_with(client, foo="bar")
        assert result == {"result": "ok"}

    def test_get_function_unknown_raises_key_error(self):
        registry = ToolRegistry()
        with pytest.raises(KeyError):
            registry.get_function("does_not_exist")

    def test_get_schema_unknown_raises_key_error(self):
        registry = ToolRegistry()
        with pytest.raises(KeyError):
            registry.get_schema("does_not_exist")

    @pytest.mark.asyncio
    async def test_execute_unknown_raises_key_error(self):
        registry = ToolRegistry()
        with pytest.raises(KeyError):
            await registry.execute("does_not_exist", MagicMock())


# ---------------------------------------------------------------------------
# memories tool tests
# ---------------------------------------------------------------------------


class TestSearchMemories:
    def _make_search_result(self, memory_id: str, content: str, tags: list[str], score: float):
        tag_mocks = [MagicMock(tag=t) for t in tags]
        memory = MagicMock(id=memory_id, content=content, tags=tag_mocks)
        result = MagicMock(memory=memory, score=score)
        return result

    @pytest.mark.asyncio
    async def test_returns_formatted_list(self):
        client = AsyncMock()
        r1 = self._make_search_result("m1", "content one", ["tag_a", "tag_b"], 0.9)
        r2 = self._make_search_result("m2", "content two", [], 0.5)
        client.search_memories = AsyncMock(return_value=[r1, r2])

        results = await search_memories(client, query="test", owner_user_id=42)

        client.search_memories.assert_called_once_with(query="test", owner_user_id=42)
        assert len(results) == 2
        assert results[0] == {"memory_id": "m1", "content": "content one", "tags": ["tag_a", "tag_b"], "score": 0.9}
        assert results[1] == {"memory_id": "m2", "content": "content two", "tags": [], "score": 0.5}

    @pytest.mark.asyncio
    async def test_empty_results(self):
        client = AsyncMock()
        client.search_memories = AsyncMock(return_value=[])
        results = await search_memories(client, query="nothing", owner_user_id=1)
        assert results == []

    def test_schema_name(self):
        assert SEARCH_MEMORIES_SCHEMA["function"]["name"] == "search_memories"
        assert "query" in SEARCH_MEMORIES_SCHEMA["function"]["parameters"]["properties"]
        assert "owner_user_id" not in SEARCH_MEMORIES_SCHEMA["function"]["parameters"]["properties"]


class TestGetMemory:
    @pytest.mark.asyncio
    async def test_returns_formatted_dict(self):
        client = AsyncMock()
        tag_mocks = [MagicMock(tag="alpha"), MagicMock(tag="beta")]
        mem = MagicMock(
            id="m99",
            content="some content",
            status="confirmed",
            is_pinned=False,
            tags=tag_mocks,
            created_at="2026-01-01T00:00:00",
        )
        client.get_memory = AsyncMock(return_value=mem)

        result = await get_memory(client, memory_id="m99")

        client.get_memory.assert_called_once_with("m99")
        assert result["id"] == "m99"
        assert result["content"] == "some content"
        assert result["status"] == "confirmed"
        assert result["is_pinned"] is False
        assert result["tags"] == ["alpha", "beta"]
        assert "created_at" in result

    @pytest.mark.asyncio
    async def test_returns_error_dict_when_not_found(self):
        client = AsyncMock()
        client.get_memory = AsyncMock(return_value=None)

        result = await get_memory(client, memory_id="missing")

        assert result == {"error": "Memory not found"}

    def test_schema_name(self):
        assert GET_MEMORY_SCHEMA["function"]["name"] == "get_memory"
        assert "memory_id" in GET_MEMORY_SCHEMA["function"]["parameters"]["properties"]
        assert "owner_user_id" not in GET_MEMORY_SCHEMA["function"]["parameters"]["properties"]


# ---------------------------------------------------------------------------
# tasks tool tests
# ---------------------------------------------------------------------------


class TestListTasks:
    def _make_task(self, task_id: str, description: str, state: str, due_at=None, memory_id="m1"):
        return MagicMock(id=task_id, description=description, state=state, due_at=due_at, memory_id=memory_id)

    @pytest.mark.asyncio
    async def test_returns_formatted_list(self):
        client = AsyncMock()
        t1 = self._make_task("t1", "do something", "NOT_DONE")
        t2 = self._make_task("t2", "done thing", "DONE", due_at="2026-02-01T10:00:00")
        client.list_tasks = AsyncMock(return_value=[t1, t2])

        results = await list_tasks(client, owner_user_id=7)

        client.list_tasks.assert_called_once_with(owner_user_id=7, state=None)
        assert len(results) == 2
        assert results[0]["id"] == "t1"
        assert results[0]["state"] == "NOT_DONE"
        assert results[0]["due_at"] is None

    @pytest.mark.asyncio
    async def test_passes_state_filter(self):
        client = AsyncMock()
        client.list_tasks = AsyncMock(return_value=[])

        await list_tasks(client, owner_user_id=7, state="NOT_DONE")

        client.list_tasks.assert_called_once_with(owner_user_id=7, state="NOT_DONE")

    def test_schema_name(self):
        assert LIST_TASKS_SCHEMA["function"]["name"] == "list_tasks"
        assert "owner_user_id" not in LIST_TASKS_SCHEMA["function"]["parameters"]["properties"]


class TestCreateTask:
    @pytest.mark.asyncio
    async def test_calls_client_and_returns_formatted(self):
        client = AsyncMock()
        task = MagicMock(id="t10", description="write tests", state="NOT_DONE", due_at=None)
        client.create_task = AsyncMock(return_value=task)

        result = await create_task(
            client,
            memory_id="m1",
            description="write tests",
            owner_user_id=5,
        )

        client.create_task.assert_called_once_with(
            memory_id="m1",
            owner_user_id=5,
            description="write tests",
            due_at=None,
        )
        assert result["id"] == "t10"
        assert result["description"] == "write tests"
        assert result["state"] == "NOT_DONE"
        assert result["due_at"] is None

    @pytest.mark.asyncio
    async def test_passes_due_at(self):
        client = AsyncMock()
        task = MagicMock(id="t11", description="task", state="NOT_DONE", due_at="2026-03-01T10:00:00")
        client.create_task = AsyncMock(return_value=task)

        await create_task(
            client,
            memory_id="m2",
            description="task",
            owner_user_id=5,
            due_at="2026-03-01T10:00:00",
        )

        client.create_task.assert_called_once_with(
            memory_id="m2",
            owner_user_id=5,
            description="task",
            due_at="2026-03-01T10:00:00",
        )

    def test_schema_required_fields(self):
        required = CREATE_TASK_SCHEMA["function"]["parameters"]["required"]
        assert "memory_id" in required
        assert "description" in required
        assert "owner_user_id" not in CREATE_TASK_SCHEMA["function"]["parameters"]["properties"]


# ---------------------------------------------------------------------------
# reminders tool tests
# ---------------------------------------------------------------------------


class TestListReminders:
    @pytest.mark.asyncio
    async def test_returns_formatted_list(self):
        client = AsyncMock()
        r1 = MagicMock(id="r1", text="call dentist", fire_at="2026-03-01T09:00:00", fired=False, memory_id="m1")
        client.list_reminders = AsyncMock(return_value=[r1])

        results = await list_reminders(client, owner_user_id=3)

        client.list_reminders.assert_called_once_with(owner_user_id=3, upcoming_only=True)
        assert len(results) == 1
        assert results[0]["id"] == "r1"
        assert results[0]["text"] == "call dentist"
        assert results[0]["fired"] is False

    @pytest.mark.asyncio
    async def test_passes_upcoming_only_false(self):
        client = AsyncMock()
        client.list_reminders = AsyncMock(return_value=[])

        await list_reminders(client, owner_user_id=3, upcoming_only=False)

        client.list_reminders.assert_called_once_with(owner_user_id=3, upcoming_only=False)

    def test_schema_name(self):
        assert LIST_REMINDERS_SCHEMA["function"]["name"] == "list_reminders"
        assert "owner_user_id" not in LIST_REMINDERS_SCHEMA["function"]["parameters"]["properties"]


class TestCreateReminder:
    @pytest.mark.asyncio
    async def test_calls_client_and_returns_formatted(self):
        client = AsyncMock()
        reminder = MagicMock(id="r10", text="buy milk", fire_at="2026-03-05T08:00:00")
        client.create_reminder = AsyncMock(return_value=reminder)

        result = await create_reminder(
            client,
            memory_id="m1",
            text="buy milk",
            fire_at="2026-03-05T08:00:00",
            owner_user_id=9,
        )

        client.create_reminder.assert_called_once_with(
            memory_id="m1",
            owner_user_id=9,
            text="buy milk",
            fire_at="2026-03-05T08:00:00",
        )
        assert result["id"] == "r10"
        assert result["text"] == "buy milk"
        assert "fire_at" in result

    def test_schema_required_fields(self):
        required = CREATE_REMINDER_SCHEMA["function"]["parameters"]["required"]
        assert "memory_id" in required
        assert "text" in required
        assert "fire_at" in required
        assert "owner_user_id" not in CREATE_REMINDER_SCHEMA["function"]["parameters"]["properties"]


# ---------------------------------------------------------------------------
# events tool tests
# ---------------------------------------------------------------------------


class TestListEvents:
    @pytest.mark.asyncio
    async def test_returns_formatted_list(self):
        client = AsyncMock()
        e1 = MagicMock(id="ev1", description="team meeting", event_time="2026-03-10T14:00:00", status="confirmed")
        client.list_events = AsyncMock(return_value=[e1])

        results = await list_events(client, owner_user_id=11)

        client.list_events.assert_called_once_with(owner_user_id=11, status=None)
        assert len(results) == 1
        assert results[0]["id"] == "ev1"
        assert results[0]["description"] == "team meeting"
        assert results[0]["status"] == "confirmed"

    @pytest.mark.asyncio
    async def test_passes_status_filter(self):
        client = AsyncMock()
        client.list_events = AsyncMock(return_value=[])

        await list_events(client, owner_user_id=11, status="pending")

        client.list_events.assert_called_once_with(owner_user_id=11, status="pending")

    def test_schema_name(self):
        assert LIST_EVENTS_SCHEMA["function"]["name"] == "list_events"
        assert "owner_user_id" not in LIST_EVENTS_SCHEMA["function"]["parameters"]["properties"]

    def test_schema_status_enum(self):
        props = LIST_EVENTS_SCHEMA["function"]["parameters"]["properties"]
        assert props["status"]["enum"] == ["pending", "confirmed", "rejected"]
