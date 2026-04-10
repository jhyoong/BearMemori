import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from urllib.parse import urlencode


def _parse_bool(v: str) -> bool:
    if v.lower() in ("true", "1", "yes"):
        return True
    if v.lower() in ("false", "0", "no"):
        return False
    raise argparse.ArgumentTypeError(f"Boolean value expected, got: {v!r}")


def get_base_url(url_override: str | None) -> str:
    if url_override:
        return url_override
    port = os.environ.get("API_PORT", "8100")
    return f"http://localhost:{port}"


def api_request(
    base_url: str,
    method: str,
    path: str,
    params: dict | None = None,
    body: dict | None = None,
) -> dict | None:
    url = f"{base_url}{path}"
    if params:
        url = f"{url}?{urlencode(params)}"

    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=data, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as e:
        err_body = e.fp.read().decode("utf-8", errors="replace") if e.fp else ""
        try:
            detail = json.loads(err_body).get("detail", err_body)
        except (json.JSONDecodeError, AttributeError):
            detail = err_body
        print(
            json.dumps({"error": detail, "status": e.code}),
            file=sys.stderr,
        )
        return None
    except urllib.error.URLError:
        print(
            json.dumps({"error": f"Cannot connect to server at {base_url}"}),
            file=sys.stderr,
        )
        return None


def output(data: dict) -> None:
    print(json.dumps(data, indent=2, default=str))


def cmd_health(base_url: str) -> int:
    result = api_request(base_url, "GET", "/health")
    if result is None:
        return 1
    output(result)
    return 0


def cmd_get(base_url: str, record_id: str) -> int:
    result = api_request(base_url, "GET", f"/memory/{record_id}")
    if result is None:
        return 1
    output(result)
    return 0


def cmd_briefing(base_url: str, event_days: int = 7) -> int:
    params = {"event_days": event_days}
    result = api_request(base_url, "GET", "/memory/briefing", params=params)
    if result is None:
        return 1
    output(result)
    return 0


def cmd_search(base_url: str, query: str, category: str | None, top_k: int) -> int:
    params = {"query": query, "top_k": top_k}
    if category:
        params["category"] = category
    result = api_request(base_url, "GET", "/memory/search", params=params)
    if result is None:
        return 1
    output(result)
    return 0


def cmd_list(
    base_url: str, category: str | None, needs_review: bool | None, offset: int, limit: int
) -> int:
    params: dict = {"offset": offset, "limit": limit}
    if category:
        params["category"] = category
    if needs_review is not None:
        params["needs_review"] = str(needs_review).lower()
    result = api_request(base_url, "GET", "/memory/list", params=params)
    if result is None:
        return 1
    output(result)
    return 0


def cmd_events(base_url: str, days: int, start: str | None, end: str | None) -> int:
    params: dict = {}
    if start and end:
        params["start"] = start
        params["end"] = end
    else:
        params["days"] = days
    result = api_request(base_url, "GET", "/memory/events/upcoming", params=params)
    if result is None:
        return 1
    output(result)
    return 0


def cmd_create(
    base_url: str,
    title: str,
    content: str,
    category: str,
    tags: str | None,
    importance: int,
) -> int:
    body: dict = {
        "title": title,
        "content": content,
        "category": category,
        "importance": importance,
    }
    if tags:
        body["tags"] = [t.strip() for t in tags.split(",")]
    result = api_request(base_url, "POST", "/memory/create", body=body)
    if result is None:
        return 1
    output(result)
    return 0


def cmd_delete(base_url: str, record_id: str) -> int:
    result = api_request(base_url, "DELETE", f"/memory/{record_id}")
    if result is None:
        return 1
    output(result)
    return 0


def cmd_update(
    base_url: str,
    record_id: str,
    title: str | None,
    content: str | None,
    category: str | None,
    tags: str | None,
    importance: int | None,
    needs_review: bool | None,
    event_status: str | None,
    event_datetime: str | None,
    event_recurrence: str | None,
    occurrence_date: str | None,
) -> int:
    body: dict = {}
    if title is not None:
        body["title"] = title
    if content is not None:
        body["content"] = content
    if category is not None:
        body["category"] = category
    if tags is not None:
        body["tags"] = [t.strip() for t in tags.split(",")]
    if importance is not None:
        body["importance"] = importance
    if needs_review is not None:
        body["needs_review"] = needs_review
    if event_status is not None:
        body["event_status"] = event_status
    if event_datetime is not None:
        body["event_datetime"] = event_datetime
    if event_recurrence is not None:
        body["event_recurrence"] = event_recurrence
    if occurrence_date is not None:
        body["occurrence_date"] = occurrence_date
    if not body:
        print(json.dumps({"error": "No updates provided"}), file=sys.stderr)
        return 1
    result = api_request(base_url, "PUT", f"/memory/{record_id}", body=body)
    if result is None:
        return 1
    output(result)
    return 0


def cmd_triage(
    base_url: str,
    conversation: str,
    memory_hint: str | None,
    current_time: str | None,
) -> int:
    try:
        conv_data = json.loads(conversation)
    except json.JSONDecodeError as e:
        print(json.dumps({"error": f"Invalid JSON for conversation: {e}"}), file=sys.stderr)
        return 1
    body: dict = {"conversation": conv_data}
    if memory_hint:
        try:
            body["memory_hint"] = json.loads(memory_hint)
        except json.JSONDecodeError as e:
            print(json.dumps({"error": f"Invalid JSON for memory_hint: {e}"}), file=sys.stderr)
            return 1
    if current_time:
        body["current_time"] = current_time
    result = api_request(base_url, "POST", "/memory/triage", body=body)
    if result is None:
        return 1
    output(result)
    return 0


def cmd_serve(port: int | None, host: str, no_telegram: bool) -> int:
    import asyncio

    from bearmemori.__main__ import run_server

    asyncio.run(run_server(port=port, host=host, no_telegram=no_telegram))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bearmemori",
        description="BearMemori CLI -- memory store client and server management",
    )
    parser.add_argument("--url", default=None, help="Server URL (default: http://localhost:8100)")

    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("health", help="Check server health")

    p_get = subparsers.add_parser("get", help="Get a memory by ID")
    p_get.add_argument("id", help="Memory record ID")

    p_briefing = subparsers.add_parser("briefing", help="Get daily briefing")
    p_briefing.add_argument(
        "--event-days", type=int, default=7, help="Days of upcoming events (default: 7)"
    )

    p_search = subparsers.add_parser("search", help="Search memories")
    p_search.add_argument("query", help="Search query")
    p_search.add_argument("--category", default=None, help="Filter by category")
    p_search.add_argument("--top-k", type=int, default=5, help="Number of results (default: 5)")

    p_list = subparsers.add_parser("list", help="List memories")
    p_list.add_argument("--category", default=None, help="Filter by category")
    p_list.add_argument(
        "--needs-review", type=_parse_bool, default=None, help="Filter by needs_review"
    )
    p_list.add_argument("--offset", type=int, default=0, help="Pagination offset (default: 0)")
    p_list.add_argument("--limit", type=int, default=50, help="Pagination limit (default: 50)")

    p_events = subparsers.add_parser("events", help="List upcoming events")
    p_events.add_argument("--days", type=int, default=7, help="Days ahead (default: 7)")
    p_events.add_argument("--start", default=None, help="Range start datetime (ISO format)")
    p_events.add_argument("--end", default=None, help="Range end datetime (ISO format)")

    p_create = subparsers.add_parser("create", help="Create a memory")
    p_create.add_argument("--title", required=True, help="Memory title")
    p_create.add_argument("--content", required=True, help="Memory content")
    p_create.add_argument("--category", required=True, help="Memory category")
    p_create.add_argument("--tags", default=None, help="Comma-separated tags")
    p_create.add_argument("--importance", type=int, default=5, help="Importance 1-10 (default: 5)")

    p_delete = subparsers.add_parser("delete", help="Delete a memory")
    p_delete.add_argument("id", help="Memory record ID")

    p_update = subparsers.add_parser("update", help="Update a memory")
    p_update.add_argument("id", help="Memory record ID")
    p_update.add_argument("--title", default=None, help="New title")
    p_update.add_argument("--content", default=None, help="New content")
    p_update.add_argument("--category", default=None, help="New category")
    p_update.add_argument("--tags", default=None, help="New comma-separated tags")
    p_update.add_argument("--importance", type=int, default=None, help="New importance 1-10")
    p_update.add_argument(
        "--needs-review", type=_parse_bool, default=None, help="Set needs_review flag"
    )
    p_update.add_argument(
        "--event-status", choices=["pending", "done"], default=None, help="Set event status"
    )
    p_update.add_argument("--event-datetime", default=None, help="New event datetime (ISO 8601)")
    p_update.add_argument("--event-recurrence", default=None, help="New recurrence rule (RRULE)")
    p_update.add_argument(
        "--occurrence-date", default=None, help="Occurrence date (YYYY-MM-DD) for recurring events"
    )

    p_triage = subparsers.add_parser("triage", help="Run triage on a conversation")
    p_triage.add_argument("--conversation", required=True, help="Conversation JSON array")
    p_triage.add_argument("--memory-hint", default=None, help="Memory hint JSON object")
    p_triage.add_argument("--current-time", default=None, help="Current time (ISO format)")

    p_serve = subparsers.add_parser("serve", help="Start the BearMemori server")
    p_serve.add_argument("--port", type=int, default=None, help="API port (default: from settings)")
    p_serve.add_argument("--host", default="0.0.0.0", help="Bind address (default: 0.0.0.0)")
    p_serve.add_argument("--no-telegram", action="store_true", help="Start without Telegram bot")

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    base_url = get_base_url(args.url)

    commands = {
        "health": lambda: cmd_health(base_url),
        "get": lambda: cmd_get(base_url, args.id),
        "briefing": lambda: cmd_briefing(base_url, args.event_days),
        "search": lambda: cmd_search(base_url, args.query, args.category, args.top_k),
        "list": lambda: cmd_list(
            base_url, args.category, args.needs_review, args.offset, args.limit
        ),
        "events": lambda: cmd_events(base_url, args.days, args.start, args.end),
        "create": lambda: cmd_create(
            base_url, args.title, args.content, args.category, args.tags, args.importance
        ),
        "delete": lambda: cmd_delete(base_url, args.id),
        "update": lambda: cmd_update(
            base_url,
            args.id,
            args.title,
            args.content,
            args.category,
            args.tags,
            args.importance,
            args.needs_review,
            args.event_status,
            args.event_datetime,
            args.event_recurrence,
            args.occurrence_date,
        ),
        "triage": lambda: cmd_triage(
            base_url, args.conversation, args.memory_hint, args.current_time
        ),
        "serve": lambda: cmd_serve(args.port, args.host, args.no_telegram),
    }

    handler = commands.get(args.command)
    if handler:
        sys.exit(handler())


if __name__ == "__main__":
    main()
