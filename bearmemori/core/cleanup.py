import asyncio
import logging
from pathlib import Path

from bearmemori.events.bus import EventBus
from bearmemori.events.domain import MemoryDiscarded, SendMessage
from bearmemori.storage.pending_store import PendingStore

logger = logging.getLogger(__name__)


class PendingCleanupTask:
    def __init__(
        self,
        bus: EventBus,
        pending_store: PendingStore,
        interval_seconds: int = 300,
    ) -> None:
        self._bus = bus
        self._pending_store = pending_store
        self._interval = interval_seconds

    async def run_once(self) -> int:
        expired = self._pending_store.cleanup_with_details()
        for item in expired:
            if item.image_path:
                path = Path(item.image_path)
                if path.exists():
                    path.unlink()
            await self._bus.emit(
                MemoryDiscarded(
                    pending_id=item.pending_id, source_chat_id=item.chat_id
                )
            )
            await self._bus.emit(
                SendMessage(
                    chat_id=item.chat_id,
                    text="Memory discarded (timed out).",
                )
            )
        if expired:
            logger.info(
                "Cleaned up %d expired pending memories", len(expired)
            )
        return len(expired)

    async def run(self) -> None:
        logger.info(
            "Pending cleanup task started (interval=%ds)", self._interval
        )
        while True:
            await asyncio.sleep(self._interval)
            await self.run_once()
