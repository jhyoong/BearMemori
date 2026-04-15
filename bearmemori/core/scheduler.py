import asyncio
import logging
from datetime import UTC, datetime, timedelta

from bearmemori.core.recurrence import expand_occurrences
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
            if record.event_fields and record.event_fields.recurrence:
                await self._handle_recurring(record)
            else:
                await self._handle_single(record)

    async def _handle_single(self, record) -> None:
        source_chat_id = self._get_chat_id(record)
        remind_at_iso = record.event_fields.datetime if record.event_fields else ""
        await self._bus.emit(
            ReminderDue(
                memory_id=record.id,
                content=record.content,
                source_chat_id=source_chat_id,
                remind_at_iso=remind_at_iso,
            )
        )
        if record.event_fields:
            record.event_fields = EventFields(
                datetime=record.event_fields.datetime,
                status="done",
                recurrence=record.event_fields.recurrence,
            )
        self._db.update(record)
        logger.info("Fired single reminder %s: %s", record.id, record.content[:80])

    async def _handle_recurring(self, record) -> None:
        now = datetime.now(UTC)
        # Check the last 25 hours to find any occurrence that just became due
        window_start = now - timedelta(hours=25)
        occurrences = expand_occurrences(record, window_start, now)

        fired = False
        completed = list(record.metadata.get("completed_occurrences", []))
        source_chat_id = self._get_chat_id(record)
        for occ in occurrences:
            if occ.status == "done":
                continue
            await self._bus.emit(
                ReminderDue(
                    memory_id=record.id,
                    content=record.content,
                    source_chat_id=source_chat_id,
                    remind_at_iso=occ.occurrence_dt.isoformat(),
                )
            )
            occ_date_str = occ.occurrence_dt.date().isoformat()
            if occ_date_str not in completed:
                completed.append(occ_date_str)
            fired = True
            logger.info("Fired recurring reminder %s occurrence %s", record.id, occ_date_str)

        if fired:
            record.metadata["completed_occurrences"] = completed
            self._db.update(record)
        else:
            logger.debug("Recurring reminder %s has no unfired due occurrences", record.id)

    def _get_chat_id(self, record) -> str:
        if record.source:
            return record.source.chat_id
        return ""

    async def run(self) -> None:
        logger.info("Reminder scheduler started (poll every %ds)", self._poll_interval)
        while True:
            try:
                await self.check_reminders()
            except Exception:
                logger.exception("Error checking reminders")
            await asyncio.sleep(self._poll_interval)
