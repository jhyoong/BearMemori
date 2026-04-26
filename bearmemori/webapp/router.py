import calendar as cal_module
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from bearmemori.core.memory_service import MemoryService
from bearmemori.storage.database import MemoryDatabase
from bearmemori.storage.models import Actor, EventFields, MemoryCategory, MemoryDraft
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
    memory_service: MemoryService | None = None,
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
        page: int = 1,
        per_page: int = 50,
    ):
        per_page = min(per_page, 200)
        offset = (page - 1) * per_page

        if q:
            if category:
                all_memories = db.list_by_category(MemoryCategory(category))
            else:
                all_memories = db.list_all()
            search_results = db.search_keyword(q, limit=100)
            search_ids = {m.id for m in search_results}
            filtered = [m for m in all_memories if m.id in search_ids]
            total = len(filtered)
            memories = filtered[offset : offset + per_page]
        elif category:
            memories = db.list_by_category(MemoryCategory(category), offset=offset, limit=per_page)
            total = db.count_by_category(MemoryCategory(category))
        else:
            memories = db.list_all(offset=offset, limit=per_page)
            total = db.count_all()

        total_pages = max(1, (total + per_page - 1) // per_page)

        context = {
            "memories": memories,
            "categories": CATEGORIES,
            "q": q,
            "category": category,
            "page": page,
            "per_page": per_page,
            "total": total,
            "total_pages": total_pages,
        }

        # Check if HTMX request (partial swap)
        if request.headers.get("HX-Request"):
            return templates.TemplateResponse(
                request,
                "partials/memory_table.html",
                context,
            )

        return templates.TemplateResponse(request, "memories.html", context)

    @r.get("/memories/new", response_class=HTMLResponse)
    async def create_memory_page(request: Request):
        from bearmemori.core.recurrence import parse_rrule_to_form

        event_dt = request.query_params.get("event_datetime", "")
        return templates.TemplateResponse(
            request,
            "create.html",
            {
                "categories": CATEGORIES,
                "rrule_form": parse_rrule_to_form(""),
                "event_datetime_value": event_dt,
                "event_status": "pending",
            },
        )

    @r.post("/memories/new")
    async def create_memory_submit(
        request: Request,
        title: str = Form(...),
        category: str = Form(...),
        content: str = Form(...),
        tags: str = Form(""),
        importance: int = Form(5),
        event_datetime: str = Form(""),
        event_status: str = Form("pending"),
        rrule_freq: str = Form(""),
        rrule_interval: int = Form(1),
        rrule_byday: list[str] = Form(default=[]),
        rrule_bymonthday: str = Form(""),
        rrule_until: str = Form(""),
    ):
        from bearmemori.core.recurrence import build_rrule_from_form

        recurrence = build_rrule_from_form(
            freq=rrule_freq,
            interval=rrule_interval,
            byday=rrule_byday,
            bymonthday=rrule_bymonthday,
            until=rrule_until,
        )
        tag_list = [t.strip() for t in tags.split(",") if t.strip()]
        draft = MemoryDraft(
            category=MemoryCategory(category),
            title=title,
            content=content,
            tags=tag_list,
            importance=max(1, min(10, importance)),
            event_fields=EventFields(
                datetime=event_datetime,
                status="pending",
                recurrence=recurrence if recurrence else None,
            )
            if event_datetime
            else None,
        )
        memory_service.create(draft)

        return_to = request.query_params.get("return", "")
        if return_to == "calendar":
            return RedirectResponse(url="/webapp/calendar", status_code=302)
        return RedirectResponse(url="/webapp/memories", status_code=302)

    @r.get("/review", response_class=HTMLResponse)
    async def review_queue(request: Request):
        memories = memory_service.list(needs_review=True)
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
            memory_service.bulk_delete(record_ids)
        # Return updated table
        memories = db.list_all()
        return templates.TemplateResponse(
            request, "partials/memory_table.html", {"memories": memories}
        )

    @r.post("/memories/bulk/clear-review")
    async def bulk_clear_review(request: Request):
        form = await request.form()
        record_ids = form.getlist("record_ids")
        memory_service.bulk_update(record_ids, {"needs_review": False})
        memories = db.list_all()
        return templates.TemplateResponse(
            request, "partials/memory_table.html", {"memories": memories}
        )

    @r.post("/review/bulk/approve")
    async def bulk_approve(request: Request):
        form = await request.form()
        record_ids = form.getlist("record_ids")
        memory_service.bulk_update(record_ids, {"needs_review": False})
        memories = db.list_all(needs_review=True)
        return templates.TemplateResponse(
            request, "partials/memory_table.html", {"memories": memories}
        )

    # Parameterized routes last to avoid capturing "new", "bulk", etc. as record_id
    @r.get("/memories/{record_id}", response_class=HTMLResponse)
    async def memory_detail(request: Request, record_id: str):
        from bearmemori.core.recurrence import parse_rrule_to_form

        record = memory_service.get(record_id)
        if not record:
            return RedirectResponse(url="/webapp/memories", status_code=302)
        rrule_form = parse_rrule_to_form(
            record.event_fields.recurrence if record.event_fields else ""
        )
        event_dt_value = ""
        if record.event_fields:
            event_dt_value = _format_event_dt_input(record.event_fields.datetime)
        return templates.TemplateResponse(
            request,
            "memory_detail.html",
            {
                "memory": record,
                "categories": CATEGORIES,
                "rrule_form": rrule_form,
                "event_datetime_value": event_dt_value,
                "event_status": record.event_fields.status if record.event_fields else "pending",
            },
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
        rrule_freq: str = Form(""),
        rrule_interval: int = Form(1),
        rrule_byday: list[str] = Form(default=[]),
        rrule_bymonthday: str = Form(""),
        rrule_until: str = Form(""),
    ):
        from bearmemori.core.recurrence import build_rrule_from_form

        record = memory_service.get(record_id)
        if not record:
            return RedirectResponse(url="/webapp/memories", status_code=302)

        recurrence = build_rrule_from_form(
            freq=rrule_freq,
            interval=rrule_interval,
            byday=rrule_byday,
            bymonthday=rrule_bymonthday,
            until=rrule_until,
        )

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
                recurrence=recurrence if recurrence else None,
            )
        else:
            record.event_fields = None
        db.update(record, actor=Actor.WEBAPP)
        vector_store.update(record)

        return_to = request.query_params.get("return", "")
        if return_to == "calendar":
            return RedirectResponse(url="/webapp/calendar", status_code=302)
        return RedirectResponse(url=f"/webapp/memories/{record_id}", status_code=302)

    @r.delete("/memories/{record_id}")
    async def memory_delete(record_id: str):
        memory_service.delete(record_id)
        return ""  # HTMX removes the element

    def _occurrences_by_date(start_dt: datetime, end_dt: datetime) -> dict[str, list]:
        from bearmemori.core.recurrence import expand_occurrences

        records = db.get_events_in_range(start_dt, end_dt)
        all_occs = []
        for rec in records:
            all_occs.extend(expand_occurrences(rec, start_dt, end_dt))

        by_date: dict[str, list] = defaultdict(list)
        for occ in all_occs:
            local_iso = utc_to_local_iso(occ.occurrence_dt.isoformat(), user_timezone)
            local_dt = datetime.fromisoformat(local_iso)
            by_date[local_dt.date().isoformat()].append(
                {
                    "memory_id": occ.memory_id,
                    "title": occ.title,
                    "category": occ.category,
                    "time": local_dt.strftime("%H:%M"),
                    "status": occ.status,
                    "is_recurring": occ.is_recurring,
                    "occurrence_date": occ.occurrence_dt.date().isoformat(),
                }
            )
        return by_date

    def _build_calendar_context(view: str, year: int, month: int, week_start_str: str | None):
        from datetime import date, timedelta

        today = datetime.now(UTC).date()

        if view == "week":
            if week_start_str:
                ws = date.fromisoformat(week_start_str)
            else:
                ws = today - timedelta(days=today.weekday())
            we = ws + timedelta(days=6)
            start_dt = datetime(ws.year, ws.month, ws.day, tzinfo=UTC)
            end_dt = datetime(we.year, we.month, we.day, 23, 59, 59, tzinfo=UTC)

            prev_ws = (ws - timedelta(days=7)).isoformat()
            next_ws = (ws + timedelta(days=7)).isoformat()

            by_date = _occurrences_by_date(start_dt, end_dt)

            days = []
            for i in range(7):
                d = ws + timedelta(days=i)
                days.append(
                    {
                        "date": d.isoformat(),
                        "label": d.strftime("%a %-d"),
                        "occurrences": by_date.get(d.isoformat(), []),
                    }
                )

            return {
                "view": "week",
                "week_start": ws.isoformat(),
                "days": days,
                "prev_url": f"/webapp/calendar/grid?view=week&week_start={prev_ws}",
                "next_url": f"/webapp/calendar/grid?view=week&week_start={next_ws}",
                "today": today.isoformat(),
            }

        else:  # month view
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

            by_date = _occurrences_by_date(start_dt, end_dt)

            weeks = []
            cal = cal_module.monthcalendar(y, m)
            for week in cal:
                week_days = []
                for day_num in week:
                    if day_num == 0:
                        week_days.append(None)
                    else:
                        d = date(y, m, day_num)
                        week_days.append(
                            {
                                "date": d.isoformat(),
                                "day": day_num,
                                "in_month": True,
                                "occurrences": by_date.get(d.isoformat(), []),
                            }
                        )
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
        if record and record.event_fields:
            if record.event_fields.recurrence:
                # Recurring: toggle the specific occurrence date
                completed = list(record.metadata.get("completed_occurrences", []))
                if occurrence_date in completed:
                    completed.remove(occurrence_date)
                else:
                    completed.append(occurrence_date)
                record.metadata["completed_occurrences"] = completed
            else:
                # Non-recurring: toggle status directly
                new_status = "done" if record.event_fields.status == "pending" else "pending"
                record.event_fields = EventFields(
                    datetime=record.event_fields.datetime,
                    status=new_status,
                    recurrence=None,
                )
            db.update(record, actor=Actor.WEBAPP)

        today = datetime.now(UTC)
        ctx = _build_calendar_context(
            view,
            year or today.year,
            month or today.month,
            week_start or None,
        )
        return templates.TemplateResponse(request, "partials/calendar_grid.html", ctx)

    return r
