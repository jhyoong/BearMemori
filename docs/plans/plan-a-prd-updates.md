# Plan A: PRD Updates

## Context

The user tested BearMemori and found that "save all text immediately as memory + show buttons" creates unnecessary friction. The decision is to move to a queue-first text message flow with LLM classification. The PRD (`docs/Life_Organiser_PRD_v1.2.md`) must be updated to reflect these decisions.

## Background Decisions

1. All text messages go through the queue first (consistent flow regardless of LLM availability)
2. Context-aware acknowledgment: "Processing..." if the queue is empty and idle; "Added to queue" if the queue already has items or is currently processing another message
3. Search queries are NOT saved as memories
4. Follow-up context tracking with configurable timeout (e.g., 5 minutes)
5. Tag suggestions for general text notes
6. Stale messages: use original message timestamp for date calculations; notify user if resolved date is in the past
7. Flood control: deliver results one at a time with a short delay
8. Queue retention: up to 2 weeks

---

## Changes Required

### 1. Rewrite Section 5.2 — Text Message Capture Behaviour

**Current text:** "Text messages: Immediately stored as a confirmed Memory. No confirmation required."

**Replace with:**
"Text messages: Queued for LLM classification. User receives a context-aware acknowledgment immediately: 'Processing...' if the queue is empty and idle, or 'Added to queue' if the queue already has items or is currently processing another message. Based on classification:
- **reminder** — saved as confirmed memory + reminder proposed for user confirmation
- **task** — saved as confirmed memory + task proposed for user confirmation
- **search** — NOT saved as a memory; search results returned directly
- **general_note** — saved as confirmed memory with LLM-suggested tags + standard action buttons
- **ambiguous** — saved as confirmed memory; LLM asks a follow-up question; queue paused for this user until resolved or timed out"

### 2. Update Principle 1 — Capture-first for text

**Current text:** "All inbound text messages are stored immediately as Memories."

**Replace with:**
"All inbound text messages are queued for LLM classification. Non-search messages are stored as Memories after classification. Search queries are processed without storage."

### 3. Update Principle 4 — Deterministic without LLM

**Current text:** Capture continues without LLM.

**Replace with:**
"Text messages remain in the queue until the LLM is available. The queue persists across restarts. Messages expire after 14 days. The user is notified of expired messages."

### 4. Update Section 5.3 — Inline Actions

**Current text:** Buttons shown on every captured memory.

**Replace with:**
"Buttons are context-dependent based on LLM classification:
- **General notes** get standard buttons (Task, Remind, Tag, Pin, Delete) + tag suggestion buttons (Confirm Tags, Edit Tags)
- **Reminder proposals** get [Confirm] [Edit time] [Just a note]
- **Task proposals** get [Confirm] [Edit] [Just a note]
- **Ambiguous** gets the follow-up question text; next user reply is treated as the answer"

### 5. Add to Section 5.1 or 5.3 — Conversation Context Tracking (new requirement)

Add a new subsection:
"When the LLM asks a follow-up question (ambiguous classification), the system tracks multi-turn conversation context:
1. Context stored in per-user state with key `PENDING_LLM_CONTEXT`
2. Includes: original message text, LLM's question, timestamp, memory_id (if created)
3. User's next text message is treated as the answer to the follow-up, not a new message
4. Both original message and answer are sent to the LLM for re-classification
5. Context expires after a configurable timeout (default: 5 minutes). On expiry, the memory is kept as-is and the queue resumes."

### 6. Add to Section 5.7.1 — New LLM Trigger Point

Add `on_text_receive` as a new LLM trigger point:
"When a text message is received, it is queued for LLM intent classification. The LLM classifies the message into one of: reminder, task, search, general_note, ambiguous. For general_note, the LLM also suggests tags."

### 7. Rewrite Section 5.7.2 — LLM Queue & Retry

**Current:** Max 5 retries with exponential backoff.

**Replace with:**
"Time-based expiry (14 days from original queue time). Retry strategy:
- Attempts 1-5: exponential backoff (1s, 2s, 4s, 8s, 16s)
- Attempts 6+: fixed 30-minute intervals
- Hard expiry: 14 days from original queue time
- On expiry: mark job as expired, notify user

One-at-a-time processing per user. The queue processes one message per user at a time. This ensures:
- Follow-up replies are always associated with the correct conversation
- Results appear in natural sequential order in the Telegram chat
- No interleaving of LLM results

Flood control: when processing a backlog after LLM recovery, add a configurable delay (e.g., 5-10 seconds) between delivering results for consecutive messages."

### 8. Update Section 7 — Failure Modes

Add a failure mode for "LLM unavailable during text classification":
"When the LLM is unavailable, text messages remain in the per-user queue. The queue retries with the backoff strategy defined in 5.7.2. Messages expire after 14 days. The user is notified of expired messages."

### 9. Add to Section 5.7 or 7 — Stale Message Handling

"When the LLM processes a queued message, the original message timestamp is included in the payload. The LLM uses this to resolve relative time references ('tomorrow', 'in 5 minutes', 'next week'). If the resolved datetime is in the past:
1. System notifies user with the original date and the resolved date
2. Offers [Reschedule] [Dismiss]
3. If rescheduled, user picks a new date/time"

---

## Files to Edit

- `docs/Life_Organiser_PRD_v1.2.md` — all changes above

## Dependencies

- None. This is a document-only plan.
- Should be completed BEFORE the BDD and implementation plans, as they reference the PRD.
