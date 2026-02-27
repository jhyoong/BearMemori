"""Shared test fixtures for BearMemori telegram service tests."""

import os
import sys
from unittest.mock import AsyncMock, Mock

import pytest
from telegram.ext import Application

# Add telegram directory to path so tg_gateway module is importable
telegram_dir = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "telegram",
)
if telegram_dir not in sys.path:
    sys.path.insert(0, telegram_dir)

import pytest_asyncio


@pytest_asyncio.fixture
async def mock_application():
    """Create a mock Application instance with mocked bot.set_my_commands."""
    application = Mock(spec=Application)
    application.bot = Mock()
    application.bot.set_my_commands = AsyncMock()
    application.bot_data = {}
    application.create_task = AsyncMock()
    yield application
