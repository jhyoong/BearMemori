import json
from io import StringIO
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError

import pytest

from bearmemori.cli import api_request, build_parser, get_base_url


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
                "http://localhost:8100",
                "POST",
                "/memory/create",
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
                "http://localhost:8100",
                "GET",
                "/memory/search",
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

                code = cmd_list(
                    "http://localhost:8100", category=None, needs_review=None, offset=0, limit=50
                )
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


class TestCreateCommand:
    def test_parse_create(self):
        parser = build_parser()
        args = parser.parse_args(
            [
                "create",
                "--title",
                "Dentist",
                "--content",
                "At 3pm",
                "--category",
                "event",
                "--tags",
                "health,appointment",
                "--importance",
                "7",
            ]
        )
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
                    title="Dentist",
                    content="At 3pm",
                    category="event",
                    tags="health,appointment",
                    importance=7,
                )
            mock_req.assert_called_once_with(
                "http://localhost:8100",
                "POST",
                "/memory/create",
                body={
                    "title": "Dentist",
                    "content": "At 3pm",
                    "category": "event",
                    "tags": ["health", "appointment"],
                    "importance": 7,
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
                    "http://localhost:8100",
                    "mem_abc",
                    title="New title",
                    content=None,
                    category=None,
                    tags=None,
                    importance=None,
                    needs_review=None,
                )
            mock_req.assert_called_once_with(
                "http://localhost:8100",
                "PUT",
                "/memory/mem_abc",
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
                    memory_hint=None,
                    current_time=None,
                )
            assert code == 0
            body = mock_req.call_args.kwargs["body"]
            assert body["conversation"] == [{"role": "user", "content": "test"}]


class TestMain:
    def test_main_dispatches_health(self):
        with patch("bearmemori.cli.api_request", return_value={"status": "ok"}):
            with patch("sys.argv", ["bearmemori", "health"]):
                with patch("sys.stdout", StringIO()):
                    with pytest.raises(SystemExit) as exc_info:
                        from bearmemori.cli import main

                        main()
                    assert exc_info.value.code == 0


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
        args = parser.parse_args(
            ["serve", "--port", "9000", "--host", "127.0.0.1", "--no-telegram"]
        )
        assert args.port == 9000
        assert args.host == "127.0.0.1"
        assert args.no_telegram is True
