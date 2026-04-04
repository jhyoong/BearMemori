# CLI Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a CLI to BearMemori for server management and REST API interaction, with JSON output for LLM tool use.

**Architecture:** Single `bearmemori/cli.py` module using argparse (stdlib) and urllib.request (stdlib). Client commands are thin wrappers around HTTP calls to the REST API. Server command reuses existing `__main__.py` logic.

**Tech Stack:** Python stdlib only (argparse, urllib.request, json)

**Design doc:** `docs/plans/2026-04-04-cli-design.md`

---

### Task 1: HTTP helper and error handling

**Files:**
- Create: `bearmemori/cli.py`
- Test: `tests/test_cli.py`

**Step 1: Write the failing tests**

Create `tests/test_cli.py`:

```python
import json
import sys
from io import StringIO
from unittest.mock import patch, MagicMock
from urllib.error import URLError, HTTPError

from bearmemori.cli import api_request, get_base_url


class TestGetBaseUrl:
    def test_default_url(self):
        with patch.dict("os.environ", {}, clear=True):
            assert get_base_url(None) == "http://localhost:8100"

    def test_override_url(self):
        assert get_base_url("http://example.com:9000") == "http://example.com:9000"

    def test_env_api_port(self):
        with patch.dict("os.environ", {"API_PORT": "9999"}):
            assert get_base_url(None) == "http://localhost:9999"


class TestApiRequest:
    def test_get_success(self):
        mock_response = MagicMock()
        mock_response.read.return_value = b'{"status": "ok"}'
        mock_response.status = 200
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response):
            result = api_request("http://localhost:8100", "GET", "/health")
            assert result == {"status": "ok"}

    def test_post_with_body(self):
        mock_response = MagicMock()
        mock_response.read.return_value = b'{"record_id": "mem_abc"}'
        mock_response.status = 200
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response) as mock_urlopen:
            result = api_request(
                "http://localhost:8100", "POST", "/memory/create",
                body={"title": "Test", "content": "Hello", "category": "note"},
            )
            assert result == {"record_id": "mem_abc"}
            req = mock_urlopen.call_args[0][0]
            assert req.method == "POST"
            assert req.get_header("Content-type") == "application/json"

    def test_connection_error(self):
        with patch("urllib.request.urlopen", side_effect=URLError("Connection refused")):
            result = api_request("http://localhost:8100", "GET", "/health")
            assert result is None

    def test_http_error(self):
        error = HTTPError(
            url="http://localhost:8100/health",
            code=404,
            msg="Not Found",
            hdrs=MagicMock(),
            fp=MagicMock(read=lambda: b'{"detail": "Not found"}'),
        )
        with patch("urllib.request.urlopen", side_effect=error):
            result = api_request("http://localhost:8100", "GET", "/memory/xyz")
            assert result is None
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli.py -v`
Expected: FAIL with `ModuleNotFoundError` or `ImportError`

**Step 3: Write minimal implementation**

Create `bearmemori/cli.py`:

```python
import json
import os
import sys
import urllib.request
import urllib.error
from urllib.parse import urlencode


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
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add bearmemori/cli.py tests/test_cli.py
git commit -m "feat: add CLI HTTP helper and error handling"
```

---

### Task 2: Argparse skeleton with health command

**Files:**
- Modify: `bearmemori/cli.py`
- Modify: `tests/test_cli.py`

**Step 1: Write the failing tests**

Add to `tests/test_cli.py`:

```python
from bearmemori.cli import build_parser


class TestBuildParser:
    def test_health_command(self):
        parser = build_parser()
        args = parser.parse_args(["health"])
        assert args.command == "health"

    def test_global_url_option(self):
        parser = build_parser()
        args = parser.parse_args(["--url", "http://example.com:9000", "health"])
        assert args.url == "http://example.com:9000"
        assert args.command == "health"

    def test_no_command_prints_help(self):
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args([])


class TestHealthCommand:
    def test_health_success(self):
        with patch("bearmemori.cli.api_request", return_value={"status": "ok"}):
            captured = StringIO()
            with patch("sys.stdout", captured):
                from bearmemori.cli import cmd_health
                code = cmd_health("http://localhost:8100")
            assert json.loads(captured.getvalue()) == {"status": "ok"}
            assert code == 0

    def test_health_connection_error(self):
        with patch("bearmemori.cli.api_request", return_value=None):
            from bearmemori.cli import cmd_health
            code = cmd_health("http://localhost:8100")
            assert code == 1
```

Add `import pytest` to the top of `tests/test_cli.py`.

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli.py::TestBuildParser -v`
Expected: FAIL with `ImportError`

**Step 3: Write minimal implementation**

Add to `bearmemori/cli.py`:

```python
import argparse


def output(data: dict) -> None:
    print(json.dumps(data, indent=2, default=str))


def cmd_health(base_url: str) -> int:
    result = api_request(base_url, "GET", "/health")
    if result is None:
        return 1
    output(result)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bearmemori",
        description="BearMemori CLI -- memory store client and server management",
    )
    parser.add_argument("--url", default=None, help="Server URL (default: http://localhost:8100)")

    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("health", help="Check server health")

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    base_url = get_base_url(args.url)

    commands = {
        "health": lambda: cmd_health(base_url),
    }

    handler = commands.get(args.command)
    if handler:
        sys.exit(handler())


if __name__ == "__main__":
    main()
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add bearmemori/cli.py tests/test_cli.py
git commit -m "feat: add argparse skeleton with health command"
```

---

### Task 3: Simple GET commands (get, briefing)

**Files:**
- Modify: `bearmemori/cli.py`
- Modify: `tests/test_cli.py`

**Step 1: Write the failing tests**

Add to `tests/test_cli.py`:

```python
class TestGetCommand:
    def test_parse_get(self):
        parser = build_parser()
        args = parser.parse_args(["get", "mem_abc123"])
        assert args.command == "get"
        assert args.id == "mem_abc123"

    def test_get_success(self):
        record = {"id": "mem_abc123", "title": "Test", "content": "Hello"}
        with patch("bearmemori.cli.api_request", return_value=record):
            captured = StringIO()
            with patch("sys.stdout", captured):
                from bearmemori.cli import cmd_get
                code = cmd_get("http://localhost:8100", "mem_abc123")
            assert json.loads(captured.getvalue()) == record
            assert code == 0


class TestBriefingCommand:
    def test_parse_briefing(self):
        parser = build_parser()
        args = parser.parse_args(["briefing", "--event-days", "14"])
        assert args.command == "briefing"
        assert args.event_days == 14

    def test_briefing_success(self):
        data = {"due_now": {"count": 0}, "total_memories": 42}
        with patch("bearmemori.cli.api_request", return_value=data):
            captured = StringIO()
            with patch("sys.stdout", captured):
                from bearmemori.cli import cmd_briefing
                code = cmd_briefing("http://localhost:8100", event_days=7)
            assert json.loads(captured.getvalue()) == data
            assert code == 0
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli.py::TestGetCommand tests/test_cli.py::TestBriefingCommand -v`
Expected: FAIL

**Step 3: Write minimal implementation**

Add to `bearmemori/cli.py` -- add command functions:

```python
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
```

Add to `build_parser()`:

```python
    # get
    p_get = subparsers.add_parser("get", help="Get a memory by ID")
    p_get.add_argument("id", help="Memory record ID")

    # briefing
    p_briefing = subparsers.add_parser("briefing", help="Get daily briefing")
    p_briefing.add_argument("--event-days", type=int, default=7, help="Days of upcoming events (default: 7)")
```

Add to `commands` dict in `main()`:

```python
        "get": lambda: cmd_get(base_url, args.id),
        "briefing": lambda: cmd_briefing(base_url, args.event_days),
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add bearmemori/cli.py tests/test_cli.py
git commit -m "feat: add get and briefing CLI commands"
```

---

### Task 4: GET commands with parameters (search, list, events)

**Files:**
- Modify: `bearmemori/cli.py`
- Modify: `tests/test_cli.py`

**Step 1: Write the failing tests**

Add to `tests/test_cli.py`:

```python
class TestSearchCommand:
    def test_parse_search(self):
        parser = build_parser()
        args = parser.parse_args(["search", "dentist", "--category", "event", "--top-k", "10"])
        assert args.command == "search"
        assert args.query == "dentist"
        assert args.category == "event"
        assert args.top_k == 10

    def test_search_success(self):
        data = {"results": [{"id": "mem_1", "document": "Dentist at 3pm"}]}
        with patch("bearmemori.cli.api_request", return_value=data) as mock_req:
            captured = StringIO()
            with patch("sys.stdout", captured):
                from bearmemori.cli import cmd_search
                code = cmd_search("http://localhost:8100", query="dentist", category=None, top_k=5)
            mock_req.assert_called_once_with(
                "http://localhost:8100", "GET", "/memory/search",
                params={"query": "dentist", "top_k": 5},
            )
            assert code == 0


class TestListCommand:
    def test_parse_list(self):
        parser = build_parser()
        args = parser.parse_args(["list", "--category", "note", "--limit", "20"])
        assert args.command == "list"
        assert args.category == "note"
        assert args.limit == 20

    def test_list_success(self):
        data = {"memories": [], "total": 0}
        with patch("bearmemori.cli.api_request", return_value=data):
            captured = StringIO()
            with patch("sys.stdout", captured):
                from bearmemori.cli import cmd_list
                code = cmd_list("http://localhost:8100", category=None, needs_review=None, offset=0, limit=50)
            assert code == 0


class TestEventsCommand:
    def test_parse_events(self):
        parser = build_parser()
        args = parser.parse_args(["events", "--days", "14"])
        assert args.command == "events"
        assert args.days == 14

    def test_parse_events_range(self):
        parser = build_parser()
        args = parser.parse_args(["events", "--start", "2026-04-01", "--end", "2026-04-30"])
        assert args.start == "2026-04-01"
        assert args.end == "2026-04-30"

    def test_events_success(self):
        data = {"events": []}
        with patch("bearmemori.cli.api_request", return_value=data):
            captured = StringIO()
            with patch("sys.stdout", captured):
                from bearmemori.cli import cmd_events
                code = cmd_events("http://localhost:8100", days=7, start=None, end=None)
            assert code == 0
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli.py::TestSearchCommand tests/test_cli.py::TestListCommand tests/test_cli.py::TestEventsCommand -v`
Expected: FAIL

**Step 3: Write minimal implementation**

Add command functions to `bearmemori/cli.py`:

```python
def cmd_search(base_url: str, query: str, category: str | None, top_k: int) -> int:
    params = {"query": query, "top_k": top_k}
    if category:
        params["category"] = category
    result = api_request(base_url, "GET", "/memory/search", params=params)
    if result is None:
        return 1
    output(result)
    return 0


def cmd_list(base_url: str, category: str | None, needs_review: bool | None, offset: int, limit: int) -> int:
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
```

Add to `build_parser()`:

```python
    # search
    p_search = subparsers.add_parser("search", help="Search memories")
    p_search.add_argument("query", help="Search query")
    p_search.add_argument("--category", default=None, help="Filter by category")
    p_search.add_argument("--top-k", type=int, default=5, help="Number of results (default: 5)")

    # list
    p_list = subparsers.add_parser("list", help="List memories")
    p_list.add_argument("--category", default=None, help="Filter by category")
    p_list.add_argument("--needs-review", type=bool, default=None, help="Filter by needs_review")
    p_list.add_argument("--offset", type=int, default=0, help="Pagination offset (default: 0)")
    p_list.add_argument("--limit", type=int, default=50, help="Pagination limit (default: 50)")

    # events
    p_events = subparsers.add_parser("events", help="List upcoming events")
    p_events.add_argument("--days", type=int, default=7, help="Days ahead (default: 7)")
    p_events.add_argument("--start", default=None, help="Range start datetime (ISO format)")
    p_events.add_argument("--end", default=None, help="Range end datetime (ISO format)")
```

Add to `commands` dict in `main()`:

```python
        "search": lambda: cmd_search(base_url, args.query, args.category, args.top_k),
        "list": lambda: cmd_list(base_url, args.category, args.needs_review, args.offset, args.limit),
        "events": lambda: cmd_events(base_url, args.days, args.start, args.end),
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add bearmemori/cli.py tests/test_cli.py
git commit -m "feat: add search, list, and events CLI commands"
```

---

### Task 5: Write commands (create, update, delete, triage)

**Files:**
- Modify: `bearmemori/cli.py`
- Modify: `tests/test_cli.py`

**Step 1: Write the failing tests**

Add to `tests/test_cli.py`:

```python
class TestCreateCommand:
    def test_parse_create(self):
        parser = build_parser()
        args = parser.parse_args([
            "create", "--title", "Dentist", "--content", "At 3pm",
            "--category", "event", "--tags", "health,appointment", "--importance", "7",
        ])
        assert args.command == "create"
        assert args.title == "Dentist"
        assert args.content == "At 3pm"
        assert args.category == "event"
        assert args.tags == "health,appointment"
        assert args.importance == 7

    def test_create_success(self):
        data = {"record_id": "mem_abc", "status": "created"}
        with patch("bearmemori.cli.api_request", return_value=data) as mock_req:
            captured = StringIO()
            with patch("sys.stdout", captured):
                from bearmemori.cli import cmd_create
                code = cmd_create(
                    "http://localhost:8100",
                    title="Dentist", content="At 3pm", category="event",
                    tags="health,appointment", importance=7,
                )
            mock_req.assert_called_once_with(
                "http://localhost:8100", "POST", "/memory/create",
                body={
                    "title": "Dentist", "content": "At 3pm", "category": "event",
                    "tags": ["health", "appointment"], "importance": 7,
                },
            )
            assert code == 0


class TestDeleteCommand:
    def test_parse_delete(self):
        parser = build_parser()
        args = parser.parse_args(["delete", "mem_abc123"])
        assert args.command == "delete"
        assert args.id == "mem_abc123"

    def test_delete_success(self):
        data = {"status": "deleted"}
        with patch("bearmemori.cli.api_request", return_value=data):
            captured = StringIO()
            with patch("sys.stdout", captured):
                from bearmemori.cli import cmd_delete
                code = cmd_delete("http://localhost:8100", "mem_abc123")
            assert code == 0


class TestUpdateCommand:
    def test_parse_update(self):
        parser = build_parser()
        args = parser.parse_args(["update", "mem_abc", "--title", "New title"])
        assert args.command == "update"
        assert args.id == "mem_abc"
        assert args.title == "New title"

    def test_update_success(self):
        data = {"status": "updated"}
        with patch("bearmemori.cli.api_request", return_value=data) as mock_req:
            captured = StringIO()
            with patch("sys.stdout", captured):
                from bearmemori.cli import cmd_update
                code = cmd_update(
                    "http://localhost:8100", "mem_abc",
                    title="New title", content=None, category=None,
                    tags=None, importance=None, needs_review=None,
                )
            mock_req.assert_called_once_with(
                "http://localhost:8100", "PUT", "/memory/mem_abc",
                body={"title": "New title"},
            )
            assert code == 0


class TestTriageCommand:
    def test_parse_triage(self):
        parser = build_parser()
        conv = '[{"role": "user", "content": "Remember my dentist is at 3pm"}]'
        args = parser.parse_args(["triage", "--conversation", conv])
        assert args.command == "triage"
        assert args.conversation == conv

    def test_triage_success(self):
        data = {"should_save": True, "pending_id": "p_123"}
        with patch("bearmemori.cli.api_request", return_value=data) as mock_req:
            captured = StringIO()
            with patch("sys.stdout", captured):
                from bearmemori.cli import cmd_triage
                code = cmd_triage(
                    "http://localhost:8100",
                    conversation='[{"role": "user", "content": "test"}]',
                    memory_hint=None, current_time=None,
                )
            assert code == 0
            body = mock_req.call_args.kwargs["body"]
            assert body["conversation"] == [{"role": "user", "content": "test"}]
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli.py::TestCreateCommand tests/test_cli.py::TestDeleteCommand tests/test_cli.py::TestUpdateCommand tests/test_cli.py::TestTriageCommand -v`
Expected: FAIL

**Step 3: Write minimal implementation**

Add command functions to `bearmemori/cli.py`:

```python
def cmd_create(
    base_url: str, title: str, content: str, category: str,
    tags: str | None, importance: int,
) -> int:
    body: dict = {
        "title": title, "content": content, "category": category,
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
    base_url: str, record_id: str, title: str | None, content: str | None,
    category: str | None, tags: str | None, importance: int | None,
    needs_review: bool | None,
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
    if not body:
        print(json.dumps({"error": "No updates provided"}), file=sys.stderr)
        return 1
    result = api_request(base_url, "PUT", f"/memory/{record_id}", body=body)
    if result is None:
        return 1
    output(result)
    return 0


def cmd_triage(
    base_url: str, conversation: str,
    memory_hint: str | None, current_time: str | None,
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
```

Add to `build_parser()`:

```python
    # create
    p_create = subparsers.add_parser("create", help="Create a memory")
    p_create.add_argument("--title", required=True, help="Memory title")
    p_create.add_argument("--content", required=True, help="Memory content")
    p_create.add_argument("--category", required=True, help="Memory category")
    p_create.add_argument("--tags", default=None, help="Comma-separated tags")
    p_create.add_argument("--importance", type=int, default=5, help="Importance 1-10 (default: 5)")

    # delete
    p_delete = subparsers.add_parser("delete", help="Delete a memory")
    p_delete.add_argument("id", help="Memory record ID")

    # update
    p_update = subparsers.add_parser("update", help="Update a memory")
    p_update.add_argument("id", help="Memory record ID")
    p_update.add_argument("--title", default=None, help="New title")
    p_update.add_argument("--content", default=None, help="New content")
    p_update.add_argument("--category", default=None, help="New category")
    p_update.add_argument("--tags", default=None, help="New comma-separated tags")
    p_update.add_argument("--importance", type=int, default=None, help="New importance 1-10")
    p_update.add_argument("--needs-review", type=bool, default=None, help="Set needs_review flag")

    # triage
    p_triage = subparsers.add_parser("triage", help="Run triage on a conversation")
    p_triage.add_argument("--conversation", required=True, help="Conversation JSON array")
    p_triage.add_argument("--memory-hint", default=None, help="Memory hint JSON object")
    p_triage.add_argument("--current-time", default=None, help="Current time (ISO format)")
```

Add to `commands` dict in `main()`:

```python
        "create": lambda: cmd_create(base_url, args.title, args.content, args.category, args.tags, args.importance),
        "delete": lambda: cmd_delete(base_url, args.id),
        "update": lambda: cmd_update(base_url, args.id, args.title, args.content, args.category, args.tags, args.importance, args.needs_review),
        "triage": lambda: cmd_triage(base_url, args.conversation, args.memory_hint, args.current_time),
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add bearmemori/cli.py tests/test_cli.py
git commit -m "feat: add create, delete, update, and triage CLI commands"
```

---

### Task 6: Serve command

**Files:**
- Modify: `bearmemori/cli.py`
- Modify: `tests/test_cli.py`

**Step 1: Write the failing test**

Add to `tests/test_cli.py`:

```python
class TestServeCommand:
    def test_parse_serve_defaults(self):
        parser = build_parser()
        args = parser.parse_args(["serve"])
        assert args.command == "serve"
        assert args.port is None
        assert args.host == "0.0.0.0"
        assert args.no_telegram is False

    def test_parse_serve_with_flags(self):
        parser = build_parser()
        args = parser.parse_args(["serve", "--port", "9000", "--host", "127.0.0.1", "--no-telegram"])
        assert args.port == 9000
        assert args.host == "127.0.0.1"
        assert args.no_telegram is True
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli.py::TestServeCommand -v`
Expected: FAIL

**Step 3: Write minimal implementation**

Add to `bearmemori/cli.py`:

```python
def cmd_serve(port: int | None, host: str, no_telegram: bool) -> int:
    import asyncio

    from bearmemori.app import Application, create_application
    from bearmemori.config import Settings
    from bearmemori.events.domain import InputReceived

    import logging
    import uvicorn
    from typing import cast

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    logger = logging.getLogger("bearmemori")

    async def processing_loop(application: Application) -> None:
        logger.info("Processing loop started")
        while True:
            item = await application.queue_manager.get_next()
            try:
                followup_event = InputReceived(
                    input_type=item.input_type,
                    content=item.content,
                    source_chat_id=item.source_chat_id,
                )
                followup_input = application.followup_manager.check_followup(followup_event)
                if followup_input:
                    item.context = followup_input.context
                await application.processor.process_item(item)
            except Exception:
                logger.exception("Error processing item from %s", item.source_chat_id)

    async def run() -> None:
        settings = Settings()
        actual_port = port if port is not None else settings.api_port
        api = create_application(settings)
        application = cast(Application, api.state.application)

        asyncio.create_task(processing_loop(application))
        asyncio.create_task(application.scheduler.run())
        asyncio.create_task(application.cleanup_task.run())

        config = uvicorn.Config(api, host=host, port=actual_port, log_level="info")
        server = uvicorn.Server(config)

        if no_telegram:
            logger.info("BearMemori is running on %s:%d (Telegram disabled)", host, actual_port)
            await server.serve()
        else:
            telegram_app = application.telegram.build()
            async with telegram_app:
                if telegram_app.post_init:
                    await telegram_app.post_init(telegram_app)
                await telegram_app.start()
                await telegram_app.updater.start_polling()
                logger.info("BearMemori is running on %s:%d", host, actual_port)
                try:
                    await server.serve()
                finally:
                    await telegram_app.updater.stop()
                    await telegram_app.stop()

    asyncio.run(run())
    return 0
```

Add to `build_parser()`:

```python
    # serve
    p_serve = subparsers.add_parser("serve", help="Start the BearMemori server")
    p_serve.add_argument("--port", type=int, default=None, help="API port (default: from settings)")
    p_serve.add_argument("--host", default="0.0.0.0", help="Bind address (default: 0.0.0.0)")
    p_serve.add_argument("--no-telegram", action="store_true", help="Start without Telegram bot")
```

Add to `commands` dict in `main()`:

```python
        "serve": lambda: cmd_serve(args.port, args.host, args.no_telegram),
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add bearmemori/cli.py tests/test_cli.py
git commit -m "feat: add serve CLI command"
```

---

### Task 7: Entry point and final wiring

**Files:**
- Modify: `pyproject.toml:1-29`
- Modify: `tests/test_cli.py`

**Step 1: Write the failing test**

Add to `tests/test_cli.py`:

```python
class TestMain:
    def test_main_dispatches_health(self):
        with patch("bearmemori.cli.api_request", return_value={"status": "ok"}):
            with patch("sys.argv", ["bearmemori", "health"]):
                with patch("sys.stdout", StringIO()):
                    with pytest.raises(SystemExit) as exc_info:
                        from bearmemori.cli import main
                        main()
                    assert exc_info.value.code == 0
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli.py::TestMain -v`
Expected: FAIL (or may already pass if wiring is correct from prior tasks)

**Step 3: Add entry point to pyproject.toml**

Add after line 17 (`]` closing dependencies) in `pyproject.toml`:

```toml
[project.scripts]
bearmemori = "bearmemori.cli:main"
```

**Step 4: Reinstall to register the entry point**

Run: `uv sync`

**Step 5: Run full test suite**

Run: `uv run pytest tests/test_cli.py -v`
Expected: ALL PASS

Run: `uv run pytest -v`
Expected: ALL PASS (no regressions)

**Step 6: Run linting**

Run: `uv run ruff check bearmemori/cli.py tests/test_cli.py`
Run: `uv run ruff format bearmemori/cli.py tests/test_cli.py`

Fix any issues.

**Step 7: Commit**

```bash
git add pyproject.toml bearmemori/cli.py tests/test_cli.py
git commit -m "feat: add CLI entry point to pyproject.toml"
```

---

### Task 8: Smoke test the CLI

**Not a code task.** Manually verify the CLI works end-to-end:

```bash
# Check help
bearmemori --help
bearmemori health --help
bearmemori search --help

# If server is running:
bearmemori health
bearmemori briefing
bearmemori list --limit 5

# If server is not running (should show connection error JSON on stderr):
bearmemori health
```

Verify:
- JSON output on stdout
- Error JSON on stderr
- Exit code 0 on success, 1 on error
- `--help` shows all commands and options
