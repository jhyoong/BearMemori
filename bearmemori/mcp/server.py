from __future__ import annotations

from bearmemori.config import Settings
from bearmemori.core.memory_service import MemoryService
from bearmemori.core.reflection import ReflectionTask
from bearmemori.core.triage import run_triage
from bearmemori.llm.client import LLMClient
from bearmemori.storage.database import MemoryDatabase
from bearmemori.storage.models import Actor
from bearmemori.storage.pending_store import PendingStore
from bearmemori.storage.vector_store import VectorStore


async def _handle_triage_conversation(
    conversation: list[dict],
    memory_hint: dict | None,
    current_time: str | None,
    llm: LLMClient | None,
    pending_store: PendingStore | None,
    user_timezone: str,
) -> dict:
    """Tool handler logic extracted for testability."""
    if llm is None or pending_store is None:
        return {"error": "Triage is not configured on this server"}
    result = await run_triage(
        conversation,
        llm=llm,
        memory_hint=memory_hint,
        current_time=current_time,
        user_timezone=user_timezone,
    )
    if not result.should_save or result.draft is None:
        response: dict = {"should_save": False}
        if result.reason:
            response["reason"] = result.reason
        return response
    pending_id = pending_store.add(result.draft)
    return {
        "should_save": True,
        "pending_id": pending_id,
        "draft": result.draft.model_dump(mode="json"),
    }


def create_mcp_app(
    db: MemoryDatabase,
    vector_store: VectorStore,
    settings: Settings,
    llm: LLMClient | None = None,
    pending_store: PendingStore | None = None,
    reflection_task: ReflectionTask | None = None,
    memory_service: MemoryService | None = None,
):
    """Build and return the MCP ASGI sub-app."""
    if memory_service is None:
        memory_service = MemoryService(
            db=db,
            vector_store=vector_store,
            image_storage_dir=settings.image_storage_dir
            if hasattr(settings, "image_storage_dir")
            else "",
        )

    from mcp.server.fastmcp import FastMCP
    from mcp.server.transport_security import TransportSecuritySettings

    mcp = FastMCP(
        "BearMemori",
        # DNS rebinding protection is disabled: the MCP app is mounted behind
        # WebappAuthMiddleware which is the actual auth boundary. The host header
        # check would break HTTPX test clients and reverse-proxy deployments.
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )

    @mcp.tool(
        description=(
            "Semantic search over stored memories. "
            "Returns ranked results with content and metadata."
        )
    )
    def search_memories(
        query: str,
        category: str | None = None,
        top_k: int = 5,
    ) -> dict:
        results = memory_service.search(query=query, top_k=top_k, category=category)
        return {"results": results}

    @mcp.tool(
        description=(
            "Get a formatted context block and scored items for LLM injection. "
            "Combines semantic search with upcoming events and importance scoring. "
            "Use this when you want a ready-to-inject memory context string."
        )
    )
    def retrieve_context(
        query_context: str,
        top_k: int = 5,
        event_days: int = 7,
    ) -> dict:
        return memory_service.retrieve_context(
            query=query_context, top_k=top_k, event_days=event_days
        )

    @mcp.tool(
        description=(
            "List memories with optional filters. "
            "category: one of profile, general, event, location, task, reminder. "
            "needs_review: true/false. "
            "offset/limit for pagination (max 200 per page)."
        )
    )
    def list_memories(
        category: str | None = None,
        needs_review: bool | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> dict:
        from bearmemori.storage.models import MemoryCategory

        if category is not None:
            try:
                MemoryCategory(category)
            except ValueError:
                return {"error": f"Invalid category: {category}"}

        limit = min(limit, 200)
        if category is not None:
            cat = MemoryCategory(category)
            total = db.count_by_category(cat)
        else:
            total = db.count_all()

        records = memory_service.list(
            category=category,
            needs_review=needs_review,
            offset=offset,
            limit=limit,
        )
        return {
            "memories": [r.model_dump(mode="json") for r in records],
            "total": total,
            "offset": offset,
            "limit": limit,
        }

    @mcp.tool(description="Get a single memory by its ID (record_id: e.g. mem_abc123).")
    def get_memory(record_id: str) -> dict:
        record = memory_service.get(record_id)
        if record is None:
            return {"error": f"Memory not found: {record_id}"}
        return record.model_dump(mode="json")

    @mcp.tool(
        description=(
            "Daily briefing summary: due events, upcoming events, needs-review count, "
            "total memories, and recent activity."
        )
    )
    def get_briefing(event_days: int = 7) -> dict:
        due = db.get_due_events()
        upcoming = db.get_upcoming_events(days=event_days)
        review_count = db.count_needs_review()
        total = db.count_all()
        recent = db.count_recent(hours=24)
        return {
            "due_now": {"count": len(due), "items": [e.model_dump(mode="json") for e in due]},
            "upcoming_events": {
                "count": len(upcoming),
                "items": [e.model_dump(mode="json") for e in upcoming],
            },
            "needs_review": {"count": review_count},
            "total_memories": total,
            "recent_activity": {
                "created_last_24h": recent["created"],
                "updated_last_24h": recent["updated"],
            },
        }

    @mcp.tool(
        description=(
            "Get upcoming calendar events. Provide start+end (ISO 8601) for a specific range, "
            "or use days (default 7) for the next N days."
        )
    )
    def get_upcoming_events(
        days: int = 7,
        start: str | None = None,
        end: str | None = None,
    ) -> dict:
        from datetime import datetime

        from bearmemori.core.recurrence import expand_occurrences

        if start and end:
            try:
                start_dt = datetime.fromisoformat(start)
                end_dt = datetime.fromisoformat(end)
            except ValueError:
                return {"error": "Invalid start or end datetime format"}
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

    @mcp.tool(
        description=(
            "Create a new memory. "
            "category: one of profile, general, event, location, task, reminder. "
            "importance: 1-10 (default 5). "
            "For events, provide event_datetime as ISO 8601 string. "
            "event_recurrence: e.g. 'weekly', 'monthly', 'yearly' (optional)."
        )
    )
    def create_memory(
        title: str,
        content: str,
        category: str,
        tags: list[str] | None = None,
        importance: int = 5,
        event_datetime: str | None = None,
        event_status: str = "pending",
        event_recurrence: str | None = None,
    ) -> dict:
        from bearmemori.storage.models import EventFields, MemoryCategory, MemoryDraft

        try:
            cat = MemoryCategory(category)
        except ValueError:
            return {"error": f"Invalid category: {category}"}

        if not (1 <= importance <= 10):
            return {"error": "importance must be between 1 and 10"}

        event_fields = None
        if event_datetime is not None:
            event_fields = EventFields(
                datetime=event_datetime,
                status=event_status,
                recurrence=event_recurrence,
            )

        draft = MemoryDraft(
            category=cat,
            title=title,
            content=content,
            tags=tags or [],
            importance=importance,
            event_fields=event_fields,
        )
        record = memory_service.create(draft, actor=Actor.API)
        return {"record_id": record.id, "status": "created"}

    @mcp.tool(
        description=(
            "Update an existing memory by record_id. All fields are optional — "
            "only provided fields are changed. "
            "category: one of profile, general, event, location, task, reminder. "
            "event_status: pending or done. "
            "occurrence_date: for recurring events, mark a specific occurrence "
            "(ISO date string) as done/pending. "
            "Requires event_status when provided."
        )
    )
    def update_memory(
        record_id: str,
        title: str | None = None,
        content: str | None = None,
        category: str | None = None,
        tags: list[str] | None = None,
        needs_review: bool | None = None,
        importance: int | None = None,
        event_status: str | None = None,
        event_datetime: str | None = None,
        event_recurrence: str | None = None,
        occurrence_date: str | None = None,
    ) -> dict:
        from bearmemori.storage.models import MemoryCategory

        record = memory_service.get(record_id)
        if record is None:
            return {"error": f"Memory not found: {record_id}"}

        if category is not None:
            try:
                MemoryCategory(category)
            except ValueError:
                return {"error": f"Invalid category: {category}"}

        if importance is not None and not (1 <= importance <= 10):
            return {"error": "importance must be between 1 and 10"}

        has_event_updates = any(
            v is not None for v in [event_status, event_datetime, event_recurrence]
        )

        has_simple_updates = any(
            v is not None for v in [title, content, category, tags, needs_review, importance]
        )

        if not has_simple_updates and not has_event_updates and occurrence_date is None:
            return {"error": "No updates provided"}

        if has_event_updates and record.event_fields is None:
            return {"error": "Cannot set event fields on a non-event memory"}

        if occurrence_date is not None and event_status is None:
            return {"error": "occurrence_date requires event_status"}

        if occurrence_date is not None and (
            record.event_fields is None or not record.event_fields.recurrence
        ):
            return {"error": "occurrence_date is only valid for recurring events"}

        # For occurrence_date (recurring event occurrence marking), apply directly
        # since MemoryService.update does not handle completed_occurrences.
        if occurrence_date is not None:
            completed = list(record.metadata.get("completed_occurrences", []))
            if event_status == "done" and occurrence_date not in completed:
                completed.append(occurrence_date)
            elif event_status == "pending" and occurrence_date in completed:
                completed.remove(occurrence_date)
            record.metadata["completed_occurrences"] = completed
            db.update(record, actor=Actor.API)
            vector_store.update(record)
            return {"status": "updated"}

        # Build updates dict for MemoryService
        updates: dict = {}
        if title is not None:
            updates["title"] = title
        if content is not None:
            updates["content"] = content
        if category is not None:
            updates["category"] = category
        if tags is not None:
            updates["tags"] = tags
        if needs_review is not None:
            updates["needs_review"] = needs_review
        if importance is not None:
            updates["importance"] = importance
        if event_status is not None:
            updates["event_status"] = event_status
        if event_datetime is not None:
            updates["event_datetime"] = event_datetime
        if event_recurrence is not None:
            updates["event_recurrence"] = event_recurrence

        memory_service.update(record_id, updates, actor=Actor.API)
        return {"status": "updated"}

    @mcp.tool(description="Delete a memory by record_id. This is permanent.")
    def delete_memory(record_id: str) -> dict:
        deleted = memory_service.delete(record_id, actor=Actor.API)
        if not deleted:
            return {"error": f"Memory not found: {record_id}"}
        return {"status": "deleted"}

    @mcp.tool(
        description=(
            "Analyse a conversation and decide if any information is worth saving as a memory. "
            "Returns should_save=true with a pending_id and draft when memory-worthy"
            " content is found. "
            "The memory enters a pending state for user review — it is not saved automatically. "
            "conversation: list of {role, content} dicts. "
            "memory_hint: optional {likely_category, confidence} from the calling agent. "
            "current_time: optional ISO 8601 string; uses server time if omitted."
        )
    )
    async def triage_conversation(
        conversation: list[dict],
        memory_hint: dict | None = None,
        current_time: str | None = None,
    ) -> dict:
        return await _handle_triage_conversation(
            conversation, memory_hint, current_time, llm, pending_store, settings.user_timezone
        )

    @mcp.tool(
        description=(
            "Trigger a memory reflection run. Reviews stored memories, archives low-value entries, "
            "and reranks importance scores. Returns a summary of what changed. "
            "This bypasses the scheduled time window and runs immediately."
        )
    )
    async def run_reflection() -> dict:
        if reflection_task is None:
            return {"error": "Reflection is not configured on this server"}
        return await reflection_task.run_once(triggered_by="mcp")

    return mcp.sse_app()
