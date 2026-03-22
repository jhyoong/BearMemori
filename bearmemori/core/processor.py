import logging

from bearmemori.core.models import QueueItem
from bearmemori.events.bus import EventBus
from bearmemori.events.domain import FollowUpRequired, MemoryPending
from bearmemori.llm.client import LLMClient
from bearmemori.storage.models import EventFields, MemoryCategory, MemoryDraft, MemorySource
from bearmemori.storage.pending_store import PendingStore

logger = logging.getLogger(__name__)


class Processor:
    def __init__(
        self,
        bus: EventBus,
        llm: LLMClient,
        pending_store: PendingStore,
    ) -> None:
        self._bus = bus
        self._llm = llm
        self._pending_store = pending_store

    async def process_item(self, item: QueueItem) -> None:
        # Handle edit corrections for a pending memory
        if item.context and "edit_pending_id" in item.context:
            await self._process_edit(item)
            return

        if item.input_type == "image":
            await self._process_image(item)
            return

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
        await self._create_pending(extraction, text, item.source_chat_id)

    async def _process_edit(self, item: QueueItem) -> None:
        pending_id = item.context["edit_pending_id"]
        pending = self._pending_store.get(pending_id)
        if pending is None:
            logger.warning("Edit target %s not found (expired?)", pending_id)
            return

        text = item.content if isinstance(item.content, str) else str(item.content)
        original_content = pending.draft.content

        context = {
            "messages": [
                {"role": "user", "content": original_content},
                {"role": "user", "content": text},
            ]
        }
        extraction = await self._llm.extract_memory(text, context)

        self._pending_store.remove(pending_id)
        await self._create_pending(
            extraction,
            text,
            item.source_chat_id,
            image_path=pending.image_path,
        )

    async def _process_image(self, item: QueueItem) -> None:
        image_bytes = item.content.get("image_bytes", b"")
        caption = item.content.get("caption", "")
        image_path = item.content.get("image_path")

        if caption:
            classification = await self._llm.classify_input(caption)
            if classification.action == "followup":
                question = await self._llm.generate_followup(caption, item.context)
                context = item.context or {"messages": []}
                context["messages"].append({"role": "user", "content": caption})
                context["messages"].append({"role": "assistant", "content": question})
                await self._bus.emit(
                    FollowUpRequired(
                        question=question,
                        source_chat_id=item.source_chat_id,
                        context=context,
                    )
                )
                return
            extraction = await self._llm.extract_memory(caption, item.context)
        else:
            extraction = await self._llm.describe_image(image_bytes, caption=caption)

        await self._create_pending(
            extraction,
            caption or "[image]",
            item.source_chat_id,
            image_path=image_path,
        )

    async def _create_pending(
        self,
        extraction,
        raw_input: str,
        chat_id: str,
        image_path: str | None = None,
    ) -> None:
        event_fields = None
        if extraction.event_fields:
            event_fields = EventFields(**extraction.event_fields)

        draft = MemoryDraft(
            category=MemoryCategory(extraction.category),
            title=extraction.title,
            content=extraction.content,
            event_fields=event_fields,
            tags=extraction.tags,
            source=MemorySource(platform="telegram", chat_id=chat_id),
        )

        pending_id = self._pending_store.add(
            draft,
            chat_id=chat_id,
            image_path=image_path,
        )

        preview_data = {
            "title": extraction.title,
            "category": extraction.category,
            "content": extraction.content,
            "tags": extraction.tags,
            "event_fields": extraction.event_fields,
        }

        await self._bus.emit(
            MemoryPending(
                pending_id=pending_id,
                preview_data=preview_data,
                source_chat_id=chat_id,
            )
        )
        logger.info("Pending memory %s: %s", pending_id, extraction.content[:80])
