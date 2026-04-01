import calendar as cal_module
import uuid
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from bearmemori.storage.database import MemoryDatabase
from bearmemori.storage.models import EventFields, MemoryCategory, MemoryRecord
from bearmemori.storage.vector_store import VectorStore
from bearmemori.utils.time import utc_to_local_iso
from bearmemori.webapp.auth import WebappAuthMiddleware

TEMPLATE_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))


CATEGORIES = [c.value for c in MemoryCategory]

router = APIRouter(prefix="/webapp")


def create_webapp_router(
    db: MemoryDatabase,
    vector_store: VectorStore,
    auth: WebappAuthMiddleware,
    image_storage_dir: str = "",
    user_timezone: str = "UTC",
) -> APIRouter:
    r = APIRouter(prefix="/webapp")

    def _format_event_dt(value: str) -> str:
        try:
            local_iso = utc_to_local_iso(value, user_timezone)
            dt = datetime.fromisoformat(local_iso)
            return dt.strftime("%Y/%m/%d %H:%M")
        except (ValueError, TypeError):
            return value

    def _format_event_dt_input(value: str) -> str:
        try:
            local_iso = utc_to_local_iso(value, user_timezone)
            dt = datetime.fromisoformat(local_iso)
            return dt.strftime("%Y-%m-%dT%H:%M")
        except (ValueError, TypeError):
            return value

    templates.env.filters["event_datetime"] = _format_event_dt
    templates.env.filters["event_datetime_input"] = _format_event_dt_input

    def _delete_image_file(record_id: str) -> None:
        if not image_storage_dir:
            return
        record = db.get(record_id)
        if record and record.image_path:
            file_path = Path(image_storage_dir) / record.image_path
            if file_path.exists():
                file_path.unlink()

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
        importance: int = Form(5),
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
            importance=max(1, min(10, importance)),
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
            for rid in record_ids:
                _delete_image_file(rid)
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
        importance: int = Form(5),
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
        record.importance = max(1, min(10, importance))
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
        _delete_image_file(record_id)
        db.delete(record_id)
        vector_store.delete(record_id)
        return ""  # HTMX removes the element

    def _build_calendar_context(view: str, year: int, month: int, week_start_str: str | None):
        from bearmemori.core.recurrence import expand_occurrences

        today = datetime.now(UTC).date()

        if view == "week":
            from datetime import date, timedelta

            if week_start_str:
                ws = date.fromisoformat(week_start_str)
            else:
                ws = today - timedelta(days=today.weekday())
            we = ws + timedelta(days=6)
            start_dt = datetime(ws.year, ws.month, ws.day, tzinfo=UTC)
            end_dt = datetime(we.year, we.month, we.day, 23, 59, 59, tzinfo=UTC)

            prev_ws = (ws - timedelta(days=7)).isoformat()
            next_ws = (ws + timedelta(days=7)).isoformat()

            records = db.get_events_in_range(start_dt, end_dt)
            all_occs = []
            for rec in records:
                all_occs.extend(expand_occurrences(rec, start_dt, end_dt))

            by_date = defaultdict(list)
            for occ in all_occs:
                local_iso = utc_to_local_iso(occ.occurrence_dt.isoformat(), user_timezone)
                occ_date = datetime.fromisoformat(local_iso).date().isoformat()
                by_date[occ_date].append({
                    "memory_id": occ.memory_id,
                    "title": occ.title,
                    "category": occ.category,
                    "time": datetime.fromisoformat(local_iso).strftime("%H:%M"),
                    "status": occ.status,
                    "is_recurring": occ.is_recurring,
                    "occurrence_date": occ.occurrence_dt.date().isoformat(),
                })

            days = []
            for i in range(7):
                from datetime import timedelta as td

                d = ws + td(days=i)
                days.append({
                    "date": d.isoformat(),
                    "label": d.strftime("%a %-d"),
                    "occurrences": by_date.get(d.isoformat(), []),
                })

            return {
                "view": "week",
                "week_start": ws.isoformat(),
                "days": days,
                "prev_url": f"/webapp/calendar/grid?view=week&week_start={prev_ws}",
                "next_url": f"/webapp/calendar/grid?view=week&week_start={next_ws}",
                "today": today.isoformat(),
            }

        else:  # month view
            from datetime import date

            y = year or today.year
            m = month or today.month
            first_day = date(y, m, 1)
            last_day = date(y, m, cal_module.monthrange(y, m)[1])
            start_dt = datetime(y, m, 1, tzinfo=UTC)
            end_dt = datetime(last_day.year, last_day.month, last_day.day, 23, 59, 59, tzinfo=UTC)

            if m == 1:
                prev_url = f"/webapp/calendar/grid?view=month&year={y - 1}&month=12"
            else:
                prev_url = f"/webapp/calendar/grid?view=month&year={y}&month={m - 1}"
            if m == 12:
                next_url = f"/webapp/calendar/grid?view=month&year={y + 1}&month=1"
            else:
                next_url = f"/webapp/calendar/grid?view=month&year={y}&month={m + 1}"

            records = db.get_events_in_range(start_dt, end_dt)
            all_occs = []
            for rec in records:
                all_occs.extend(expand_occurrences(rec, start_dt, end_dt))

            by_date = defaultdict(list)
            for occ in all_occs:
                local_iso = utc_to_local_iso(occ.occurrence_dt.isoformat(), user_timezone)
                occ_date = datetime.fromisoformat(local_iso).date().isoformat()
                by_date[occ_date].append({
                    "memory_id": occ.memory_id,
                    "title": occ.title,
                    "category": occ.category,
                    "time": datetime.fromisoformat(local_iso).strftime("%H:%M"),
                    "status": occ.status,
                    "is_recurring": occ.is_recurring,
                    "occurrence_date": occ.occurrence_dt.date().isoformat(),
                })

            weeks = []
            cal = cal_module.monthcalendar(y, m)
            for week in cal:
                week_days = []
                for day_num in week:
                    if day_num == 0:
                        week_days.append(None)
                    else:
                        d = date(y, m, day_num)
                        week_days.append({
                            "date": d.isoformat(),
                            "day": day_num,
                            "in_month": True,
                            "occurrences": by_date.get(d.isoformat(), []),
                        })
                weeks.append(week_days)

            return {
                "view": "month",
                "year": y,
                "month": m,
                "month_name": first_day.strftime("%B %Y"),
                "weeks": weeks,
                "prev_url": prev_url,
                "next_url": next_url,
                "today": today.isoformat(),
            }

    @r.get("/calendar", response_class=HTMLResponse)
    async def calendar_page(
        request: Request,
        view: str = "month",
        year: int = 0,
        month: int = 0,
        week_start: str | None = None,
    ):
        today = datetime.now(UTC)
        ctx = _build_calendar_context(
            view,
            year or today.year,
            month or today.month,
            week_start,
        )
        year_val = ctx.get("year", "")
        month_val = ctx.get("month", "")
        ctx["current_view_url"] = (
            f"/webapp/calendar/grid?view={view}&year={year_val}&month={month_val}"
        )
        return templates.TemplateResponse(request, "calendar.html", ctx)

    @r.get("/calendar/grid", response_class=HTMLResponse)
    async def calendar_grid(
        request: Request,
        view: str = "month",
        year: int = 0,
        month: int = 0,
        week_start: str | None = None,
    ):
        today = datetime.now(UTC)
        ctx = _build_calendar_context(
            view,
            year or today.year,
            month or today.month,
            week_start,
        )
        return templates.TemplateResponse(request, "partials/calendar_grid.html", ctx)

    @r.post("/calendar/occurrence/toggle", response_class=HTMLResponse)
    async def toggle_occurrence(
        request: Request,
        memory_id: str = Form(...),
        occurrence_date: str = Form(...),
        view: str = Form("month"),
        year: int = Form(0),
        month: int = Form(0),
        week_start: str = Form(""),
    ):
        record = db.get(memory_id)
        if record:
            completed = list(record.metadata.get("completed_occurrences", []))
            if occurrence_date in completed:
                completed.remove(occurrence_date)
            else:
                completed.append(occurrence_date)
            record.metadata["completed_occurrences"] = completed
            db.update(record)

        today = datetime.now(UTC)
        ctx = _build_calendar_context(
            view,
            year or today.year,
            month or today.month,
            week_start or None,
        )
        return templates.TemplateResponse(request, "partials/calendar_grid.html", ctx)

    return r
