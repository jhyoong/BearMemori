"""Integration tests for the full assistant agent flow."""

import json
import pytest
import pytest_asyncio
import fakeredis.aioredis
from unittest.mock import AsyncMock, MagicMock

from assistant_svc.agent import Agent
from assistant_svc.briefing import BriefingBuilder
from assistant_svc.context import ContextManager
from assistant_svc.core_client import AssistantCoreClient
from assistant_svc.tools import ToolRegistry
from assistant_svc.tools.memories import search_memories, SEARCH_MEMORIES_SCHEMA
from assistant_svc.tools.tasks import list_tasks, LIST_TASKS_SCHEMA, create_task, CREATE_TASK_SCHEMA
from assistant_svc.tools.reminders import list_reminders, LIST_REMINDERS_SCHEMA
from assistant_svc.tools.events import list_events, LIST_EVENTS_SCHEMA


@pytest_asyncio.fixture
async def redis():
    r = fakeredis.aioredis.FakeRedis()
    yield r
    await r.aclose()


@pytest_asyncio.fixture
async def integration_stack(redis):
    """Build a full agent stack with mocked external dependencies (OpenAI + Core API)."""
    # Mock Core API client
    core_client = AsyncMock(spec=AssistantCoreClient)
    core_client.list_tasks.return_value = []
    core_client.list_reminders.return_value = []
    core_client.search_memories.return_value = []
    core_client.get_settings.return_value = MagicMock(timezone="UTC")

    # Real context manager with fake Redis
    ctx = ContextManager(
        redis=redis,
        context_window_tokens=128000,
        briefing_budget_tokens=5000,
        response_reserve_tokens=4000,
        session_timeout_seconds=1800,
    )

    # Real briefing builder
    briefing = BriefingBuilder(
        core_client=core_client,
        context_manager=ctx,
        budget_tokens=5000,
    )

    # Real tool registry with all tools
    registry = ToolRegistry()
    registry.register("search_memories", search_memories, SEARCH_MEMORIES_SCHEMA)
    registry.register("list_tasks", list_tasks, LIST_TASKS_SCHEMA)
    registry.register("create_task", create_task, CREATE_TASK_SCHEMA)
    registry.register("list_reminders", list_reminders, LIST_REMINDERS_SCHEMA)
    registry.register("list_events", list_events, LIST_EVENTS_SCHEMA)

    # Mock OpenAI client
    mock_openai = AsyncMock()

    agent = Agent(
        openai_client=mock_openai,
        model="gpt-4o",
        core_client=core_client,
        context_manager=ctx,
        briefing_builder=briefing,
        tool_registry=registry,
    )

    return {
        "agent": agent,
        "openai": mock_openai,
        "core_client": core_client,
        "context": ctx,
        "redis": redis,
    }


class TestIntegration:
    @pytest.mark.asyncio
    async def test_simple_conversation(self, integration_stack):
        """Simple message with no tool calls."""
        stack = integration_stack
        agent = stack["agent"]
        mock_openai = stack["openai"]

        choice = MagicMock()
        choice.message.content = "Hi! I'm your personal assistant."
        choice.message.tool_calls = None
        response = MagicMock()
        response.choices = [choice]
        mock_openai.chat.completions.create.return_value = response

        reply = await agent.handle_message(user_id=1, text="Hello")
        assert reply == "Hi! I'm your personal assistant."

    @pytest.mark.asyncio
    async def test_conversation_with_tool_call(self, integration_stack):
        """Message that triggers a tool call, then returns a final answer."""
        stack = integration_stack
        agent = stack["agent"]
        mock_openai = stack["openai"]
        core_client = stack["core_client"]

        # First LLM call returns tool call
        tool_call = MagicMock()
        tool_call.id = "call_abc"
        tool_call.function.name = "search_memories"
        tool_call.function.arguments = json.dumps({"query": "vacation"})
        first_choice = MagicMock()
        first_choice.message.content = None
        first_choice.message.tool_calls = [tool_call]
        first_choice.message.role = "assistant"
        first_resp = MagicMock()
        first_resp.choices = [first_choice]

        # Second LLM call returns text
        second_choice = MagicMock()
        second_choice.message.content = "You have a vacation planned for March."
        second_choice.message.tool_calls = None
        second_resp = MagicMock()
        second_resp.choices = [second_choice]

        mock_openai.chat.completions.create.side_effect = [first_resp, second_resp]
        core_client.search_memories.return_value = []

        reply = await agent.handle_message(user_id=1, text="Do I have any vacation plans?")
        assert "vacation" in reply.lower()
        assert mock_openai.chat.completions.create.call_count == 2

    @pytest.mark.asyncio
    async def test_history_persists_across_messages(self, integration_stack):
        """Chat history is saved and loaded between messages."""
        stack = integration_stack
        agent = stack["agent"]
        mock_openai = stack["openai"]
        redis = stack["redis"]

        choice = MagicMock()
        choice.message.content = "Response 1"
        choice.message.tool_calls = None
        resp = MagicMock()
        resp.choices = [choice]
        mock_openai.chat.completions.create.return_value = resp

        # First message
        await agent.handle_message(user_id=1, text="First message")

        # Verify history was saved
        raw = await redis.get("assistant:chat:1")
        assert raw is not None
        history = json.loads(raw)
        assert len(history) >= 2  # user + assistant

        # Second message -- reset mock
        choice2 = MagicMock()
        choice2.message.content = "Response 2"
        choice2.message.tool_calls = None
        resp2 = MagicMock()
        resp2.choices = [choice2]
        mock_openai.chat.completions.create.return_value = resp2

        await agent.handle_message(user_id=1, text="Second message")

        # History should now have 4 messages (2 user + 2 assistant)
        raw2 = await redis.get("assistant:chat:1")
        history2 = json.loads(raw2)
        assert len(history2) >= 4

    @pytest.mark.asyncio
    async def test_separate_users_isolated(self, integration_stack):
        """Different users have separate conversations."""
        stack = integration_stack
        agent = stack["agent"]
        mock_openai = stack["openai"]
        redis = stack["redis"]

        choice = MagicMock()
        choice.message.content = "Hello user"
        choice.message.tool_calls = None
        resp = MagicMock()
        resp.choices = [choice]
        mock_openai.chat.completions.create.return_value = resp

        await agent.handle_message(user_id=1, text="I'm user 1")
        await agent.handle_message(user_id=2, text="I'm user 2")

        h1 = json.loads(await redis.get("assistant:chat:1"))
        h2 = json.loads(await redis.get("assistant:chat:2"))
        assert h1[0]["content"] == "I'm user 1"
        assert h2[0]["content"] == "I'm user 2"

    @pytest.mark.asyncio
    async def test_briefing_fetches_from_core(self, integration_stack):
        """Agent calls Core API to build the briefing on each message."""
        stack = integration_stack
        agent = stack["agent"]
        mock_openai = stack["openai"]
        core_client = stack["core_client"]

        choice = MagicMock()
        choice.message.content = "OK"
        choice.message.tool_calls = None
        resp = MagicMock()
        resp.choices = [choice]
        mock_openai.chat.completions.create.return_value = resp

        await agent.handle_message(user_id=42, text="Hi")

        # Verify briefing-related API calls were made
        core_client.list_tasks.assert_called()
        core_client.list_reminders.assert_called()
