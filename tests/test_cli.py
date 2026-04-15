import argparse
from io import StringIO
from unittest.mock import patch

import pytest

from bearmemori.cli import build_parser, get_base_url


class TestGetBaseUrl:
    def test_default_url(self):
        with patch.dict("os.environ", {}, clear=True):
            assert get_base_url(None) == "http://localhost:8100"

    def test_override_url(self):
        assert get_base_url("http://example.com:9000") == "http://example.com:9000"

    def test_env_api_port(self):
        with patch.dict("os.environ", {"API_PORT": "9999"}):
            assert get_base_url(None) == "http://localhost:9999"


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

    def test_only_serve_and_health_remain(self):
        parser = build_parser()
        # health works
        args = parser.parse_args(["health"])
        assert args.command == "health"
        # serve works
        args = parser.parse_args(["serve"])
        assert args.command == "serve"
        # old commands are gone
        with pytest.raises(SystemExit):
            parser.parse_args(["search", "query"])


class TestHealthCommand:
    def test_health_success(self):
        import json

        import urllib.request
        from unittest.mock import MagicMock

        mock_response = MagicMock()
        mock_response.read.return_value = b'{"status": "ok"}'
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response):
            captured = StringIO()
            with patch("sys.stdout", captured):
                from bearmemori.cli import cmd_health

                code = cmd_health("http://localhost:8100")
        assert json.loads(captured.getvalue()) == {"status": "ok"}
        assert code == 0

    def test_health_connection_error(self):
        from urllib.error import URLError

        with patch("urllib.request.urlopen", side_effect=URLError("Connection refused")):
            from bearmemori.cli import cmd_health

            code = cmd_health("http://localhost:8100")
            assert code == 1


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


class TestMain:
    def test_main_dispatches_health(self):
        import json
        from unittest.mock import MagicMock

        mock_response = MagicMock()
        mock_response.read.return_value = b'{"status": "ok"}'
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response):
            with patch("sys.argv", ["bearmemori", "health"]):
                with patch("sys.stdout", StringIO()):
                    with pytest.raises(SystemExit) as exc_info:
                        from bearmemori.cli import main

                        main()
                    assert exc_info.value.code == 0
