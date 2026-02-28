"""Tests for the assistant agent core."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from assistant_svc.agent import Agent, MAX_TOOL_ITERATIONS


@pytest.fixture
def mock_openai():
    return AsyncMock()


@pytest.fixture
def mock_core_client():
    return AsyncMock()


@pytest.fixture
def mock_context():
    ctx = AsyncMock()
    ctx.load_history.return_value = []
    ctx.needs_summarization.return_value = False
    ctx.chat_budget_tokens = 100000
    ctx.count_tokens.side_effect = lambda t: len(t.split())
    ctx.count_messages_tokens.return_value = 0
    return ctx


@pytest.fixture
def mock_briefing():
    b = AsyncMock()
    b.build.return_value = "No upcoming tasks or reminders."
    return b


@pytest.fixture
def mock_registry():
    reg = MagicMock()
    reg.get_all_schemas.return_value = []
    reg.execute = AsyncMock()
    return reg


@pytest.fixture
def agent(mock_openai, mock_core_client, mock_context, mock_briefing, mock_registry):
    return Agent(
        openai_client=mock_openai,
        model="gpt-4o",
        core_client=mock_core_client,
        context_manager=mock_context,
        briefing_builder=mock_briefing,
        tool_registry=mock_registry,
    )


class TestAgent:
    @pytest.mark.asyncio
    async def test_simple_text_response(self, agent, mock_openai, mock_context):
        """Agent returns text when LLM responds without tool calls."""
        mock_choice = MagicMock()
        mock_choice.message.content = "Hello! How can I help?"
        mock_choice.message.tool_calls = None
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_openai.chat.completions.create.return_value = mock_response

        reply = await agent.handle_message(user_id=1, text="Hello")
        assert reply == "Hello! How can I help?"
        mock_context.save_history.assert_called_once()

    @pytest.mark.asyncio
    async def test_history_saved_with_new_messages(self, agent, mock_openai, mock_context):
        """Agent appends user and assistant messages to history and saves."""
        mock_choice = MagicMock()
        mock_choice.message.content = "Sure!"
        mock_choice.message.tool_calls = None
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_openai.chat.completions.create.return_value = mock_response

        await agent.handle_message(user_id=1, text="Help me")
        saved = mock_context.save_history.call_args[1]["messages"]
        assert saved[-2]["role"] == "user"
        assert saved[-2]["content"] == "Help me"
        assert saved[-1]["role"] == "assistant"
        assert saved[-1]["content"] == "Sure!"

    @pytest.mark.asyncio
    async def test_tool_call_loop(self, agent, mock_openai, mock_context, mock_registry):
        """Agent executes tool calls and loops back to LLM."""
        # First call: LLM returns a tool call
        tool_call = MagicMock()
        tool_call.id = "call_123"
        tool_call.function.name = "search_memories"
        tool_call.function.arguments = '{"query": "groceries"}'
        first_choice = MagicMock()
        first_choice.message.content = None
        first_choice.message.tool_calls = [tool_call]
        first_response = MagicMock()
        first_response.choices = [first_choice]

        # Second call: LLM returns text
        second_choice = MagicMock()
        second_choice.message.content = "I found your grocery list."
        second_choice.message.tool_calls = None
        second_response = MagicMock()
        second_response.choices = [second_choice]

        mock_openai.chat.completions.create.side_effect = [first_response, second_response]
        mock_registry.get_all_schemas.return_value = [{"type": "function", "function": {"name": "search_memories"}}]
        mock_registry.execute.return_value = [{"content": "Buy milk"}]

        reply = await agent.handle_message(user_id=1, text="What groceries do I need?")
        assert reply == "I found your grocery list."
        assert mock_openai.chat.completions.create.call_count == 2
        mock_registry.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_tool_call_injects_owner_user_id(self, agent, mock_openai, mock_registry):
        """Agent injects owner_user_id into tool call kwargs."""
        tool_call = MagicMock()
        tool_call.id = "call_1"
        tool_call.function.name = "list_tasks"
        tool_call.function.arguments = '{"state": "NOT_DONE"}'
        first_choice = MagicMock()
        first_choice.message.content = None
        first_choice.message.tool_calls = [tool_call]
        first_resp = MagicMock()
        first_resp.choices = [first_choice]

        second_choice = MagicMock()
        second_choice.message.content = "Here are your tasks."
        second_choice.message.tool_calls = None
        second_resp = MagicMock()
        second_resp.choices = [second_choice]

        mock_openai.chat.completions.create.side_effect = [first_resp, second_resp]
        mock_registry.get_all_schemas.return_value = [{"type": "function", "function": {"name": "list_tasks"}}]
        mock_registry.execute.return_value = []

        await agent.handle_message(user_id=42, text="Show tasks")
        call_kwargs = mock_registry.execute.call_args
        # owner_user_id should be in the kwargs
        assert call_kwargs[1]["owner_user_id"] == 42

    @pytest.mark.asyncio
    async def test_summarization_triggered(self, agent, mock_openai, mock_context):
        """When history is too long, agent triggers summarization."""
        mock_context.needs_summarization.return_value = True
        mock_context.load_history.return_value = [
            {"role": "user", "content": "old message 1"},
            {"role": "assistant", "content": "old reply 1"},
            {"role": "user", "content": "old message 2"},
            {"role": "assistant", "content": "old reply 2"},
        ]

        # Summarization LLM call
        summary_choice = MagicMock()
        summary_choice.message.content = "User asked two questions."
        summary_response = MagicMock()
        summary_response.choices = [summary_choice]

        # Actual response
        reply_choice = MagicMock()
        reply_choice.message.content = "Here's my answer."
        reply_choice.message.tool_calls = None
        reply_response = MagicMock()
        reply_response.choices = [reply_choice]

        mock_openai.chat.completions.create.side_effect = [summary_response, reply_response]

        reply = await agent.handle_message(user_id=1, text="New question")
        assert reply == "Here's my answer."
        assert mock_openai.chat.completions.create.call_count == 2

    @pytest.mark.asyncio
    async def test_tool_error_handled(self, agent, mock_openai, mock_registry):
        """Tool execution errors are caught and sent back as error results."""
        tool_call = MagicMock()
        tool_call.id = "call_err"
        tool_call.function.name = "search_memories"
        tool_call.function.arguments = '{"query": "test"}'
        first_choice = MagicMock()
        first_choice.message.content = None
        first_choice.message.tool_calls = [tool_call]
        first_resp = MagicMock()
        first_resp.choices = [first_choice]

        second_choice = MagicMock()
        second_choice.message.content = "Sorry, I had trouble searching."
        second_choice.message.tool_calls = None
        second_resp = MagicMock()
        second_resp.choices = [second_choice]

        mock_openai.chat.completions.create.side_effect = [first_resp, second_resp]
        mock_registry.get_all_schemas.return_value = [{"type": "function"}]
        mock_registry.execute.side_effect = Exception("Connection failed")

        reply = await agent.handle_message(user_id=1, text="Search for something")
        assert reply == "Sorry, I had trouble searching."

    @pytest.mark.asyncio
    async def test_briefing_included_in_system_prompt(self, agent, mock_openai, mock_briefing):
        """Briefing text is included in the system message."""
        mock_briefing.build.return_value = "You have 3 tasks due today."

        choice = MagicMock()
        choice.message.content = "OK"
        choice.message.tool_calls = None
        resp = MagicMock()
        resp.choices = [choice]
        mock_openai.chat.completions.create.return_value = resp

        await agent.handle_message(user_id=1, text="Hi")
        call_args = mock_openai.chat.completions.create.call_args
        messages = call_args[1]["messages"]
        system_msg = messages[0]
        assert "3 tasks due today" in system_msg["content"]

    @pytest.mark.asyncio
    async def test_max_tool_iterations(self, agent, mock_openai, mock_registry):
        """Agent stops after MAX_TOOL_ITERATIONS to prevent infinite loops."""
        tool_call = MagicMock()
        tool_call.id = "call_loop"
        tool_call.function.name = "search_memories"
        tool_call.function.arguments = '{"query": "test"}'

        choice = MagicMock()
        choice.message.content = None
        choice.message.tool_calls = [tool_call]
        resp = MagicMock()
        resp.choices = [choice]

        # Always return tool calls, never text
        mock_openai.chat.completions.create.return_value = resp
        mock_registry.get_all_schemas.return_value = [{"type": "function"}]
        mock_registry.execute.return_value = {"data": "result"}

        reply = await agent.handle_message(user_id=1, text="Loop forever")
        assert "trouble processing" in reply
        assert mock_openai.chat.completions.create.call_count == MAX_TOOL_ITERATIONS
