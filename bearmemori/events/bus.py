import asyncio
import logging
from collections import defaultdict
from collections.abc import Callable

from bearmemori.events.types import Event

logger = logging.getLogger(__name__)


class EventBus:
    def __init__(self) -> None:
        self._handlers: dict[type[Event], list[Callable]] = defaultdict(list)

    def on(self, event_type: type[Event], handler: Callable) -> None:
        self._handlers[event_type].append(handler)

    async def emit(self, event: Event) -> None:
        handlers = self._handlers.get(type(event), [])
        tasks = []
        for handler in handlers:
            result = handler(event)
            if asyncio.iscoroutine(result):
                tasks.append(result)
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            errors = [r for r in results if isinstance(r, Exception)]
            for err in errors:
                logger.error("Event handler error: %s", err)
            if errors:
                raise errors[0]
