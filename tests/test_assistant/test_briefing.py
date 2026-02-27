"""Tests for the briefing builder."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime

from assistant_svc.briefing import BriefingBuilder


@pytest.fixture
def mock_core_client():
    return AsyncMock()


@pytest.fixture
def mock_context_manager():
    ctx = MagicMock()
    ctx.count_tokens.side_effect = lambda text: len(text.split())
    ctx.load_session_summary = AsyncMock(return_value=None)
    return ctx


@pytest.fixture
def builder(mock_core_client, mock_context_manager):
    return BriefingBuilder(
        core_client=mock_core_client,
        context_manager=mock_context_manager,
        budget_tokens=5000,
    )


class TestBriefingBuilder:
    @pytest.mark.asyncio
    async def test_empty_briefing(self, builder, mock_core_client):
        """User with no data gets a minimal briefing."""
        mock_core_client.list_tasks.return_value = []
        mock_core_client.list_reminders.return_value = []

        text = await builder.build(user_id=1)
        assert isinstance(text, str)
        assert "No upcoming tasks" in text
        assert "No upcoming reminders" in text

    @pytest.mark.asyncio
    async def test_briefing_includes_tasks(self, builder, mock_core_client):
        """Briefing includes upcoming tasks."""
        task = MagicMock()
        task.id = "t1"
        task.description = "Buy groceries"
        task.due_at = datetime(2026, 3, 1, 10, 0)
        mock_core_client.list_tasks.return_value = [task]
        mock_core_client.list_reminders.return_value = []

        text = await builder.build(user_id=1)
        assert "Buy groceries" in text
        assert "t1" in text

    @pytest.mark.asyncio
    async def test_briefing_includes_reminders(self, builder, mock_core_client):
        """Briefing includes upcoming reminders."""
        reminder = MagicMock()
        reminder.id = "r1"
        reminder.text = "Call dentist"
        reminder.fire_at = datetime(2026, 3, 1, 9, 0)
        mock_core_client.list_tasks.return_value = []
        mock_core_client.list_reminders.return_value = [reminder]

        text = await builder.build(user_id=1)
        assert "Call dentist" in text
        assert "r1" in text

    @pytest.mark.asyncio
    async def test_briefing_includes_session_summary(
        self, builder, mock_core_client, mock_context_manager
    ):
        """Briefing includes previous session summary when available."""
        mock_core_client.list_tasks.return_value = []
        mock_core_client.list_reminders.return_value = []
        mock_context_manager.load_session_summary.return_value = "User discussed vacation plans."

        text = await builder.build(user_id=1)
        assert "vacation plans" in text
        assert "Previous Conversation" in text

    @pytest.mark.asyncio
    async def test_briefing_no_session_summary(
        self, builder, mock_core_client, mock_context_manager
    ):
        """Briefing omits session section when no summary exists."""
        mock_core_client.list_tasks.return_value = []
        mock_core_client.list_reminders.return_value = []
        mock_context_manager.load_session_summary.return_value = None

        text = await builder.build(user_id=1)
        assert "Previous Conversation" not in text

    @pytest.mark.asyncio
    async def test_briefing_handles_api_errors(self, builder, mock_core_client):
        """Briefing gracefully handles Core API errors."""
        mock_core_client.list_tasks.side_effect = Exception("Connection failed")
        mock_core_client.list_reminders.side_effect = Exception("Connection failed")

        text = await builder.build(user_id=1)
        assert isinstance(text, str)
        # Should still return something, just without data
        assert "No upcoming tasks" in text

    @pytest.mark.asyncio
    async def test_briefing_caps_tasks_at_20(self, builder, mock_core_client):
        """Briefing caps tasks at 20 items."""
        tasks = []
        for i in range(25):
            t = MagicMock()
            t.id = f"t{i}"
            t.description = f"Task {i}"
            t.due_at = None
            tasks.append(t)
        mock_core_client.list_tasks.return_value = tasks
        mock_core_client.list_reminders.return_value = []

        text = await builder.build(user_id=1)
        assert "Task 19" in text
        assert "Task 20" not in text

    @pytest.mark.asyncio
    async def test_briefing_trims_to_budget(self, mock_core_client, mock_context_manager):
        """Briefing is trimmed when it exceeds the token budget."""
        # Set a very small budget
        builder = BriefingBuilder(
            core_client=mock_core_client,
            context_manager=mock_context_manager,
            budget_tokens=10,  # very small
        )
        tasks = []
        for i in range(5):
            t = MagicMock()
            t.id = f"t{i}"
            t.description = f"This is a task with a longer description number {i}"
            t.due_at = None
            tasks.append(t)
        mock_core_client.list_tasks.return_value = tasks
        mock_core_client.list_reminders.return_value = []

        text = await builder.build(user_id=1)
        word_count = len(text.split())
        assert word_count <= 10
