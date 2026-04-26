import logging
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from bearmemori.api.schemas import (
    BulkDeleteRequest,
    BulkUpdateRequest,
    ConfirmRequest,
    TriageRequest,
    UpdateMemoryRequest,
)
from bearmemori.core.memory_service import MemoryService
from bearmemori.core.reflection import ReflectionTask
from bearmemori.core.triage import run_triage
from bearmemori.llm.client import LLMClient
from bearmemori.storage.database import MemoryDatabase
from bearmemori.storage.models import (
    Actor,
    EventFields,
    MemoryCategory,
    MemoryDraft,
    MemoryRecord,
    MemorySource,
)
from bearmemori.storage.pending_store import PendingStore
from bearmemori.storage.vector_store import VectorStore

logger = logging.getLogger(__name__)


def create_app(
    db: MemoryDatabase,
    vector_store: VectorStore,
    pending_store: PendingStore,
    memory_service: MemoryService,
    llm: LLMClient | None = None,
    reflection_task: ReflectionTask | None = None,
    user_timezone: str = "UTC",
    image_storage_dir: str = "",
) -> FastAPI:
    app = FastAPI(title="BearMemori", version="0.3.9")

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.post("/memory/triage")
    async def triage_conversation(request: TriageRequest):
        if llm is None:
            return {"error": "LLM is not configured"}
        logger.info(
            "Triage request: conversation_len=%d, memory_hint=%s, current_time=%s",
            len(request.conversation),
            request.memory_hint,
            request.current_time,
        )
        if request.conversation:
            logger.info(
                "Triage last message: %s",
                request.conversation[-1].get("content", "")[:200],
            )
        result = await run_triage(
            request.conversation,
            llm=llm,
            memory_hint=request.memory_hint,
            current_time=request.current_time,
            user_timezone=user_timezone,
        )
        if not result.should_save or result.draft is None:
            response = {"should_save": False}
            if result.reason:
                response["reason"] = result.reason
            return response

        pending_id = pending_store.add(result.draft)
        logger.info("Triage proposed memory: %s", pending_id)
        return {
            "should_save": True,
            "pending_id": pending_id,
            "draft": result.draft.model_dump(mode="json"),
        }

    @app.post("/memory/reflection/run")
    async def run_reflection():
        if reflection_task is None:
            return {"error": "Reflection is not configured"}
        summary = await reflection_task.run_once(triggered_by="api")
        return summary

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

        if request.source_chat_id:
            record.source = MemorySource(
                platform="telegram",
                chat_id=request.source_chat_id,
            )

        db.create(record, actor=Actor.API)
        vector_store.add(record)
        pending_store.remove(request.pending_id)

        logger.info("Confirmed memory: %s -> %s", request.pending_id, record_id)
        return {"record_id": record_id, "status": "confirmed"}

    @app.get("/memory/search")
    def search_memories(query: str, category: str | None = None, top_k: int = 5):
        results = memory_service.search(query=query, top_k=top_k, category=category)
        return {"results": results}

    @app.get("/memory/retrieve")
    def retrieve_context(query_context: str, top_k: int = 5, event_days: int = 7):
        return memory_service.retrieve_context(
            query=query_context, top_k=top_k, event_days=event_days
        )

    @app.get("/memory/events/upcoming")
    def get_upcoming_events(days: int = 7, start: str | None = None, end: str | None = None):
        from bearmemori.core.recurrence import expand_occurrences

        if start and end:
            try:
                start_dt = datetime.fromisoformat(start)
                end_dt = datetime.fromisoformat(end)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid start or end datetime format")
            records = db.get_events_in_range(start_dt, end_dt)
            occurrences = []
            for r in records:
                occurrences.extend(expand_occurrences(r, start_dt, end_dt))
            return {
                "events": [e.model_dump(mode="json") for e in records],
                "occurrences": [o.model_dump(mode="json") for o in occurrences],
            }

        events = db.get_upcoming_events(days=days)
        return {"events": [e.model_dump(mode="json") for e in events]}

    @app.get("/memory/events/due")
    def get_due_events():
        events = db.get_due_events()
        return {"events": [e.model_dump(mode="json") for e in events]}

    @app.get("/memory/list")
    def list_memories(
        category: str | None = None,
        needs_review: bool | None = None,
        offset: int = 0,
        limit: int = 50,
    ):
        limit = min(limit, 200)

        if category is not None:
            try:
                cat = MemoryCategory(category)
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid category: {category}",
                )
            total = db.count_by_category(cat)
        else:
            total = db.count_all()

        try:
            records = memory_service.list(
                category=category,
                needs_review=needs_review,
                offset=offset,
                limit=limit,
            )
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid category: {category}",
            )

        return {
            "memories": [r.model_dump(mode="json") for r in records],
            "total": total,
            "offset": offset,
            "limit": limit,
        }

    @app.get("/memory/recent")
    def get_recent_memories(since: str, limit: int = 50):
        try:
            since_dt = datetime.fromisoformat(since.replace(" ", "+"))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid 'since' datetime format")
        memories = db.list_recently_updated(since=since_dt, limit=limit)
        return {
            "memories": [m.model_dump(mode="json") for m in memories],
            "count": len(memories),
        }

    @app.get("/memory/briefing")
    def get_briefing(event_days: int = 7):
        due = db.get_due_events()
        upcoming = db.get_upcoming_events(days=event_days)
        review_count = db.count_needs_review()
        total = db.count_all()
        recent = db.count_recent(hours=24)

        return {
            "due_now": {
                "count": len(due),
                "items": [e.model_dump(mode="json") for e in due],
            },
            "upcoming_events": {
                "count": len(upcoming),
                "items": [e.model_dump(mode="json") for e in upcoming],
            },
            "needs_review": {
                "count": review_count,
            },
            "total_memories": total,
            "recent_activity": {
                "created_last_24h": recent["created"],
                "updated_last_24h": recent["updated"],
            },
        }

    @app.get("/memory/{record_id}")
    def get_memory(record_id: str):
        record = memory_service.get(record_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Memory not found")
        return record.model_dump(mode="json")

    @app.delete("/memory/{record_id}")
    def delete_memory(record_id: str):
        deleted = memory_service.delete(record_id, actor=Actor.API)
        if not deleted:
            raise HTTPException(status_code=404, detail="Memory not found")
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

        # Extract event-specific fields before model_copy
        event_status = update_data.pop("event_status", None)
        event_datetime = update_data.pop("event_datetime", None)
        event_recurrence = update_data.pop("event_recurrence", None)
        occurrence_date = update_data.pop("occurrence_date", None)

        has_event_updates = any(
            v is not None for v in [event_status, event_datetime, event_recurrence]
        )

        if has_event_updates and record.event_fields is None:
            raise HTTPException(
                status_code=400,
                detail="Cannot set event fields on a non-event memory",
            )

        if occurrence_date is not None and event_status is None:
            raise HTTPException(
                status_code=400,
                detail="occurrence_date requires event_status",
            )

        if occurrence_date is not None and (
            record.event_fields is None or not record.event_fields.recurrence
        ):
            raise HTTPException(
                status_code=400,
                detail="occurrence_date is only valid for recurring events",
            )

        # Handle category as string to MemoryCategory enum
        if "category" in update_data and update_data["category"] is not None:
            try:
                update_data["category"] = MemoryCategory(update_data["category"])
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid category: {update_data['category']}",
                )

        # Apply non-event updates
        updated_record = record.model_copy(update=update_data) if update_data else record

        # Apply event field updates
        if has_event_updates and updated_record.event_fields is not None:
            if occurrence_date is not None:
                # Toggle specific occurrence in completed_occurrences metadata
                completed = list(updated_record.metadata.get("completed_occurrences", []))
                if event_status == "done" and occurrence_date not in completed:
                    completed.append(occurrence_date)
                elif event_status == "pending" and occurrence_date in completed:
                    completed.remove(occurrence_date)
                updated_record.metadata["completed_occurrences"] = completed
            else:
                # Update event fields directly
                updated_record.event_fields = EventFields(
                    datetime=event_datetime
                    if event_datetime is not None
                    else updated_record.event_fields.datetime,
                    status=event_status
                    if event_status is not None
                    else updated_record.event_fields.status,
                    recurrence=event_recurrence
                    if event_recurrence is not None
                    else updated_record.event_fields.recurrence,
                )

        db.update(updated_record, actor=Actor.API)
        vector_store.update(updated_record)

        logger.info("Updated memory: %s", record_id)
        return {"status": "updated"}

    @app.post("/memory/create")
    def create_memory_direct(draft: MemoryDraft):
        record = memory_service.create(draft, actor=Actor.API)
        return {"record_id": record.id, "status": "created"}

    @app.post("/memory/bulk/delete")
    def bulk_delete(request: BulkDeleteRequest):
        deleted_count = memory_service.bulk_delete(request.record_ids, actor=Actor.API)
        return {"deleted": deleted_count}

    @app.post("/memory/bulk/update")
    def bulk_update(request: BulkUpdateRequest):
        updated_count = memory_service.bulk_update(
            request.record_ids, request.updates, actor=Actor.API
        )
        return {"updated": updated_count}

    @app.get("/images/{filename}")
    def get_image(filename: str):
        if not image_storage_dir:
            raise HTTPException(status_code=404, detail="Image storage not configured")
        file_path = (Path(image_storage_dir) / filename).resolve()
        if not str(file_path).startswith(str(Path(image_storage_dir).resolve())):
            raise HTTPException(status_code=400, detail="Invalid filename")
        if not file_path.exists() or not file_path.is_file():
            raise HTTPException(status_code=404, detail="Image not found")
        return FileResponse(file_path, media_type="image/jpeg")

    return app
