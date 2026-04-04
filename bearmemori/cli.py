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
