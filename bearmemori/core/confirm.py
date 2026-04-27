import logging
import uuid
from pathlib import Path

from bearmemori.events.bus import EventBus
from bearmemori.events.domain import MemoryConfirmed, MemoryDiscarded, MemoryStored
from bearmemori.storage.database import MemoryDatabase
from bearmemori.storage.models import Actor, MemoryRecord, MemorySource
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
        image_storage_dir: str = "",
    ) -> None:
        self._bus = bus
        self._pending_store = pending_store
        self._db = db
        self._vector_store = vector_store
        self._image_storage_dir = image_storage_dir

    async def handle_confirmed(self, event: MemoryConfirmed) -> None:
        pending = self._pending_store.get(event.pending_id)
        if pending is None:
            logger.warning("Pending memory %s not found (expired?)", event.pending_id)
            return

        record_id = f"mem_{uuid.uuid4().hex[:12]}"
        record = MemoryRecord.from_draft(pending.draft, record_id)
        record.needs_review = event.needs_review
        if event.source_chat_id:
            record.source = MemorySource(
                platform="telegram",
                chat_id=event.source_chat_id,
            )
        # Save image to disk if present
        if pending.image_bytes and self._image_storage_dir:
            image_dir = Path(self._image_storage_dir)
            image_dir.mkdir(parents=True, exist_ok=True)
            image_file = image_dir / f"{record_id}.jpg"
            image_file.write_bytes(pending.image_bytes)
            record.image_path = f"{record_id}.jpg"
            logger.info("Saved image to %s", image_file)
        self._db.create(record, actor=Actor.TELEGRAM)
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
        self._pending_store.remove(event.pending_id)
        logger.info("Discarded pending memory %s", event.pending_id)
