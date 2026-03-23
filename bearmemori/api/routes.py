import logging
import uuid
from datetime import UTC, datetime

from fastapi import FastAPI, HTTPException

from bearmemori.api.schemas import (
    BulkDeleteRequest,
    BulkUpdateRequest,
    ConfirmRequest,
    CreateMemoryRequest,
    SearchRequest,
    TriageRequest,
    UpdateMemoryRequest,
)
from bearmemori.core.triage import run_triage
from bearmemori.storage.database import MemoryDatabase
from bearmemori.storage.models import (
    MemoryCategory,
    MemoryDraft,
    MemoryRecord,
)
from bearmemori.storage.pending_store import PendingStore
from bearmemori.storage.vector_store import VectorStore

logger = logging.getLogger(__name__)


def create_app(
    db: MemoryDatabase,
    vector_store: VectorStore,
    pending_store: PendingStore,
    llm_base_url: str = "",
    llm_api_key: str = "",
    llm_model: str = "",
    llm_max_tokens: int = 4096,
) -> FastAPI:
    app = FastAPI(title="BearMemori", version="0.3.3")

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.post("/memory/triage")
    async def triage_conversation(request: TriageRequest):
        result = await run_triage(
            request.conversation,
            llm_base_url=llm_base_url,
            llm_api_key=llm_api_key,
            llm_model=llm_model,
            llm_max_tokens=llm_max_tokens,
            memory_hint=request.memory_hint,
        )
        if not result.should_save or result.draft is None:
            return {"should_save": False}

        pending_id = pending_store.add(result.draft)
        logger.info("Triage proposed memory: %s", pending_id)
        return {
            "should_save": True,
            "pending_id": pending_id,
            "draft": result.draft.model_dump(mode="json"),
        }

    @app.post("/memory/pending")
    def create_pending(draft: MemoryDraft):
        pending_id = pending_store.add(draft)
        logger.info("Created pending memory: %s", pending_id)
        return {"pending_id": pending_id}

    @app.delete("/memory/pending/{pending_id}")
    def dismiss_pending(pending_id: str):
        removed = pending_store.remove(pending_id)
        if not removed:
            raise HTTPException(status_code=404, detail="Pending memory not found")
        logger.info("Dismissed pending memory: %s", pending_id)
        return {"status": "dismissed"}

    @app.post("/memory/confirm")
    def confirm_pending(request: ConfirmRequest):
        pending = pending_store.get(request.pending_id)
        if pending is None:
            raise HTTPException(status_code=404, detail="Pending memory not found or expired")

        record_id = f"mem_{uuid.uuid4().hex[:12]}"
        record = MemoryRecord.from_draft(pending.draft, record_id=record_id)

        db.create(record)
        vector_store.add(record)
        pending_store.remove(request.pending_id)

        logger.info("Confirmed memory: %s -> %s", request.pending_id, record_id)
        return {"record_id": record_id, "status": "confirmed"}

    @app.post("/memory/search")
    def search_memories(request: SearchRequest):
        results = vector_store.search(
            query=request.query,
            top_k=request.top_k,
            category=request.category,
        )
        return {"results": results}

    @app.get("/memory/retrieve")
    def retrieve_context(query_context: str, top_k: int = 5, event_days: int = 7):
        semantic_results = vector_store.search(query=query_context, top_k=top_k)
        upcoming_events = db.get_upcoming_events(days=event_days)

        lines = []
        if semantic_results:
            lines.append("## Relevant Memories")
            for r in semantic_results:
                lines.append(f"- {r['document']}")

        if upcoming_events:
            lines.append("\n## Upcoming Events")
            for e in upcoming_events:
                dt = e.event_fields.datetime if e.event_fields else "unknown"
                lines.append(f"- [{dt}] {e.title}: {e.content}")

        context_block = "\n".join(lines) if lines else ""

        items = semantic_results + [
            {
                "id": e.id,
                "document": f"{e.title}: {e.content}",
                "metadata": {"category": e.category.value},
            }
            for e in upcoming_events
        ]

        return {"context_block": context_block, "items": items}

    @app.get("/memory/events/upcoming")
    def get_upcoming_events(days: int = 7):
        events = db.get_upcoming_events(days=days)
        return {"events": [e.model_dump(mode="json") for e in events]}

    @app.get("/memory/list")
    def list_memories(category: str | None = None, needs_review: bool | None = None):
        if category is not None:
            try:
                cat = MemoryCategory(category)
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid category: {category}",
                )
            records = db.list_by_category(cat)
        else:
            records = db.list_all()
        if needs_review is not None:
            records = [r for r in records if r.needs_review == needs_review]
        return {"memories": [r.model_dump(mode="json") for r in records]}

    @app.get("/memory/{record_id}")
    def get_memory(record_id: str):
        record = db.get(record_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Memory not found")
        return record.model_dump(mode="json")

    @app.delete("/memory/{record_id}")
    def delete_memory(record_id: str):
        deleted = db.delete(record_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Memory not found")
        vector_store.delete(record_id)
        logger.info("Deleted memory: %s", record_id)
        return {"status": "deleted"}

    @app.put("/memory/{record_id}")
    def update_memory(record_id: str, request: UpdateMemoryRequest):
        record = db.get(record_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Memory not found")

        update_data = request.model_dump(exclude_unset=True)
        if not update_data:
            raise HTTPException(status_code=400, detail="No updates provided")

        # Handle category as string to MemoryCategory enum
        if "category" in update_data and update_data["category"] is not None:
            try:
                update_data["category"] = MemoryCategory(update_data["category"])
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid category: {update_data['category']}",
                )

        # Update the record
        updated_record = record.model_copy(update=update_data)
        db.update(updated_record)
        vector_store.update(updated_record)

        logger.info("Updated memory: %s", record_id)
        return {"status": "updated"}

    @app.post("/memory/create")
    def create_memory_direct(request: CreateMemoryRequest):
        try:
            category = MemoryCategory(request.category)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid category: {request.category}",
            )

        record_id = f"mem_{uuid.uuid4().hex[:12]}"
        record = MemoryRecord(
            id=record_id,
            category=category,
            title=request.title,
            content=request.content,
            created_at=datetime.now(UTC),
            tags=request.tags or [],
            needs_review=False,
        )

        db.create(record)
        vector_store.add(record)
        logger.info("Created memory: %s", record_id)
        return {"record_id": record_id, "status": "created"}

    @app.post("/memory/bulk/delete")
    def bulk_delete(request: BulkDeleteRequest):
        deleted_count = 0
        for record_id in request.record_ids:
            if db.delete(record_id):
                vector_store.delete(record_id)
                deleted_count += 1
                logger.info("Deleted memory: %s", record_id)

        return {"deleted": deleted_count}

    @app.post("/memory/bulk/update")
    def bulk_update(request: BulkUpdateRequest):
        allowed_fields = {"title", "content", "category", "tags", "needs_review"}
        updated_count = 0
        for record_id in request.record_ids:
            record = db.get(record_id)
            if record is None:
                continue

            update_data = {k: v for k, v in request.updates.items() if k in allowed_fields}
            if not update_data:
                continue

            # Handle category string to enum conversion
            if "category" in update_data and update_data["category"] is not None:
                try:
                    update_data["category"] = MemoryCategory(update_data["category"])
                except ValueError:
                    continue

            updated_record = record.model_copy(update=update_data)
            db.update(updated_record)
            vector_store.update(updated_record)
            updated_count += 1
            logger.info("Updated memory: %s", record_id)

        return {"updated": updated_count}

    return app
