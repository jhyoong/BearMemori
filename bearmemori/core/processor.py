import logging
import uuid
from datetime import UTC, datetime

from bearmemori.core.models import QueueItem
from bearmemori.events.bus import EventBus
from bearmemori.events.domain import FollowUpRequired, MemoryStored
from bearmemori.llm.client import LLMClient
from bearmemori.storage.database import MemoryDatabase
from bearmemori.storage.models import EventFields, MemoryCategory, MemoryRecord, MemorySource

logger = logging.getLogger(__name__)


class Processor:
    def __init__(
        self,
        bus: EventBus,
        llm: LLMClient,
        db: MemoryDatabase,
    ) -> None:
        self._bus = bus
        self._llm = llm
        self._db = db

    async def process_item(self, item: QueueItem) -> None:
        text = item.content if isinstance(item.content, str) else str(item.content)

        classification = await self._llm.classify_input(text)

        if classification.action == "followup":
            question = await self._llm.generate_followup(text, item.context)
            context = item.context or {"messages": []}
            context["messages"].append({"role": "user", "content": text})
            context["messages"].append({"role": "assistant", "content": question})

            await self._bus.emit(
                FollowUpRequired(
                    question=question,
                    source_chat_id=item.source_chat_id,
                    context=context,
                )
            )
            return

        extraction = await self._llm.extract_memory(text, item.context)

        event_fields = None
        if extraction.event_fields:
            event_fields = EventFields(**extraction.event_fields)

        record = MemoryRecord(
            id=f"mem_{uuid.uuid4().hex[:12]}",
            category=MemoryCategory(extraction.category),
            title=extraction.title,
            content=extraction.content,
            created_at=datetime.now(UTC),
            raw_input=text,
            event_fields=event_fields,
            tags=extraction.tags,
            source=MemorySource(platform="telegram", chat_id=item.source_chat_id),
        )
        self._db.create(record)

        await self._bus.emit(
            MemoryStored(
                memory_id=record.id,
                content=record.content,
                category=record.category.value,
                source_chat_id=item.source_chat_id,
            )
        )
        logger.info("Stored memory %s: %s", record.id, record.content[:80])
