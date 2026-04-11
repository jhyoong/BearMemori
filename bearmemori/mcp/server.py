from __future__ import annotations

from starlette.responses import Response
from starlette.types import ASGIApp, Receive, Scope, Send

from bearmemori.config import Settings
from bearmemori.core.triage import run_triage
from bearmemori.llm.client import LLMClient
from bearmemori.storage.database import MemoryDatabase
from bearmemori.storage.pending_store import PendingStore
from bearmemori.storage.vector_store import VectorStore


class BearerAuthMiddleware:
    """ASGI middleware that enforces Bearer token auth when a secret is configured."""

    def __init__(self, app: ASGIApp, secret: str) -> None:
        self.app = app
        self.secret = secret

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if self.secret and scope["type"] in ("http", "websocket"):
            headers = dict(scope.get("headers", []))
            auth = headers.get(b"authorization", b"").decode()
            if not auth.startswith("Bearer ") or auth[7:] != self.secret:
                response = Response("Unauthorized", status_code=401)
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


def create_mcp_app(
    db: MemoryDatabase,
    vector_store: VectorStore,
    settings: Settings,
    llm: LLMClient | None = None,
    pending_store: PendingStore | None = None,
):
    """Build and return the MCP ASGI sub-app."""
    from mcp.server.fastmcp import FastMCP
    from mcp.server.transport_security import TransportSecuritySettings

    mcp = FastMCP(
        "BearMemori",
        # DNS rebinding protection is disabled: the MCP app is mounted behind
        # BearerAuthMiddleware which is the actual auth boundary. The host header
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
        results = vector_store.search(query=query, top_k=top_k, category=category)
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
        semantic_results = vector_store.search(query=query_context, top_k=top_k * 2)
        upcoming_events = db.get_upcoming_events(days=event_days)

        scored = []
        for r in semantic_results:
            distance = r.get("distance", 1.0)
            similarity = max(0.0, 1.0 - distance)
            importance = r.get("metadata", {}).get("importance", 5) / 10.0
            combined = 0.5 * similarity + 0.5 * importance
            scored.append((combined, r))
        scored.sort(key=lambda x: x[0], reverse=True)

        filtered = []
        for _score, r in scored:
            imp = r.get("metadata", {}).get("importance", 5)
            distance = r.get("distance", 1.0)
            similarity = max(0.0, 1.0 - distance)
            if imp <= 2 and similarity < 0.7:
                continue
            filtered.append(r)
            if len(filtered) >= top_k:
                break

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

        limit = min(limit, 200)
        if category is not None:
            try:
                cat = MemoryCategory(category)
            except ValueError:
                return {"error": f"Invalid category: {category}"}
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

    @mcp.tool(description="Get a single memory by its ID (record_id: e.g. mem_abc123).")
    def get_memory(record_id: str) -> dict:
        record = db.get(record_id)
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
        import uuid
        from datetime import UTC, datetime

        from bearmemori.storage.models import EventFields, MemoryCategory, MemoryRecord

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
        record_id = f"mem_{uuid.uuid4().hex[:12]}"
        record = MemoryRecord(
            id=record_id,
            category=cat,
            title=title,
            content=content,
            created_at=datetime.now(UTC),
            tags=tags or [],
            importance=importance,
            needs_review=False,
            event_fields=event_fields,
        )
        db.create(record)
        vector_store.add(record)
        return {"record_id": record_id, "status": "created"}

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
        from bearmemori.storage.models import EventFields, MemoryCategory

        record = db.get(record_id)
        if record is None:
            return {"error": f"Memory not found: {record_id}"}

        update_data: dict = {}
        if title is not None:
            update_data["title"] = title
        if content is not None:
            update_data["content"] = content
        if category is not None:
            try:
                update_data["category"] = MemoryCategory(category)
            except ValueError:
                return {"error": f"Invalid category: {category}"}
        if tags is not None:
            update_data["tags"] = tags
        if needs_review is not None:
            update_data["needs_review"] = needs_review
        if importance is not None:
            if not (1 <= importance <= 10):
                return {"error": "importance must be between 1 and 10"}
            update_data["importance"] = importance

        has_event_updates = any(
            v is not None for v in [event_status, event_datetime, event_recurrence]
        )

        if not update_data and not has_event_updates and occurrence_date is None:
            return {"error": "No updates provided"}

        if has_event_updates and record.event_fields is None:
            return {"error": "Cannot set event fields on a non-event memory"}

        if occurrence_date is not None and event_status is None:
            return {"error": "occurrence_date requires event_status"}

        if occurrence_date is not None and (
            record.event_fields is None or not record.event_fields.recurrence
        ):
            return {"error": "occurrence_date is only valid for recurring events"}

        updated_record = record.model_copy(update=update_data) if update_data else record

        if has_event_updates and updated_record.event_fields is not None:
            if occurrence_date is not None:
                completed = list(updated_record.metadata.get("completed_occurrences", []))
                if event_status == "done" and occurrence_date not in completed:
                    completed.append(occurrence_date)
                elif event_status == "pending" and occurrence_date in completed:
                    completed.remove(occurrence_date)
                updated_record.metadata["completed_occurrences"] = completed
            else:
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
        return {"status": "updated"}

    @mcp.tool(description="Delete a memory by record_id. This is permanent.")
    def delete_memory(record_id: str) -> dict:
        if settings.image_storage_dir:
            from pathlib import Path

            record_to_delete = db.get(record_id)
            if record_to_delete and record_to_delete.image_path:
                file_path = Path(settings.image_storage_dir) / record_to_delete.image_path
                if file_path.exists():
                    file_path.unlink()
        deleted = db.delete(record_id)
        if not deleted:
            return {"error": f"Memory not found: {record_id}"}
        vector_store.delete(record_id)
        return {"status": "deleted"}

    @mcp.tool(
        description=(
            "Analyse a conversation and decide if any information is worth saving as a memory. "
            "Returns should_save=true with a pending_id and draft when memory-worthy content is found. "
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
        if llm is None or pending_store is None:
            return {"error": "Triage is not configured on this server"}
        result = await run_triage(
            conversation,
            llm=llm,
            memory_hint=memory_hint,
            current_time=current_time,
            user_timezone=settings.user_timezone,
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

    app = mcp.sse_app()
    if settings.webapp_secret:
        app = BearerAuthMiddleware(app, settings.webapp_secret)
    return app
