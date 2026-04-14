import logging

from bearmemori.events.bus import EventBus
from bearmemori.events.domain import FollowUpRequired, InputReceived, SendMessage

logger = logging.getLogger(__name__)


class FollowUpManager:
    def __init__(self, bus: EventBus) -> None:
        self._bus = bus
        self._active: dict[str, dict] = {}  # chat_id -> context

    async def handle_followup_required(self, event: FollowUpRequired) -> None:
        self._active[event.source_chat_id] = event.context
        await self._bus.emit(SendMessage(chat_id=event.source_chat_id, text=event.question))
        logger.info("Follow-up requested for chat %s", event.source_chat_id)

    def check_followup(self, event: InputReceived) -> InputReceived | None:
        context = self._active.pop(event.source_chat_id, None)
        if context is None:
            return None
        return InputReceived(
            input_type=event.input_type,
            content=event.content,
            source_chat_id=event.source_chat_id,
            context=context,
        )
