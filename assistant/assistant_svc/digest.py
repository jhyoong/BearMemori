"""Daily digest scheduler for morning briefings."""

import asyncio
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class DigestScheduler:
    """Sends daily morning briefings to users."""

    def __init__(
        self,
        redis,
        briefing_builder,
        interface,
        core_client,
        user_ids: list[int],
        default_hour: int = 8,
    ):
        self._redis = redis
        self._briefing = briefing_builder
        self._interface = interface
        self._core_client = core_client
        self._user_ids = user_ids
        self._default_hour = default_hour
        self._running = False

    async def send_digest_for_user(self, user_id: int) -> None:
        """Send a digest to a single user if not already sent today."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        key = f"assistant:digest_sent:{user_id}:{today}"

        # Check if already sent
        if await self._redis.get(key):
            return

        # Build the briefing
        briefing = await self._briefing.build(user_id)
        if not briefing or not briefing.strip():
            return

        # Send via interface
        await self._interface.send_message(
            user_id=user_id,
            text=f"Good morning! Here's your daily briefing:\n\n{briefing}",
        )

        # Mark as sent (48h TTL to handle timezone edge cases)
        await self._redis.set(key, "1", ex=172800)

    async def check_and_send_all(self) -> None:
        """Check all users and send digests if it's the right time."""
        for user_id in self._user_ids:
            try:
                # Get user's timezone
                settings = await self._core_client.get_settings(user_id)
                tz_name = settings.timezone if settings else "UTC"

                # Check if it's the configured hour in the user's timezone
                from zoneinfo import ZoneInfo

                user_tz = ZoneInfo(tz_name)
                now = datetime.now(user_tz)
                if now.hour == self._default_hour:
                    await self.send_digest_for_user(user_id)
            except Exception:
                logger.exception("Failed to send digest for user %d", user_id)

    async def run(self) -> None:
        """Run the digest scheduler loop, checking every 15 minutes."""
        self._running = True
        logger.info("Digest scheduler started")
        while self._running:
            try:
                await self.check_and_send_all()
            except Exception:
                logger.exception("Digest scheduler error")
            await asyncio.sleep(900)  # 15 minutes

    def stop(self) -> None:
        """Stop the scheduler loop."""
        self._running = False
