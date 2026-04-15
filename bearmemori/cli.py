import argparse
import json
import os
import sys
import urllib.error
import urllib.request


def get_base_url(url_override: str | None) -> str:
    if url_override:
        return url_override
    port = os.environ.get("API_PORT", "8100")
    return f"http://localhost:{port}"


def cmd_health(base_url: str) -> int:
    url = f"{base_url}/health"
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req) as response:
            result = json.loads(response.read())
        print(json.dumps(result, indent=2, default=str))
        return 0
    except urllib.error.URLError:
        print(
            json.dumps({"error": f"Cannot connect to server at {base_url}"}),
            file=sys.stderr,
        )
        return 1


def cmd_serve(port: int | None, host: str, no_telegram: bool) -> int:
    import asyncio

    from bearmemori.__main__ import run_server

    asyncio.run(run_server(port=port, host=host, no_telegram=no_telegram))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bearmemori",
        description="BearMemori server management",
    )
    parser.add_argument("--url", default=None, help="Server URL (default: http://localhost:8100)")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("health", help="Check server health")

    p_serve = subparsers.add_parser("serve", help="Start the BearMemori server")
    p_serve.add_argument("--port", type=int, default=None)
    p_serve.add_argument("--host", default="0.0.0.0")
    p_serve.add_argument("--no-telegram", action="store_true")

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    base_url = get_base_url(args.url)

    if args.command == "health":
        sys.exit(cmd_health(base_url))
    elif args.command == "serve":
        sys.exit(cmd_serve(args.port, args.host, args.no_telegram))


if __name__ == "__main__":
    main()
