import uuid
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from bearmemori.storage.database import MemoryDatabase
from bearmemori.storage.models import EventFields, MemoryCategory, MemoryRecord
from bearmemori.storage.vector_store import VectorStore
from bearmemori.webapp.auth import WebappAuthMiddleware

TEMPLATE_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))


def _format_event_datetime(value: str) -> str:
    """Format ISO 8601 datetime string as YYYY/MM/DD HH:mm."""
    try:
        dt = datetime.fromisoformat(value)
        return dt.strftime("%Y/%m/%d %H:%M")
    except (ValueError, TypeError):
        return value


templates.env.filters["event_datetime"] = _format_event_datetime

CATEGORIES = [c.value for c in MemoryCategory]

router = APIRouter(prefix="/webapp")


def create_webapp_router(
    db: MemoryDatabase,
    vector_store: VectorStore,
    auth: WebappAuthMiddleware,
) -> APIRouter:
    r = APIRouter(prefix="/webapp")

    @r.get("/login", response_class=HTMLResponse)
    async def login_page(request: Request):
        return templates.TemplateResponse(request, "login.html", {"error": None})

    @r.post("/login")
    async def login_submit(request: Request, secret: str = Form(...)):
        if auth.verify_secret(secret):
            response = RedirectResponse(url="/webapp/memories", status_code=302)
            return auth.create_session_cookie(response)
        return templates.TemplateResponse(
            request, "login.html", {"error": "Invalid secret"}, status_code=401
        )

    @r.get("/memories", response_class=HTMLResponse)
    async def memories_list(
        request: Request,
        q: str | None = None,
        category: str | None = None,
    ):
        if category:
            memories = db.list_by_category(MemoryCategory(category))
        else:
            memories = db.list_all()

        if q:
            search_results = db.search_keyword(q, limit=100)
            search_ids = {m.id for m in search_results}
            memories = [m for m in memories if m.id in search_ids]

        # Check if HTMX request (partial swap)
        if request.headers.get("HX-Request"):
            return templates.TemplateResponse(
                request,
                "partials/memory_table.html",
                {"memories": memories},
            )

        return templates.TemplateResponse(
            request,
            "memories.html",
            {
                "memories": memories,
                "categories": CATEGORIES,
                "q": q,
                "category": category,
            },
        )

    @r.get("/memories/new", response_class=HTMLResponse)
    async def create_memory_page(request: Request):
        return templates.TemplateResponse(request, "create.html", {"categories": CATEGORIES})

    @r.post("/memories/new")
    async def create_memory_submit(
        request: Request,
        title: str = Form(...),
        category: str = Form(...),
        content: str = Form(...),
        tags: str = Form(""),
    ):
        record_id = f"mem_{uuid.uuid4().hex[:12]}"
        tag_list = [t.strip() for t in tags.split(",") if t.strip()]
        record = MemoryRecord(
            id=record_id,
            category=MemoryCategory(category),
            title=title,
            content=content,
            created_at=datetime.now(UTC),
            tags=tag_list,
        )
        db.create(record)
        vector_store.add(record)
        return RedirectResponse(url="/webapp/memories", status_code=302)

    @r.get("/review", response_class=HTMLResponse)
    async def review_queue(request: Request):
        memories = db.list_all(needs_review=True)
        return templates.TemplateResponse(
            request,
            "review_queue.html",
            {"memories": memories, "categories": CATEGORIES},
        )

    @r.post("/memories/bulk/delete")
    async def bulk_delete(request: Request):
        form = await request.form()
        record_ids = form.getlist("record_ids")
        if record_ids:
            db.delete_many(record_ids)
            vector_store.delete_many(record_ids)
        # Return updated table
        memories = db.list_all()
        return templates.TemplateResponse(
            request, "partials/memory_table.html", {"memories": memories}
        )

    @r.post("/memories/bulk/clear-review")
    async def bulk_clear_review(request: Request):
        form = await request.form()
        record_ids = form.getlist("record_ids")
        for rid in record_ids:
            record = db.get(rid)
            if record:
                record.needs_review = False
                db.update(record)
        memories = db.list_all()
        return templates.TemplateResponse(
            request, "partials/memory_table.html", {"memories": memories}
        )

    @r.post("/review/bulk/approve")
    async def bulk_approve(request: Request):
        form = await request.form()
        record_ids = form.getlist("record_ids")
        for rid in record_ids:
            record = db.get(rid)
            if record:
                record.needs_review = False
                db.update(record)
        memories = db.list_all(needs_review=True)
        return templates.TemplateResponse(
            request, "partials/memory_table.html", {"memories": memories}
        )

    # Parameterized routes last to avoid capturing "new", "bulk", etc. as record_id
    @r.get("/memories/{record_id}", response_class=HTMLResponse)
    async def memory_detail(request: Request, record_id: str):
        record = db.get(record_id)
        if not record:
            return RedirectResponse(url="/webapp/memories", status_code=302)
        return templates.TemplateResponse(
            request,
            "memory_detail.html",
            {"memory": record, "categories": CATEGORIES},
        )

    @r.post("/memories/{record_id}")
    async def memory_update(
        request: Request,
        record_id: str,
        title: str = Form(...),
        category: str = Form(...),
        content: str = Form(...),
        tags: str = Form(""),
        needs_review: bool = Form(False),
        event_datetime: str = Form(""),
        event_status: str = Form("pending"),
        event_recurrence: str = Form(""),
    ):
        record = db.get(record_id)
        if not record:
            return RedirectResponse(url="/webapp/memories", status_code=302)

        record.title = title
        record.category = MemoryCategory(category)
        record.content = content
        record.tags = [t.strip() for t in tags.split(",") if t.strip()]
        record.needs_review = needs_review
        if event_datetime:
            record.event_fields = EventFields(
                datetime=event_datetime,
                status=event_status if event_status in ("pending", "done") else "pending",
                recurrence=event_recurrence if event_recurrence else None,
            )
        else:
            record.event_fields = None
        db.update(record)
        vector_store.update(record)
        return RedirectResponse(url=f"/webapp/memories/{record_id}", status_code=302)

    @r.delete("/memories/{record_id}")
    async def memory_delete(record_id: str):
        db.delete(record_id)
        vector_store.delete(record_id)
        return ""  # HTMX removes the element

    return r
