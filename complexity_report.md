# BearMemori Queue System Report — `v0.1.1` Branch

This report covers every layer of the queue system in [BearMemori](https://github.com/jhyoong/BearMemori/tree/v0.1.1) — from how messages enter, through locking, LLM processing, picture tagging, intent routing, and the feedback loop back to the user. The central goal is to assess overall complexity.

***

## System Architecture at a Glance

The queue system is built on **Redis Streams** with two consumer groups and six named streams :

| Stream | Purpose | Consumer Group |
|---|---|---|
| `llm:intent` | Classify user text messages | `llm-worker-group` |
| `llm:image_tag` | Tag and describe photos | `llm-worker-group` |
| `llm:followup` | Re-process ambiguous messages | `llm-worker-group` |
| `llm:task_match` | Match memory to existing tasks | `llm-worker-group` |
| `llm:email_extract` | Extract events from email | `llm-worker-group` |
| `notify:telegram` | Send results back to Telegram | `telegram-group` |

Two independent consumer loops run concurrently: `llm-worker-1` (in `llm_worker/worker/consumer.py`) processes the five LLM streams, and `telegram-gw-1` (in `telegram/tg_gateway/consumer.py`) consumes the notification stream .

***

## The Locking System

### How It Works

Before any LLM job is processed, the worker attempts to acquire a **per-user Redis lock** via `SET NX EX` at the key `llm:user_lock:{user_id}` :

```python
result = await redis_client.set(lock_key, "1", nx=True, ex=ttl_seconds)
```

If the lock is held, the message is **not acknowledged** and not processed — it stays in the Pending Entries List (PEL) to be retried on the next loop cycle . If acquired, the job is processed, a result is published to `notify:telegram`, but **the lock is deliberately not released** at that point. The lock remains held until the user interacts with the resulting Telegram keyboard (confirm, reject, or cancel) .

### Complexity Issues in the Lock Design

The lock has a **7-day TTL** as a safety net, described as covering "edge cases where release fails." However, messages are considered **stale after only 5 minutes** and are auto-acked and skipped . This creates a significant asymmetry: if a user never responds to a proposal, their entire queue is frozen for up to 7 days, yet any new messages they send will be enqueued, read by the worker, and then immediately discarded as stale. The 7-day window and the 5-minute stale cutoff operate at different layers with no cross-awareness.

Lock **release is scattered** across multiple different locations in the codebase:
- In `llm_worker/worker/consumer.py` — only on retry failure or lock-not-acquired path 
- In `telegram/tg_gateway/consumer.py` — only for the `search` intent, inside `_handle_intent_result` 
- Presumably in the callback handlers (confirm/reject/cancel buttons) — not shown but referenced throughout the code

This means the lock release responsibility is split across three different services and files, making it very hard to reason about when a user's queue will actually unblock.

### The `is_message_in_pel` Problem

`shared_lib/redis_streams.py` contains `is_message_in_pel`, a function that checks whether a message was read from the PEL by querying `XPENDING` . It handles three distinct Redis client response formats (dict, list/tuple, and unknown fallback), does string-based ID range comparison, and **defaults to `True` (assuming PEL) on any error**. In practice, the main `run_consumer` loop in `llm_worker` always passes `from_pel` explicitly as `True` or `False` — meaning this function is **never actually called in the hot path** . It exists as dead complexity.

***

## Picture Handling

Photos sent by the user are routed to the `llm:image_tag` stream and processed by the `image_tag` handler. Once the LLM produces tags and a description, the worker publishes an `llm_image_tag_result` message to `notify:telegram` . The Telegram consumer then dispatches this with a `tag_suggestion_keyboard` inline keyboard :

```python
elif message_type == "llm_image_tag_result":
    tags_str = ", ".join(tags)
    text = f"Tag suggestions for your image:\nDescription: {description}\nSuggested tags: {tags_str}"
    keyboard = tag_suggestion_keyboard(memory_id)
    await bot.send_message(chat_id=user_id, text=text, reply_markup=keyboard)
```

Images go through the **same locking system** as text messages . The user lock is acquired before the image is tagged and is not released until the user confirms or rejects the tag suggestions. This means a photo and a text message sent in quick succession will be serialized — the text will sit in the PEL until the photo's tags are approved. There is no priority or bypass mechanism for images vs. text.

***

## Intent Classification and Routing

The `llm:intent` stream feeds the most complex part of the system. After the LLM worker processes a message, it publishes an `llm_intent_result` to `notify:telegram`. The Telegram consumer's `_handle_intent_result` function then **routes to six distinct branches** based on the classified intent :

| Intent | Action | Lock Held? | State Set |
|---|---|---|---|
| `reminder` | Send proposal with time keyboard | ✅ Yes | `AWAITING_BUTTON_ACTION` |
| `task` | Send proposal with due date keyboard | ✅ Yes | `AWAITING_BUTTON_ACTION` |
| `search` | Send results with result keyboard | ❌ Released | `USER_QUEUE_COUNT` decremented |
| `general_note` | Send tag suggestions | ✅ Yes | `AWAITING_BUTTON_ACTION` |
| `ambiguous` | Send follow-up question | ✅ Yes | `PENDING_LLM_CONVERSATION` |
| unknown | Send plain text fallback | ❓ Unspecified | None |

Each intent also has sub-logic. For `reminder` and `task`, the handler validates the LLM's extracted datetime string with `_try_parse_datetime`, and depending on whether the parsed time is `None`, in the past, or valid, three different keyboard variants (`reminder_time_keyboard`, `reschedule_keyboard`, or `reminder_proposal_keyboard`) are sent . This means a single `llm_intent_result` can produce one of at least 8 different Telegram messages depending on intent type and datetime validity.

***

## The Feedback Loop

The full roundtrip for a user message looks like this:

1. **User sends text/photo** → Telegram handler publishes job to `llm:intent` or `llm:image_tag`
2. **LLM worker** reads from PEL first, then new messages; acquires user lock; calls handler; publishes result to `notify:telegram`; does **not** ack the user lock release
3. **Telegram consumer** polls `notify:telegram` with a `FLOOD_CONTROL_DELAY_SECONDS` of 1 second between consecutive messages to the same user; dispatches the result with an appropriate keyboard 
4. **User clicks a button** → callback handler fires → processes the confirmation → releases the user lock (in a third code location)
5. **Next queued job** can now be processed from the PEL

### Feedback Loop Complexity Issues

The consumer loop in `llm_worker` runs a **tight round-robin** across all 5 streams :

```python
while True:
    for stream_name in streams:
        # Read PEL (id="0")
        messages = await consume(..., id="0", count=50, block_ms=1000)
        # If empty, read new (id=">")
        if not messages:
            messages = await consume(..., id=">", count=1, block_ms=1000)
        ...
    await asyncio.sleep(0.1)
```

This means in the worst case (all streams empty), the loop makes **10 Redis calls every 1+ second** (2 per stream × 5 streams with 1000ms block each). The `asyncio.sleep(0.1)` at the bottom is largely irrelevant since the blocking calls already dominate. When messages are present, the PEL batch reads up to 50 messages but new messages are read **one at a time** (`count=1`), meaning a burst of 10 incoming messages requires 10 separate loop iterations to consume.

The **`USER_QUEUE_COUNT`** variable in `application.user_data` is decremented in the Telegram consumer for the `search` intent, implying the Telegram gateway tracks queue depth per user in memory . However, there is no visible increment site in the files reviewed — the counter management is asymmetric and split across the intent routing logic.

***

## Retry System

The worker has two distinct retry modes classified by `_classify_failure_type` :

- **`INVALID_RESPONSE`** (bad JSON, missing fields): Exponential backoff with `asyncio.sleep(backoff)` inline in the consumer loop, blocking all other stream processing during the sleep. Max retries exceeded → job marked `failed`, user notified, lock released.
- **`UNAVAILABLE`** (timeouts, connection errors): No backoff sleep; message stays un-acked in the PEL; retried on every loop cycle for up to **14 days**. On first occurrence, user is notified. On 14-day expiry, job fails.

The `asyncio.sleep(backoff)` for `INVALID_RESPONSE` retries is placed **inside the message loop**, meaning the entire consumer — across all 5 streams — stalls for the backoff duration of a single failing job.

***

## A Notable Bug

In `telegram/tg_gateway/consumer.py`, inside the `search` intent branch of `_handle_intent_result`, after releasing the user lock the code calls `await redis_client.aclose()` :

```python
if redis_client:
    try:
        await release_user_lock(redis_client, str(user_id))
        await redis_client.aclose()  # closes the shared connection
    except Exception:
        logger.exception(...)
```

This **closes the shared Redis client** that is stored in `application.bot_data["redis"]` and used by the entire Telegram gateway process. Any subsequent Redis operations — including the notification consumer loop itself — will fail until a reconnect occurs (which is not coded here). This is a concurrency-safety issue caused by the lock release logic being added to the notification consumer rather than a dedicated connection scope.

***

## Overall Complexity Assessment

The queue system is **significantly over-engineered** for its current scale (a personal assistant bot with a small `allowed_ids` list). Key sources of unnecessary complexity are:

- **Two separate consumer files** (`llm_worker/worker/consumer.py` and `telegram/tg_gateway/consumer.py`) with mirrored but inconsistent stream/lock management logic
- **Lock release responsibility scattered** across three separate files and services with no central ownership
- **`is_message_in_pel`** is a dead code path that adds ~60 lines of multi-format handling for a function the hot path never calls
- **Round-robin polling** with dual PEL+new reads per stream creates 10 Redis calls per cycle even when idle
- **Inline backoff sleep** inside the consumer loop stalls all stream processing for a single job's retry delay
- **`USER_QUEUE_COUNT`** is decremented in one place but its increment site is not in the reviewed files, suggesting fragmented queue-depth bookkeeping
- **The 7-day lock TTL vs 5-minute stale cutoff asymmetry** can permanently block a user's queue while silently discarding all their new messages