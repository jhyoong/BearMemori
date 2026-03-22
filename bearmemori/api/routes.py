import logging
import uuid

from fastapi import FastAPI, HTTPException

from bearmemori.api.schemas import ConfirmRequest, SearchRequest, TriageRequest
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
) -> FastAPI:
    app = FastAPI(title="BearMemori", version="0.4.0")

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
    def list_memories(category: str | None = None):
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

    return app
