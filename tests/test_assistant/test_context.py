"""Tests for chat history context management."""

import json
import pytest
import pytest_asyncio
import fakeredis.aioredis

from assistant_svc.context import ContextManager, SYSTEM_PROMPT_ESTIMATE_TOKENS


@pytest_asyncio.fixture
async def redis():
    r = fakeredis.aioredis.FakeRedis()
    yield r
    await r.aclose()


@pytest_asyncio.fixture
async def ctx(redis):
    return ContextManager(
        redis=redis,
        context_window_tokens=1000,
        briefing_budget_tokens=200,
        response_reserve_tokens=100,
        session_timeout_seconds=1800,
    )


class TestContextManager:
    @pytest.mark.asyncio
    async def test_empty_history(self, ctx):
        """New user has empty chat history."""
        messages = await ctx.load_history(user_id=1)
        assert messages == []

    @pytest.mark.asyncio
    async def test_save_and_load(self, ctx):
        """Messages are persisted to Redis and can be loaded back."""
        msgs = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
        ]
        await ctx.save_history(user_id=1, messages=msgs)
        loaded = await ctx.load_history(user_id=1)
        assert loaded == msgs

    def test_token_count(self, ctx):
        """count_tokens returns a positive integer for non-empty text."""
        count = ctx.count_tokens("Hello, how are you?")
        assert isinstance(count, int)
        assert count > 0

    def test_count_messages_tokens(self, ctx):
        """count_messages_tokens sums tokens across all message contents."""
        msgs = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there, how can I help?"},
        ]
        total = ctx.count_messages_tokens(msgs)
        assert total > 0

    def test_count_messages_tokens_with_dict_content(self, ctx):
        """count_messages_tokens handles dict content (tool results)."""
        msgs = [{"role": "tool", "content": {"result": "some data"}}]
        total = ctx.count_messages_tokens(msgs)
        assert total > 0

    def test_chat_budget_calculation(self, ctx):
        """Chat budget = window - briefing - response reserve - system prompt estimate."""
        budget = ctx.chat_budget_tokens
        expected = 1000 - 200 - 100 - SYSTEM_PROMPT_ESTIMATE_TOKENS
        assert budget == expected

    def test_needs_summarization_false(self, ctx):
        """Short history does not trigger summarization."""
        msgs = [{"role": "user", "content": "Hi"}]
        assert ctx.needs_summarization(msgs) is False

    def test_needs_summarization_true(self, ctx):
        """Long history triggers summarization (over 70% of budget)."""
        # Create messages that exceed 70% of the budget
        # Budget is 1000 - 200 - 100 - 300 = 400. 70% = 280 tokens.
        # Each word is roughly 1 token, so ~300 words should exceed.
        long_msg = " ".join(["word"] * 300)
        msgs = [{"role": "user", "content": long_msg}]
        assert ctx.needs_summarization(msgs) is True

    @pytest.mark.asyncio
    async def test_save_session_summary(self, ctx):
        """Session summary is saved to Redis and can be loaded."""
        await ctx.save_session_summary(user_id=1, summary="We discussed groceries.")
        summary = await ctx.load_session_summary(user_id=1)
        assert summary == "We discussed groceries."

    @pytest.mark.asyncio
    async def test_load_session_summary_empty(self, ctx):
        """Loading summary for user with no summary returns None."""
        summary = await ctx.load_session_summary(user_id=999)
        assert summary is None

    @pytest.mark.asyncio
    async def test_separate_users(self, ctx):
        """Different users have separate histories."""
        await ctx.save_history(user_id=1, messages=[{"role": "user", "content": "User 1"}])
        await ctx.save_history(user_id=2, messages=[{"role": "user", "content": "User 2"}])
        h1 = await ctx.load_history(user_id=1)
        h2 = await ctx.load_history(user_id=2)
        assert h1[0]["content"] == "User 1"
        assert h2[0]["content"] == "User 2"
