import argparse
import json
import os
import sys
import urllib.error
import urllib.request
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

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    base_url = get_base_url(args.url)

    commands = {
        "health": lambda: cmd_health(base_url),
        "get": lambda: cmd_get(base_url, args.id),
        "briefing": lambda: cmd_briefing(base_url, args.event_days),
    }

    handler = commands.get(args.command)
    if handler:
        sys.exit(handler())


if __name__ == "__main__":
    main()
