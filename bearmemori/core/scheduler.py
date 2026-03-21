import asyncio
import logging
from datetime import timedelta

from bearmemori.events.bus import EventBus
from bearmemori.events.domain import ReminderDue
from bearmemori.storage.database import MemoryDatabase

logger = logging.getLogger(__name__)


class ReminderScheduler:
    def __init__(self, bus: EventBus, db: MemoryDatabase, poll_interval_seconds: int = 60) -> None:
        self._bus = bus
        self._db = db
        self._poll_interval = poll_interval_seconds

    async def check_reminders(self) -> None:
        due = self._db.get_due_reminders()
        for memory in due:
            source_chat_id = memory.metadata.get("source_chat_id", "")
            await self._bus.emit(
                ReminderDue(
                    memory_id=memory.id,
                    content=memory.content,
                    source_chat_id=source_chat_id,
                    remind_at_iso=memory.remind_at.isoformat(),
                )
            )

            if memory.recurring_minutes:
                memory.remind_at = memory.remind_at + timedelta(minutes=memory.recurring_minutes)
            else:
                memory.remind_at = None

            self._db.update(memory)
            logger.info("Fired reminder %s: %s", memory.id, memory.content[:80])

    async def run(self) -> None:
        logger.info("Reminder scheduler started (poll every %ds)", self._poll_interval)
        while True:
            try:
                await self.check_reminders()
            except Exception:
                logger.exception("Error checking reminders")
            await asyncio.sleep(self._poll_interval)
