import logging
import uuid
from pathlib import Path

from bearmemori.events.bus import EventBus
from bearmemori.events.domain import MemoryConfirmed, MemoryDiscarded, MemoryStored
from bearmemori.storage.database import MemoryDatabase
from bearmemori.storage.models import MemoryRecord
from bearmemori.storage.pending_store import PendingStore
from bearmemori.storage.vector_store import VectorStore

logger = logging.getLogger(__name__)


class ConfirmHandler:
    def __init__(
        self,
        bus: EventBus,
        pending_store: PendingStore,
        db: MemoryDatabase,
        vector_store: VectorStore,
    ) -> None:
        self._bus = bus
        self._pending_store = pending_store
        self._db = db
        self._vector_store = vector_store

    async def handle_confirmed(self, event: MemoryConfirmed) -> None:
        pending = self._pending_store.get(event.pending_id)
        if pending is None:
            logger.warning("Pending memory %s not found (expired?)", event.pending_id)
            return

        record_id = f"mem_{uuid.uuid4().hex[:12]}"
        record = MemoryRecord.from_draft(pending.draft, record_id)
        record.needs_review = event.needs_review
        self._db.create(record)
        self._vector_store.add(record)
        self._pending_store.remove(event.pending_id)

        await self._bus.emit(
            MemoryStored(
                memory_id=record.id,
                content=record.content,
                category=record.category.value,
                source_chat_id=event.source_chat_id,
            )
        )
        logger.info(
            "Confirmed and stored memory %s (needs_review=%s)", record.id, record.needs_review
        )

    async def handle_discarded(self, event: MemoryDiscarded) -> None:
        pending = self._pending_store.get(event.pending_id)
        if pending is None:
            return

        if pending.image_path:
            path = Path(pending.image_path)
            if path.exists():
                path.unlink()
                logger.info("Deleted image %s", pending.image_path)

        self._pending_store.remove(event.pending_id)
        logger.info("Discarded pending memory %s", event.pending_id)
