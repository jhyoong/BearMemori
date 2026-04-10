from __future__ import annotations

from starlette.responses import Response
from starlette.types import ASGIApp, Receive, Scope, Send

from bearmemori.config import Settings
from bearmemori.storage.database import MemoryDatabase
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
):
    """Build and return the MCP ASGI sub-app."""
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("BearMemori")

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

    @mcp.tool(description="Get a single memory by its ID (e.g. mem_abc123).")
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

    app = mcp.sse_app()
    if settings.webapp_secret:
        app = BearerAuthMiddleware(app, settings.webapp_secret)
    return app
