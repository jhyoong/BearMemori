"""Tests for the daily digest scheduler."""

import pytest
import pytest_asyncio
import fakeredis.aioredis
from unittest.mock import AsyncMock, MagicMock

from assistant_svc.digest import DigestScheduler


@pytest_asyncio.fixture
async def redis():
    r = fakeredis.aioredis.FakeRedis()
    yield r
    await r.aclose()


@pytest.fixture
def mock_briefing():
    b = AsyncMock()
    b.build.return_value = "You have 2 tasks due today."
    return b


@pytest.fixture
def mock_interface():
    return AsyncMock()


@pytest.fixture
def mock_core_client():
    settings = MagicMock()
    settings.timezone = "UTC"
    client = AsyncMock()
    client.get_settings.return_value = settings
    return client


@pytest.fixture
def scheduler(redis, mock_briefing, mock_interface, mock_core_client):
    return DigestScheduler(
        redis=redis,
        briefing_builder=mock_briefing,
        interface=mock_interface,
        core_client=mock_core_client,
        user_ids=[1, 2],
        default_hour=8,
    )


class TestDigestScheduler:
    @pytest.mark.asyncio
    async def test_send_digest(self, scheduler, mock_interface):
        """send_digest sends briefing and marks as sent."""
        await scheduler.send_digest_for_user(user_id=1)
        mock_interface.send_message.assert_called_once()
        call_kwargs = mock_interface.send_message.call_args
        # Verify user_id is passed
        assert call_kwargs[1]["user_id"] == 1 or call_kwargs[0][0] == 1

    @pytest.mark.asyncio
    async def test_digest_not_sent_twice(self, scheduler, mock_interface):
        """Digest is not sent twice on the same day."""
        await scheduler.send_digest_for_user(user_id=1)
        await scheduler.send_digest_for_user(user_id=1)
        assert mock_interface.send_message.call_count == 1

    @pytest.mark.asyncio
    async def test_digest_skips_empty_briefing(self, scheduler, mock_briefing, mock_interface):
        """Digest is skipped if briefing is empty."""
        mock_briefing.build.return_value = ""
        await scheduler.send_digest_for_user(user_id=1)
        mock_interface.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_digest_skips_whitespace_briefing(
        self, scheduler, mock_briefing, mock_interface
    ):
        """Digest is skipped if briefing is only whitespace."""
        mock_briefing.build.return_value = "   \n\n  "
        await scheduler.send_digest_for_user(user_id=1)
        mock_interface.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_different_users_independent(self, scheduler, mock_interface):
        """Different users get independent digests."""
        await scheduler.send_digest_for_user(user_id=1)
        await scheduler.send_digest_for_user(user_id=2)
        assert mock_interface.send_message.call_count == 2

    def test_stop(self, scheduler):
        """stop() sets running flag to False."""
        scheduler._running = True
        scheduler.stop()
        assert scheduler._running is False
