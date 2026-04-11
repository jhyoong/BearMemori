import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from bearmemori.api.schemas import (
    BulkDeleteRequest,
    BulkUpdateRequest,
    ConfirmRequest,
    CreateMemoryRequest,
    TriageRequest,
    UpdateMemoryRequest,
)
from bearmemori.core.triage import run_triage
from bearmemori.llm.client import LLMClient
from bearmemori.storage.database import MemoryDatabase
from bearmemori.storage.models import (
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
    llm: LLMClient | None = None,
    user_timezone: str = "UTC",
    image_storage_dir: str = "",
) -> FastAPI:
    app = FastAPI(title="BearMemori", version="0.3.9")

    def _delete_image(record_id: str) -> None:
        if not image_storage_dir:
            return
        record = db.get(record_id)
        if record and record.image_path:
            file_path = Path(image_storage_dir) / record.image_path
            if file_path.exists():
                file_path.unlink()
                logger.info("Deleted image: %s", file_path)

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
            record.metadata["source_chat_id"] = request.source_chat_id

        db.create(record)
        vector_store.add(record)
        pending_store.remove(request.pending_id)

        logger.info("Confirmed memory: %s -> %s", request.pending_id, record_id)
        return {"record_id": record_id, "status": "confirmed"}

    @app.get("/memory/search")
    def search_memories(query: str, category: str | None = None, top_k: int = 5):
        results = vector_store.search(
            query=query,
            top_k=top_k,
            category=category,
        )
        return {"results": results}

    @app.get("/memory/retrieve")
    def retrieve_context(query_context: str, top_k: int = 5, event_days: int = 7):
        # Fetch more candidates than needed for scoring
        semantic_results = vector_store.search(query=query_context, top_k=top_k * 2)
        upcoming_events = db.get_upcoming_events(days=event_days)

        # Score and rank by combined relevance + importance
        scored = []
        for r in semantic_results:
            distance = r.get("distance", 1.0)
            similarity = max(0.0, 1.0 - distance)
            importance = r.get("metadata", {}).get("importance", 5) / 10.0
            combined = 0.5 * similarity + 0.5 * importance
            scored.append((combined, r))

        # Sort by combined score descending
        scored.sort(key=lambda x: x[0], reverse=True)

        # Apply importance thresholds
        filtered = []
        for score, r in scored:
            imp = r.get("metadata", {}).get("importance", 5)
            distance = r.get("distance", 1.0)
            similarity = max(0.0, 1.0 - distance)
            # Skip low importance unless highly relevant
            if imp <= 2 and similarity < 0.7:
                continue
            filtered.append(r)
            if len(filtered) >= top_k:
                break

        # Always include high-importance memories with any relevance
        high_imp = [
            r
            for _, r in scored
            if r.get("metadata", {}).get("importance", 5) >= 8 and r not in filtered
        ]
        filtered.extend(high_imp[: max(0, top_k - len(filtered))])

        lines = []
        if filtered:
            lines.append("## Relevant Memories")
            for r in filtered:
                lines.append(f"- {r['document']}")

        if upcoming_events:
            lines.append("\n## Upcoming Events")
            for e in upcoming_events:
                dt = e.event_fields.datetime if e.event_fields else "unknown"
                lines.append(f"- [{dt}] {e.title}: {e.content}")

        context_block = "\n".join(lines) if lines else ""

        items = filtered + [
            {
                "id": e.id,
                "document": f"{e.title}: {e.content}",
                "metadata": {"category": e.category.value},
            }
            for e in upcoming_events
        ]

        return {"context_block": context_block, "items": items}

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
            records = db.list_by_category(cat, offset=offset, limit=limit)
            total = db.count_by_category(cat)
        else:
            records = db.list_all(offset=offset, limit=limit)
            total = db.count_all()

        if needs_review is not None:
            records = [r for r in records if r.needs_review == needs_review]

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
        record = db.get(record_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Memory not found")
        return record.model_dump(mode="json")

    @app.delete("/memory/{record_id}")
    def delete_memory(record_id: str):
        _delete_image(record_id)
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

        event_fields = None
        if request.event_datetime is not None:
            event_fields = EventFields(
                datetime=request.event_datetime,
                status=request.event_status,
                recurrence=request.event_recurrence,
            )

        record_id = f"mem_{uuid.uuid4().hex[:12]}"
        record = MemoryRecord(
            id=record_id,
            category=category,
            title=request.title,
            content=request.content,
            created_at=datetime.now(UTC),
            tags=request.tags or [],
            importance=request.importance,
            needs_review=False,
            event_fields=event_fields,
        )

        db.create(record)
        vector_store.add(record)
        logger.info("Created memory: %s", record_id)
        return {"record_id": record_id, "status": "created"}

    @app.post("/memory/bulk/delete")
    def bulk_delete(request: BulkDeleteRequest):
        deleted_count = 0
        for record_id in request.record_ids:
            _delete_image(record_id)
            if db.delete(record_id):
                vector_store.delete(record_id)
                deleted_count += 1
                logger.info("Deleted memory: %s", record_id)

        return {"deleted": deleted_count}

    @app.post("/memory/bulk/update")
    def bulk_update(request: BulkUpdateRequest):
        allowed_fields = {"title", "content", "category", "tags", "needs_review", "importance"}
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
