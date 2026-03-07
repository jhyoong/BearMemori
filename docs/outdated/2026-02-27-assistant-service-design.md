# BearMemori Assistant Service Design

## Overview

A new service (`assistant/assistant_svc/`) in the BearMemori monorepo. An LLM-powered
conversational assistant that uses OpenAI tool-calling to help users interact with their
memories, tasks, reminders, and events.

Key decisions:
- Communicates with BearMemori via the Core API (HTTP), both reads and writes
- Uses OpenAI API (same as llm_worker) with function/tool-calling
- Interface layer is abstracted (Telegram first, other channels later)
- Reactive conversation + daily morning digest
- Chat history and session summaries stored in Redis (ephemeral, accepted risk)

## Service Structure

```
assistant/
  assistant_svc/
    __init__.py
    main.py              # Entry point, wires up components
    agent.py             # Core agent: builds prompts, calls OpenAI, handles tool calls
    briefing.py          # Builds the pre-loaded context briefing
    context.py           # Chat history management, summarize-and-truncate
    tools/
      __init__.py        # Tool registry
      memories.py        # search_memories, get_memory
      tasks.py           # list_tasks, create_task
      reminders.py       # list_reminders, create_reminder
      events.py          # list_events
    interfaces/
      __init__.py
      base.py            # Abstract interface class
      telegram.py        # Telegram bot implementation
    digest.py            # Daily briefing scheduler
    core_client.py       # HTTP client for Core API
    config.py            # Service config (extends shared_lib.config)
  pyproject.toml
  Dockerfile
```

## Agent Loop

When a user sends a message:

1. Load chat history from Redis for this user.
2. Build the briefing (upcoming tasks/reminders, recent memories, last session summary).
3. Construct the message list:
   `[system prompt + briefing] + [summary of old messages] + [recent messages] + [new user message]`
4. Call OpenAI with tool definitions.
5. If the model returns tool calls, execute them against Core API, append results,
   call OpenAI again (loop until the model returns a text response).
6. Send the text response back to the user via the interface layer.
7. Save updated chat history to Redis.

## Context Window Management

### Token Budget Allocation

Given a model with context window W tokens:

| Segment               | Budget          | Contents                                        |
|-----------------------|-----------------|-------------------------------------------------|
| System prompt + tools | Fixed (~2-3k)   | Persona, instructions, tool schemas             |
| Briefing              | Capped (~4-6k)  | Pre-loaded user context (see below)             |
| Chat history          | Remainder       | Conversation messages + tool call results       |
| Response reserve      | Fixed (~4k)     | Space for the model's reply                     |

Chat history gets the largest share. As it grows, the summarize-and-truncate mechanism
kicks in.

### Briefing (Pre-loaded Context)

On each user message, the assistant builds a briefing by fetching from the Core API:

1. **Upcoming tasks and reminders** -- tasks due within 7 days + reminders firing within
   48 hours. Sorted by urgency (soonest first). Capped at ~20 items.
2. **Recent memories** -- memories created/updated in the last 7 days. Sorted by recency.
   Capped at ~15 items.
3. **Previous session summary** -- stored summary of the last conversation session.

Each item is formatted as a compact one-liner, e.g.:
`[TASK due:2026-02-28] "Buy groceries" (linked to memory #42)`

If the briefing exceeds its budget cap, items are trimmed from the bottom of each
category (least urgent tasks, oldest memories).

### Chat History: Summarize-and-Truncate

1. **Keep recent messages verbatim** -- the last N message pairs (user + assistant).
2. **Threshold trigger** -- when total chat history tokens exceed ~70% of the chat budget,
   trigger summarization.
3. **Summarize older messages** -- take the oldest half of the history, send to the LLM
   with a "summarize this conversation so far" prompt, replace those messages with the
   summary.
4. **Result** -- context always contains:
   `[summary of older conversation] + [recent messages verbatim]`
5. **Session end** -- when the conversation goes idle (30-minute timeout), summarize the
   entire session and store it in Redis for the next session's briefing.

## Tool Definitions (Initial Set)

| Tool               | Type  | Description                                  |
|--------------------|-------|----------------------------------------------|
| `search_memories`  | read  | FTS5 search, returns top 10 results          |
| `get_memory`       | read  | Full memory details with tags                |
| `list_tasks`       | read  | Filtered task list (state, due date range)   |
| `list_reminders`   | read  | Filtered reminders (upcoming, fired)         |
| `list_events`      | read  | Filtered events (status, date range)         |
| `create_task`      | write | Create task linked to a memory               |
| `create_reminder`  | write | Create reminder with fire_at                 |

For write operations, the assistant is instructed in the system prompt to always confirm
with the user before executing. The confirmation happens in the conversation (the LLM
asks "Should I create this?", user says yes, then the tool is called).

## Digest Scheduler

A background task that runs once daily at a user-configured time (default: 8:00 AM in
user's timezone, fetched from Core API `/settings`):

1. Fetch tasks due today/tomorrow.
2. Fetch reminders firing in the next 24 hours.
3. Fetch memories created in the last 24 hours.
4. Format into a short briefing message.
5. Send via the interface layer.

## Storage (Redis)

| Key                                      | Contents                  | TTL     |
|------------------------------------------|---------------------------|---------|
| `assistant:chat:{user_id}`               | JSON list of chat messages | 24 hours |
| `assistant:summary:{user_id}`            | Last session summary       | 7 days  |
| `assistant:digest_sent:{user_id}:{date}` | Flag to prevent duplicates | 48 hours |

## Interface Layer

Abstract base class with:
- `send_message(user_id, text)` -- send a message to the user
- `on_message(user_id, text) -> None` -- callback when user sends a message

Telegram implementation uses python-telegram-bot with its own bot token, separate from
the BearMemori gateway bot.

## Adding New Tools

To add a new capability:

1. Create a new file in `assistant_svc/tools/` (or add to an existing one).
2. Define the function that calls the Core API (or any external API).
3. Define the OpenAI tool schema (name, description, parameters).
4. Register the tool in `tools/__init__.py`.

The agent picks it up automatically via the tool registry.
