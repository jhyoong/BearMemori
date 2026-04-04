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
