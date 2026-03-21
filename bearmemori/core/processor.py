import logging
import struct
import uuid

from bearmemori.core.models import QueueItem
from bearmemori.events.bus import EventBus
from bearmemori.events.domain import FollowUpRequired, MemoryStored
from bearmemori.llm.client import LLMClient
from bearmemori.storage.database import MemoryDatabase
from bearmemori.storage.models import Memory

logger = logging.getLogger(__name__)


class Processor:
    def __init__(
        self,
        bus: EventBus,
        llm: LLMClient,
        db: MemoryDatabase,
        embedding_model: str,
    ) -> None:
        self._bus = bus
        self._llm = llm
        self._db = db
        self._embedding_model = embedding_model

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
        embedding = await self._llm.get_embedding(extraction.content, self._embedding_model)
        embedding_bytes = struct.pack(f"{len(embedding)}f", *embedding)

        memory = Memory(
            id=str(uuid.uuid4()),
            content=extraction.content,
            raw_input=text,
            memory_type=extraction.memory_type,
            tags=extraction.tags,
            embedding=embedding_bytes,
            source="telegram",
        )
        self._db.create(memory)

        await self._bus.emit(
            MemoryStored(
                memory_id=memory.id,
                content=memory.content,
                memory_type=memory.memory_type,
                source_chat_id=item.source_chat_id,
            )
        )
        logger.info("Stored memory %s: %s", memory.id, memory.content[:80])
