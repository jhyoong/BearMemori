import asyncio
import heapq
import logging

from bearmemori.core.models import QueueItem
from bearmemori.events.bus import EventBus
from bearmemori.events.domain import InputQueued, InputReceived

logger = logging.getLogger(__name__)


class QueueManager:
    def __init__(self, bus: EventBus, max_size: int = 1000) -> None:
        self._bus = bus
        self._max_size = max_size
        self._heap: list[QueueItem] = []
        self._item_available = asyncio.Event()

    async def enqueue(self, item: QueueItem) -> bool:
        if len(self._heap) >= self._max_size:
            logger.warning("Queue full, rejecting item from %s", item.source_chat_id)
            return False
        heapq.heappush(self._heap, item)
        self._item_available.set()
        return True

    async def get_next(self) -> QueueItem:
        while not self._heap:
            self._item_available.clear()
            await self._item_available.wait()
        return heapq.heappop(self._heap)

    async def handle_input(self, event: InputReceived) -> None:
        item = QueueItem(
            priority=0 if event.context else 10,
            input_type=event.input_type,
            content=event.content,
            context=event.context,
            source_chat_id=event.source_chat_id,
        )
        accepted = await self.enqueue(item)
        if accepted:
            await self._bus.emit(
                InputQueued(
                    priority=item.priority,
                    input_type=item.input_type,
                    source_chat_id=item.source_chat_id,
                )
            )
