import asyncio
import logging

from bearmemori.events.bus import EventBus
from bearmemori.events.domain import ReminderDue
from bearmemori.storage.database import MemoryDatabase
from bearmemori.storage.models import EventFields

logger = logging.getLogger(__name__)


class ReminderScheduler:
    def __init__(self, bus: EventBus, db: MemoryDatabase, poll_interval_seconds: int = 60) -> None:
        self._bus = bus
        self._db = db
        self._poll_interval = poll_interval_seconds

    async def check_reminders(self) -> None:
        due = self._db.get_due_events()
        for record in due:
            source_chat_id = ""
            if record.source:
                source_chat_id = record.source.chat_id
            elif record.metadata.get("source_chat_id"):
                source_chat_id = record.metadata["source_chat_id"]

            remind_at_iso = record.event_fields.datetime if record.event_fields else ""

            await self._bus.emit(
                ReminderDue(
                    memory_id=record.id,
                    content=record.content,
                    source_chat_id=source_chat_id,
                    remind_at_iso=remind_at_iso,
                )
            )

            # Mark as done
            if record.event_fields:
                record.event_fields = EventFields(
                    datetime=record.event_fields.datetime,
                    status="done",
                    recurrence=record.event_fields.recurrence,
                )
            self._db.update(record)
            logger.info("Fired reminder %s: %s", record.id, record.content[:80])

    async def run(self) -> None:
        logger.info("Reminder scheduler started (poll every %ds)", self._poll_interval)
        while True:
            try:
                await self.check_reminders()
            except Exception:
                logger.exception("Error checking reminders")
            await asyncio.sleep(self._poll_interval)
