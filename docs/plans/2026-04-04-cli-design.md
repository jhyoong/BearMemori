# CLI Design for BearMemori

Date: 2026-04-04

## Purpose

Add a CLI to BearMemori that serves two roles:
1. **Client tool** -- interact with a running BearMemori instance via the REST API
2. **Server management** -- start the server with configurable flags

Primary design constraint: output structured JSON to stdout, making it easy for LLMs to call via tool use / function calling.

## Architecture

Single file: `bearmemori/cli.py` using `argparse` (stdlib). No new dependencies.

HTTP client uses `urllib.request` (stdlib) to call the REST API.

Entry point added via `[project.scripts]` in `pyproject.toml`:
```
bearmemori = "bearmemori.cli:main"
```

Existing `__main__.py` stays as-is for `python -m bearmemori` usage.

## Global Options

```
bearmemori [--url URL] <command> [args]
```

- `--url` -- server URL (default: `http://localhost:{API_PORT}` from env, fallback `http://localhost:8000`)

## Output Convention

- All client commands print JSON to stdout
- Errors print `{"error": "<message>", "status": <code>}` to stderr
- Connection errors print `{"error": "Cannot connect to server at <url>"}` to stderr
- Exit code 0 on success, 1 on error

## Server Command

### `bearmemori serve`

Starts the full application (API + Telegram + processing loop).

```
bearmemori serve [--port PORT] [--host HOST] [--no-telegram]
```

- `--port` -- override `API_PORT` from settings
- `--host` -- bind address (default: `0.0.0.0`)
- `--no-telegram` -- start without the Telegram bot

Reuses existing `__main__.py` logic.

## Client Commands

| Command | API Endpoint | Key Arguments |
|---|---|---|
| `bearmemori health` | `GET /health` | none |
| `bearmemori search <query>` | `GET /memory/search` | `--category`, `--top-k` |
| `bearmemori list` | `GET /memory/list` | `--category`, `--needs-review`, `--offset`, `--limit` |
| `bearmemori get <id>` | `GET /memory/{id}` | none |
| `bearmemori create` | `POST /memory/create` | `--title`, `--content`, `--category`, `--tags`, `--importance` |
| `bearmemori delete <id>` | `DELETE /memory/{id}` | none |
| `bearmemori update <id>` | `PUT /memory/{id}` | `--title`, `--content`, `--category`, `--tags`, `--importance`, `--needs-review` |
| `bearmemori briefing` | `GET /memory/briefing` | `--event-days` |
| `bearmemori events` | `GET /memory/events/upcoming` | `--days`, `--start`, `--end` |
| `bearmemori triage` | `POST /memory/triage` | `--conversation` (JSON string), `--memory-hint`, `--current-time` |

## Dependencies

None new. All stdlib: `argparse`, `urllib.request`, `json`.

## Testing

- `tests/test_cli.py` -- test argparse parsing and HTTP client functions by mocking `urllib.request.urlopen`
- `serve` command delegates to existing logic, no unit tests needed for it

## Files Changed

- `bearmemori/cli.py` -- new file, all CLI logic
- `pyproject.toml` -- add `[project.scripts]` entry
