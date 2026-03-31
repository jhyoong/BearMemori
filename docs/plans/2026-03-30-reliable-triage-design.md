# Reliable Triage LLM Flow Design

Date: 2026-03-30

## Problem

The triage LLM flow is inconsistent. Two independent LLM calls — the telebearAI chatbot (which decides `intent_state`) and BearMemori's triage LLM (which decides `should_save`) — sometimes disagree. The chatbot tells the user it will save a memory, but the triage LLM decides not to. This happens unpredictably at both layers.

Contributing factors:
- The reasoning model (Qwen3.5) can overthink and talk itself out of saving
- The triage prompt's "Be selective" framing biases toward rejection
- Fixed 10-message conversation window can include irrelevant context from earlier topics
- Draft validation failures silently return `should_save=false`

## Approach: Confidence Override + Conversation Windowing

Keep the two-stage architecture (chatbot decides intent, triage service decides save) but make them more consistent through three mechanisms:

1. High-confidence hints from the chatbot bypass the should_save decision
2. Smart conversation windowing reduces context noise
3. Prompt hardening shifts the triage LLM's default toward saving

## Design

### 1. Confidence Override (BearMemori)

**Where:** `bearmemori/core/triage.py` — `run_triage()`

When the `/memory/triage` endpoint receives a `memory_hint` with `confidence: "high"`:
- Use an extraction-only prompt that assumes saving and only asks for structured fields (category, title, content, importance, event_fields)
- No `should_save` field in this prompt — the answer is always "yes"
- The response is just the memory fields

When confidence is "medium", "low", or absent:
- Use the current full triage prompt (which includes the should_save decision)

**Extraction-only prompt:**

```
You are a memory extraction agent. The following conversation contains
information that should be saved as a long-term memory.

Current date and time: {current_time}
When the user mentions relative times (e.g. "in 10 minutes", "tomorrow",
"next week"), use the current date and time above to compute the absolute
ISO 8601 datetime for event_fields.

Extract the memory details from the conversation. You MUST respond with a
single valid JSON object and nothing else.

Categories:
- "profile": Stable facts about the user (preferences, identity, relationships)
- "general": Non-time-bound useful information (prices, recommendations, facts)
- "event": Time-bound commitments, reminders, appointments
- "location": Places, addresses, venues the user mentions
- "task": Action items, to-dos
- "reminder": Triggered notifications with scheduling

Importance (1-10 integer):
- 1-3: Low importance (trivial facts, casual mentions)
- 4-6: Medium importance (useful information, general preferences)
- 7-8: High importance (key personal facts, significant events, strong preferences)
- 9-10: Critical importance (core identity, health/safety, major life events)

Respond with:
{"category": "<category>", "title": "<short title>",
"content": "<key information>", "tags": ["tag1", "tag2"],
"importance": <1-10>, "event_fields": null}

For events/tasks/reminders, set event_fields to:
{"datetime": "ISO 8601", "status": "pending", "recurrence": null}

The conversation may contain information spread across multiple messages.
Synthesize the full conversation to extract the complete memory, not just
the last message.
```

**Fallback:** If the extraction-only prompt returns invalid JSON or fails draft validation, retry once with the full triage prompt before giving up.

### 2. Smart Conversation Windowing (telebearAI)

**Where:** `bot/main_agent.py` — `_trigger_memory_triage()`, `bot/context_manager.py`

Instead of always sending the last 10 messages:

1. Track the index of the last message that triggered a triage call (last `intent_state="resolved"` message) in `ContextManager`, keyed by `chat_id`.
2. When a new triage is triggered, send only the messages since the last triage trigger, capped at 10 messages.
3. If there's no previous trigger (first triage in the conversation), fall back to the last 10 messages.
4. The index resets when the conversation history is cleared.

**Example:**

```
Message 1:  "Trip to Tokyo next week"     -> resolved, triage (msgs 1)
Message 2:  "What hotel?"                 -> pending
Message 3:  "The Park Hyatt"              -> resolved, triage (msgs 2-3 only)
```

Without windowing, triage for message 3 sees messages 1-3, including the already-triaged Tokyo trip. With windowing, it sees only messages 2-3.

This is a telebearAI-side change only. BearMemori's `/memory/triage` endpoint receives whatever conversation array is sent.

### 3. Triage Prompt Hardening (BearMemori)

**Where:** `bearmemori/core/triage.py` — `_TRIAGE_SYSTEM_TEMPLATE`

Changes to the full triage prompt (the should_save variant):

**Add "when in doubt, save" guidance:**
```
When in doubt, lean toward saving. It is better to save something
the user can dismiss than to lose information they wanted kept.
```

**Add multi-turn synthesis guidance:**
```
The conversation may contain information spread across multiple messages.
Synthesize the full conversation to extract the complete memory, not just
the last message.
```

**Add mixed-topic guidance:**
```
If the conversation covers multiple unrelated topics, focus on the most
recent topic that contains memory-worthy information.
```

**Replace "Be selective" with neutral framing:**

Remove:
```
Be selective. Only save genuinely useful, specific information. Do not save:
```

Replace with:
```
Save specific, actionable information. Skip only:
```

Keep the existing skip list (greetings, questions without answers, trivial mentions).

### 4. Error Handling and Observability (BearMemori)

**Where:** `bearmemori/core/triage.py`, `bearmemori/api/routes.py`, `bearmemori/api/schemas.py`

**Retry on extraction failure:**
In the confidence override path, if JSON parsing or draft validation fails, retry once with the full triage prompt before returning `should_save=false`.

**Log raw LLM response on failure:**
```python
logger.warning("Triage produced invalid draft: %s | raw: %s", e, raw_content[:500])
```

**Add reason field to API response:**
```json
{"should_save": false, "reason": "llm_decided_no"}
{"should_save": false, "reason": "extraction_failed"}
{"should_save": false, "reason": "validation_failed"}
```

Update `TriageResponse` schema to include the optional `reason` field. telebearAI logs this for debugging but doesn't need to act on it differently.

## Files Changed

### BearMemori
- `bearmemori/core/triage.py`: Extraction-only prompt, confidence override logic, retry-on-failure, improved logging, prompt hardening
- `bearmemori/api/routes.py`: Add `reason` field to triage response
- `bearmemori/api/schemas.py`: Update `TriageResponse` schema

### telebearAI
- `bot/main_agent.py`: Smart windowing in `_trigger_memory_triage()`
- `bot/context_manager.py`: Track last triage trigger index per `chat_id`

### Unchanged
- Event bus, storage, Telegram interface, follow-up system, scheduler, queue
- telebearAI chatbot system prompt (already handles intent_state and memory_hint correctly)

## Testing

- Unit tests for the confidence override branching logic
- Unit tests for the smart windowing calculation
- Unit test for the extraction-only prompt producing valid drafts
- Integration test: high-confidence hint skips should_save and extracts correctly
- Integration test: failed extraction falls back to full triage prompt
