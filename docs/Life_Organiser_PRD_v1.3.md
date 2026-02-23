# Life Organiser — Personal Recall, Reminder & Knowledge Bot

**Product Requirements Document**
Version 1.3 | February 2026

---

## Changelog (v1.2 → v1.3)

- **Queue-first text message flow:** Text messages are now queued for LLM classification before storage. User receives immediate acknowledgment ("Processing..." or "Added to queue"). Based on classification: reminder/task are saved + proposed for confirmation, search returns results without storage, general_note is saved with LLM-suggested tags, and ambiguous triggers a follow-up question with queue pause.
- **Conversation context tracking:** Added `PENDING_LLM_CONTEXT` per-user state for tracking multi-turn conversations when the LLM asks follow-up questions.
- **New LLM trigger point:** Added `on_text_receive` for text message intent classification.
- **Updated LLM queue & retry:** Changed from max 5 retries to time-based expiry (14 days). Attempts 1-5 use exponential backoff (1s, 2s, 4s, 8s, 16s); attempts 6+ use fixed 30-minute intervals. One-at-a-time processing per user ensures correct conversation ordering. Added flood control for backlog processing.
- **Stale message handling:** When LLM resolves relative time references ("tomorrow", "in 5 minutes") that result in past datetime, system notifies user with options to reschedule or dismiss.
- **Updated failure modes:** Added new failure mode for "LLM unavailable during text classification".
- **Updated principles:** Updated capture-first principle and deterministic features principle to reflect queue-first behavior.

---

## 1. Purpose & North Star

### 1.1 Primary Goal

Enable a single place to capture, organise, and recall personal knowledge — with reliable reminders and provenance-backed answers. The system prioritises trust, correctness, and traceability over autonomy, creativity, or real-time responsiveness.

### 1.2 Success Criteria

- Users can confidently ask: "Did I do X?", "What happened recently?", "When is Y due?"
- Every recalled answer links back to its source (image, message, email, or task).
- The system asks follow-up questions when uncertain rather than guessing.
- No unverified or inferred data is treated as truth.
- Capture friction is minimal — sending a message is enough to store it.

---

## 2. Target Users

### 2.1 Primary User

A single individual comfortable interacting via Telegram, who values recall accuracy and wants to stop losing information across apps.

### 2.2 Secondary Users (Future)

Two to three additional users in a shared Telegram group (up to four users total). No privacy boundaries between users in shared context — all data is searchable by all participants. Records are still tagged by `owner_user_id` for filtering.

---

## 3. Non-Goals

This product is explicitly not any of the following:

- A full email client
- A social bot or coding assistant
- A real-time system
- A source of implicit or inferred truth
- An autonomous agent that takes actions without confirmation
- A system requiring enterprise-grade compliance, complex permission models, or large-scale performance

---

## 4. Key Principles & Constraints

1. **Capture-first (text):** All inbound text messages are queued for LLM classification. Non-search messages are stored as Memories after classification. Search queries are processed without storage.
2. **Capture-pending (images):** Inbound images are stored as pending Memories. If the user does not interact with the image (confirm tags, reject tags, promote to task, pin, or any other action) within 7 days, the image and its pending Memory are hard deleted. This encourages proper tagging habits and prevents unmanaged data accumulation.
3. **LLMs are advisory, not authoritative:** LLM outputs are suggestions only. No LLM output directly modifies persisted data without user confirmation.
4. **Deterministic features must work without LLMs:** Text messages remain in the queue until the LLM is available. The queue persists across restarts. Messages expire after 14 days. The user is notified of expired messages. If the LLM is unavailable, capture, task tracking, and reminders continue to function. Search availability without the LLM depends on implementation: if the LLM's search path relies on a keyword/full-text search mechanism internally, that same mechanism serves as the fallback; otherwise, search is LLM-dependent and pauses when the LLM is down. This will be determined during implementation planning.
5. **All recalled information must have provenance:** Every answer returned to the user includes a link or attachment to the original source data.
6. **Uncertainty must be surfaced:** When the system cannot confidently answer a query, it asks clarifying questions rather than guessing.

---

## 5. Core Features & Specifications

### 5.1 Chat Interface (Telegram)

Telegram is the primary interaction surface. All user interaction happens through Telegram DM or a shared group chat. Shared group chats are assumed to be dedicated to the bot for memory purposes, not general conversation.

**Capabilities**

- Accept text messages and images (with optional captions).
- Respond to natural-language queries.
- Present inline keyboard buttons for quick actions (promote to task, set reminder, tag, delete).
- Ask follow-up questions when queries are ambiguous.

**Identity**

- Telegram user ID is the canonical `user_id`.
- Each record stores `owner_user_id` (sender) and `source_chat_id` / `source_message_id` for traceability.
- In shared chats, all users' data is searchable by default. In individual DMs, search is scoped to the requesting user.

**Gateway Abstraction**

The messaging integration must be isolated behind a gateway interface so Telegram can be swapped for another platform with similar primitives (receive messages, send messages, inline buttons/callbacks) in the future.

**Conversation Context Tracking**

When the LLM asks a follow-up question (ambiguous classification), the system tracks multi-turn conversation context:

1. Context stored in per-user state with key `PENDING_LLM_CONTEXT`
2. Includes: original message text, LLM's question, timestamp, memory_id (if created)
3. User's next text message is treated as the answer to the follow-up, not a new message
4. Both original message and answer are sent to the LLM for re-classification
5. Context expires after a configurable timeout (default: 5 minutes). On expiry, the memory is kept as-is and the queue resumes.

---

### 5.2 Universal Capture & Memory

**Capture Behaviour**

Every inbound message (text or image) in a DM or group where the bot is present is processed as follows:

- **Text messages:** Queued for LLM classification. User receives a context-aware acknowledgment immediately: "Processing..." if the queue is empty and idle, or "Added to queue" if the queue already has items or is currently processing another message. Based on classification:
  - **reminder** — saved as confirmed memory + reminder proposed for user confirmation
  - **task** — saved as confirmed memory + task proposed for user confirmation
  - **search** — NOT saved as a memory; search results returned directly
  - **general_note** — saved as confirmed memory with LLM-suggested tags + standard action buttons
  - **ambiguous** — saved as confirmed memory; LLM asks a follow-up question; queue paused for this user until resolved or timed out
- **Images:** Stored as a pending Memory record tagged to the sender's Telegram user ID. The image enters a 7-day retention window. If the user takes any action on the image (confirm tags, reject tags, promote to task, set reminder, pin, or manually tag) within 7 days, the Memory is confirmed and retained permanently. If no action is taken within 7 days, the pending Memory and its associated image data are hard deleted.

**Image Handling**

- Timestamp: time received.
- Description: user-provided caption text.
- Location: optional. Priority order: user text → metadata → LLM-suggested (marked as inferred).
- Tags: proposed by the vision LLM; must be user-confirmed before being persisted.
- Media storage: Telegram `file_id` references stored at ingest; actual bytes retrieved via Telegram's `getFile` mechanism when needed.

**Storage Rules**

- No image-derived fact (tag, location, classification) is stored as confirmed without user approval.
- Each Memory entry includes: source reference, timestamp, `owner_user_id`, status (confirmed or pending), and audit log entry.

**Recall Rules**

- Image-based recall always returns the image itself, not just a text summary.
- No abstract summary is returned without source attachment.
- Only confirmed Memories appear in search results. Pending images are not searchable.

---

### 5.3 Inline Actions

Buttons are context-dependent based on LLM classification:

- **General notes** get standard buttons (Task, Remind, Tag, Pin, Delete) + tag suggestion buttons (Confirm Tags, Edit Tags)
- **Reminder proposals** get [Confirm] [Edit time] [Just a note]
- **Task proposals** get [Confirm] [Edit] [Just a note]
- **Ambiguous** gets the follow-up question text; next user reply is treated as the answer

**Pin Behaviour**

Pinning a Memory does two things:

1. **Search boost:** Pinned items are ranked higher in search results.
2. **Filterable tag:** Pinned items can be filtered as a category (e.g. via a `/pinned` command or a filter toggle in search).

Pinning counts as user interaction for the purpose of the 7-day image retention window.

---

### 5.4 Task Management

**Task States**

Tasks have two states: `NOT DONE` and `DONE`.

**Capabilities**

- Create tasks with optional due dates.
- Support repeatable tasks via a `recurrence_minutes` field.
- Link tasks to source Memories or events.

**Repeatable Tasks**

A task is repeatable if it has a non-null `recurrence_minutes` value. When a repeatable task is marked as `DONE`:

1. The current task is marked `DONE` with a completion timestamp.
2. A new task is automatically created with the same description, tags, and `recurrence_minutes` value.
3. The new task's due date is calculated as: `previous_due_date + recurrence_minutes`.
4. This is a deterministic operation — no LLM is involved.

If the original task had no due date, the new task's due date is calculated as: `completion_timestamp + recurrence_minutes`.

**Completion Rules**

- Task completion must be explicit (user confirms via deterministic API, not LLM inference).
- LLM may suggest completion (e.g. based on an image matching a task), but the user must confirm.
- Timestamp recorded on completion.

**Reminders**

- Triggered by schedule.
- Reminders must persist across restarts (durable scheduler backed by storage).
- No acknowledgement required — reminders fire regardless.
- Default reminder time is a configurable setting (e.g. 9:00 AM).

**Reminder Recurrence**

A reminder is repeatable if it has a non-null `recurrence_minutes` value. When a recurring reminder fires:

1. The reminder is delivered to the user.
2. A new reminder is automatically scheduled at: `previous_fire_time + recurrence_minutes`.
3. This is a deterministic operation — no LLM is involved.

**Deferred to future versions:** Snooze and reschedule buttons on reminder messages.

---

### 5.5 Email & External Event Tracking

**Workflow**

1. Inbox is polled periodically.
2. Candidate events are extracted (dates, actions, deadlines).
3. Event is sent to the user for confirmation via Telegram.
4. Pending for up to 24 hours.

**Outcomes**

- Confirmed → stored as an event with a reminder scheduled.
- Rejected → discarded.
- Unanswered after 24 hours → re-queued for another prompt.

**Audit Logging**

All outcomes (confirmed, rejected, expired, re-queued) are recorded in the audit log.

**Implementation Details**

Protocol, polling frequency, inbox filtering, and authentication details are deferred to the implementation planning phase.

---

### 5.6 Search & Recall

**MVP Search**

Users issue a query (e.g. `/find passport renewal`) and the bot returns the top three to five results ranked by keyword match and recency, with brief snippets. A "Show details" button returns the full stored record including any attached media.

**Query Routing**

- LLM classifies query intent (task query, event query, general memory query).
- Query is routed to the appropriate subsystem.
- If ambiguous, the system asks clarifying questions.

**Search Scope**

- Only confirmed Memories are included in search results. Pending images are excluded.
- Deleted items are not searchable (hard deletes).
- Pinned items receive a ranking boost in results.

**Output Requirements**

- Results grouped by source type.
- All answers include links or attachments to original data.

---

### 5.7 LLM Usage (OpenAI API)

The LLM is accessed via the OpenAI API and acts strictly as an advisory layer. It never writes to the database directly. All LLM outputs are disposable unless explicitly confirmed by the user.

#### 5.7.1 Trigger Points

The LLM is invoked at specific, well-defined points in the system. Each trigger has a clear input, expected output, and what happens with that output.

**On text receive (intent classification)**

- **Trigger:** User sends a text message to the bot.
- **Input:** The text message content.
- **Output:** A classified intent — one of: reminder, task, search, general_note, or ambiguous. For general_note, the LLM also suggests tags.
- **What happens next:** Based on classification: reminder/task saved as confirmed memory + proposal sent for user confirmation; search returns results without storage; general_note saved with LLM-suggested tags and standard action buttons; ambiguous triggers a follow-up question with queue paused for this user.

**On image receive (vision model)**

- **Trigger:** User sends an image (with or without a caption) to the bot.
- **Input:** The image bytes and any caption text.
- **Output:** A set of suggested tags, an optional inferred location, and an optional short description if no caption was provided.
- **What happens next:** The suggestions are presented to the user as inline buttons (Confirm Tags / Edit Tags). Nothing is persisted as confirmed until the user acts. The image is stored as a pending Memory subject to the 7-day retention window. If the LLM is unavailable, the image is still stored as pending — tagging is queued for retry.

**On search query (intent classification)**

- **Trigger:** User sends a natural-language query or uses `/find`.
- **Input:** The query text.
- **Output:** A classified intent — one of: task query, event query, general memory query, or ambiguous.
- **What happens next:** The query is routed to the matching subsystem (task store, event store, or full memory search). If classified as ambiguous, the system generates a follow-up question (see below). LLM-unavailable fallback behaviour depends on implementation (see principle 4).

**On ambiguous query (follow-up generation)**

- **Trigger:** The intent classifier returns "ambiguous", or a search returns zero results.
- **Input:** The original query text and (optionally) the empty result set context.
- **Output:** A clarifying question to send back to the user (e.g. "Did you mean the task 'Install shelf' or are you looking for a photo?").
- **What happens next:** The question is sent to the user via Telegram. Their reply re-enters the normal query flow.

**On task completion suggestion**

- **Trigger:** User sends an image or message that the system detects may relate to an open task. Detection is based on keyword overlap between the new Memory's content/caption and open task descriptions.
- **Input:** The new Memory content and the candidate open task(s).
- **Output:** A confidence assessment and a suggested match (e.g. "This image looks related to the task 'Install shelf'").
- **What happens next:** The suggestion is presented to the user with a confirmation button (Mark as DONE? [Yes] [No]). The task state only changes if the user taps Yes via the deterministic API.

**On email event extraction**

- **Trigger:** The email poller retrieves new messages from the inbox.
- **Input:** Email subject and body text.
- **Output:** Zero or more candidate events, each with an extracted date, a short description, and a confidence level.
- **What happens next:** Each candidate is sent to the user for confirmation. The 24-hour pending / re-queue / discard flow applies as described in section 5.5.

#### 5.7.2 LLM Queue & Retry

All LLM invocations are placed on an internal queue. Queue items expire after 14 days from original queue time.

**Retry strategy:**

- **Attempts 1-5:** exponential backoff (1s, 2s, 4s, 8s, 16s)
- **Attempts 6+:** fixed 30-minute intervals
- **Hard expiry:** 14 days from original queue time
- **On expiry:** mark job as expired, notify user

**One-at-a-time processing:** The queue processes one message per user at a time. This ensures:

- Follow-up replies are always associated with the correct conversation
- Results appear in natural sequential order in the Telegram chat
- No interleaving of LLM results

**Flood control:** When processing a backlog after LLM recovery, add a configurable delay (e.g., 5-10 seconds) between delivering results for consecutive messages.

**Stale message handling:** When the LLM processes a queued message, the original message timestamp is included in the payload. The LLM uses this to resolve relative time references ("tomorrow", "in 5 minutes", "next week"). If the resolved datetime is in the past, the system notifies the user (e.g., "Your message from [date] mentioned a reminder for [resolved date], which has passed") and offers [Reschedule] [Dismiss]. If the user reschedules, they pick a new date/time. If dismissed, the memory is kept but no reminder/task is created.

**Unconfirmed tag suggestions:** If the LLM successfully generates tag suggestions but the user does not act on them (confirm, reject, edit, or take any other action on the Memory) within 7 days, the suggestions are discarded. For images, this also triggers the pending Memory hard delete per the image retention policy (section 5.2).

#### 5.7.3 Model Selection

The system uses two model roles, both accessed via the OpenAI API:

- **Vision model** (e.g. `gpt-4o-mini`): Used for image tagging, description, and location inference.
- **Text model** (e.g. `gpt-4o-mini`): Used for intent classification, follow-up generation, email event extraction, and task matching.

Model names are configured via environment variables (`LLM_VISION_MODEL`, `LLM_TEXT_MODEL`) so they can be swapped without code changes.

#### 5.7.4 Constraints Summary

- No direct database writes — all outputs pass through a user confirmation step or are used only for ephemeral routing decisions (like intent classification).
- No authoritative decisions — the LLM never changes task state, creates events, or persists tags on its own.
- All outputs are disposable unless user-confirmed.
- If the LLM is down, capture, task tracking, and reminders continue working. Search fallback depends on implementation (see principle 4).

---

### 5.8 Data Storage & Backup

**Storage**

Local storage for database, images, and audit logs.

**Backup**

- Weekly backup to S3 for disaster recovery.
- Backup includes: all databases, images, and audit logs.
- Acceptable data loss: up to 7 days.
- System exposes a `last-backup` timestamp for visibility.

**Recovery**

In the event of database corruption, a full restore from the latest S3 backup is performed.

---

## 6. Feature Roadmap

### 6.1 MVP (Must-Have)

1. Universal capture: text messages queued for LLM classification then stored; images stored as pending with 7-day retention window.
2. Inline actions: context-dependent buttons based on LLM classification.
3. Image tagging via LLM: vision model proposes tags; user confirms. Unconfirmed suggestions discarded after 7 days.
4. Task management: create tasks with optional due date, mark DONE/NOT DONE, repeatable tasks via `recurrence_minutes`.
5. Reminders: create from any Memory, deliver at scheduled time, persist across restarts. Recurring reminders via `recurrence_minutes`. Default reminder time configurable.
6. Email event extraction: poll inbox, extract candidates, confirm/reject/re-queue flow with full audit logging. Implementation details deferred.
7. Basic search: `/find <query>` returns top 3-5 matches; "Show details" returns full record with media. Pinned items boosted.

### 6.2 V1 (High Value, Next)

1. Search pagination and filters: paginated results with toggles for owner, content type, date range, tags, and pinned status.
2. Media-first retrieval: "Show details" re-sends stored photos along with extracted metadata.
3. Task enhancements: `/today` and `/tasks` commands, basic priority levels.
4. Snooze and reschedule buttons on reminder messages.
5. LLM-suggested conversion of completed tasks to repeatable tasks based on description patterns.
6. Advanced summarisation vs raw recall options.

### 6.3 Later (Optional, Aligned)

1. OCR and speech-to-text: make screenshots, receipts, and voice notes searchable.
2. Semantic search: handle queries where the user doesn't remember exact words.
3. Routines and habits: morning/evening checklists.
4. Selective restore from backups.
5. UI for bulk confirmation cleanup.
6. Migration to non-Telegram interfaces.

---

## 7. Failure Modes & Degradation

| Failure | Behaviour |
|---|---|
| LLM unavailable during text classification | Text messages remain in the per-user queue. The queue retries with the backoff strategy defined in 5.7.2. Messages expire after 14 days. The user is notified of expired messages. |
| LLM unavailable | Tagging, suggestions, and intent classification pause. Capture, tasks, and reminders continue. Search fallback depends on implementation (see principle 4). |
| Image tagging fails | Retries via queue. Image is still stored as a pending Memory without tags — subject to 7-day retention window. |
| Database corruption | Full restore from latest S3 backup. |
| Unanswered confirmations (email) | Re-queued after 24 hours per policy. |
| Unanswered image suggestions | Pending Memory and image hard deleted after 7 days. |
| Telegram API outage | Inbound capture paused. Scheduled reminders queued for delivery when restored. |
| LLM queue overflow | Items beyond retry limit marked as failed in audit log. User notified to add metadata manually. |
| Stale queued message (resolved time in the past) | When LLM processes a delayed message and resolves relative time references to a past datetime, user is notified with [Reschedule] [Dismiss] options. Memory is still saved. See 5.7.2 for details. |

---

## 8. Non-Functional Requirements

- **Modularity / Portability:** Messaging integration isolated behind a gateway interface for future platform swaps. Key components split into separate Docker images for clear separation of responsibilities.
- **Reliability:** Reminders persist across restarts via durable scheduler and storage. LLM queue persists across restarts. Text message queue with 14-day expiry.
- **Low scale:** Optimised for correctness and UX, not throughput (2-4 users).
- **Security:** Allowlist known Telegram user IDs to prevent unauthorised access.
- **Auditability:** All state transitions (confirmation, rejection, completion, re-queue, LLM failures, pending expiry) are logged with timestamps and user IDs.
- **Deployment:** Personal server. Docker-based deployment with key components in separate containers.
- **Tech stack:** To be determined during implementation planning.

---

## 9. Example User Interactions

### Example 1: Image Memory Capture

**User:** *(sends image of grocery receipt with caption "Butter purchase")*

**Bot:** Saved as pending! I suggest these tags: "butter", "groceries", "receipt". Possible location: "Cold Storage". [Confirm Tags] [Edit Tags] [Task] [Remind]

**User:** Taps [Edit Tags] → removes location, confirms tags.

**Result:** Image confirmed as Memory. Tags confirmed. Location omitted.

---

### Example 2: Text Message Capture (Queue-First)

**User:** *(sends message "Renew passport by March 20")*

**Bot:** Processing...

**Bot:** (after LLM classification) Saved! This looks like a reminder. Remind you on March 18 at 9am? [Confirm] [Edit time] [Just a note]

**User:** Taps [Confirm].

**Result:** Memory stored. Reminder scheduled for March 18.

---

### Example 3: Text Message Search Query

**User:** *(sends message "Where did I put my passport?")*

**Bot:** Processing...

**Bot:** (after LLM classification - search intent) Found 2 results: (1) Note — "Passport in drawer" — Jan 15. (2) Image — "Passport photo" — Dec 10. [Show details 1] [Show details 2]

**Result:** Search results returned. No memory stored for this query.

---

### Example 4: Ambiguous Text Message

**User:** *(sends message "meeting Thursday")*

**Bot:** Processing...

**Bot:** Saved! I'm not sure what you'd like to do with this. Is this: [A reminder for Thursday] [A task to prepare for] [Just a note to keep]

**User:** Taps [A reminder for Thursday].

**Bot:** Which Thursday — February 12 or February 19? [Feb 12] [Feb 19]

**User:** Taps [Feb 12].

**Result:** Memory stored. Reminder scheduled for February 12 at configured default time. (Conversation context tracked via `PENDING_LLM_CONTEXT`.)

---

### Example 5: Promote to Reminder (from confirmed memory)

**User:** *(sends message "Renew passport by March 20")*

**Bot:** Processing...

**Bot:** Saved! [Task] [Remind] [Tag] [Pin]

**User:** Taps [Remind] → Bot proposes March 18 at 9am (configurable default) → User confirms.

**Result:** Memory stored. Reminder scheduled for March 18.

---

### Example 6: Task Completion Suggestion

**User:** *(sends image of completed shelf installation)*

**Bot:** Saved as pending! This looks related to the task "Install shelf". Mark as DONE? [Yes] [No] [Task] [Remind] [Tag]

**User:** Taps [Yes].

**Result:** Task marked DONE via deterministic API. Timestamp recorded. Image confirmed as Memory and linked to the task.

---

### Example 7: Email Event Extraction

**Bot:** I detected an event from an email: "Tax payment due on March 15." Add as event? [Yes] [No]

**User:** Taps [Yes].

**Result:** Event stored. Reminder scheduled. Audit log updated.

---

### Example 8: Basic Search

**User:** `/find butter price`

**Bot:** Found 2 results: (1) Image — "Butter purchase" — Feb 5. (2) Note — "Butter was $4.50" — Jan 28. [Show details 1] [Show details 2]

**User:** Taps [Show details 1] → Bot returns full image with timestamp, tags, and caption.

---

### Example 9: Image of Event Poster

**User:** *(sends image of a concert poster, no caption)*

**Bot:** Saved as pending! I found: "Summer Jazz Festival, Marina Bay, June 14 2026, 7pm". Suggested tags: "concert", "jazz", "marina bay". [Confirm Tags] [Edit Tags] [Remind] [Task]

**User:** Taps [Confirm Tags], then taps [Remind].

**Bot:** When should I remind you? [1 day before] [3 days before] [1 week before] [Custom]

**User:** Taps [1 week before].

**Result:** Image confirmed as Memory with tags. Reminder scheduled for June 7. If the user later searches for "jazz" or "marina bay", this image is returned directly.

---

### Example 10: Ambiguous Query

**User:** "What about the shelf?"

**Bot:** I found a few things related to "shelf": (1) Task — "Install shelf" (DONE, completed Feb 3). (2) Image — shelf installation photo (Feb 3). (3) Note — "IKEA shelf dimensions 80x30cm" (Jan 20). Which one did you mean? [Show task] [Show image] [Show note]

**User:** Taps [Show image] → Bot returns the image with timestamp and linked task.

---

### Example 11: Image with No Action (Expiry)

**User:** *(sends photo of a sunset, no caption)*

**Bot:** Saved as pending! Suggested tags: "sunset", "landscape", "outdoor". [Confirm Tags] [Edit Tags] [Task] [Remind] [Pin]

**User:** *(does not respond)*

**Result (after 7 days):** No user action taken. Pending Memory and image are hard deleted. Audit log records the expiry.

---

### Example 12: Image Pinned Without Tag Confirmation

**User:** *(sends photo of a sunset, no caption)*

**Bot:** Saved as pending! Suggested tags: "sunset", "landscape", "outdoor". [Confirm Tags] [Edit Tags] [Task] [Remind] [Pin]

**User:** Taps [Pin].

**Result:** Image confirmed as Memory and pinned. Tag suggestions discarded (user chose to pin but didn't act on tags). Image is retained permanently because pinning counts as user interaction. Findable by date or via pinned items filter.

---

### Example 13: Shared Chat Query

**User (in shared chat):** "What happened last Friday?"

**Bot:** Here are entries from last Friday (Feb 6): (1) [Alice] Image — "Dinner at Lau Pa Sat" (2) [Bob] Note — "Signed tenancy renewal" (3) [Alice] Task completed — "Submit tax docs". [Show details 1] [Show details 2] [Show details 3]

---

### Example 14: LLM Unavailable During Capture

**User:** *(sends image of a whiteboard with meeting notes, caption "Sprint planning")*

**Bot:** Saved as pending! I couldn't generate tag suggestions right now — I'll retry shortly. You can add tags manually in the meantime. [Tag] [Task] [Remind]

**Result:** Image stored as pending Memory with caption. Image tagging request placed on the LLM retry queue. When the LLM becomes available, the user receives a follow-up: "I have tag suggestions for your image 'Sprint planning': 'whiteboard', 'meeting', 'sprint'. [Confirm Tags] [Edit Tags]". The 7-day retention window applies — if the user does not act on either the original buttons or the follow-up suggestions within 7 days of the original send, the pending Memory is deleted.

---

### Example 15: Repeatable Task Completion

**User:** Has a task "Take vitamins" with `recurrence_minutes: 1440` (daily) and due date of Feb 10.

**User:** Taps [Mark DONE] on "Take vitamins".

**Result:** Task marked DONE with completion timestamp. New task auto-created: "Take vitamins", due Feb 11, `recurrence_minutes: 1440`. No LLM involved.

---

### Example 16: Stale Message Handling

**User:** *(sends message "Remind me tomorrow at 9am")*

**Bot:** Processing...

**Bot:** (LLM resolves "tomorrow" to Feb 24 9am — which is in the past since today is Feb 23) I see you wanted to be reminded at 9am tomorrow (Feb 24), but that's in the past. Would you like to: [Reschedule] [Dismiss]

**User:** Taps [Reschedule].

**Bot:** Please pick a new date/time: [Feb 24 9am] [Feb 25 9am] [Custom]

**Result:** If user selects a future time, reminder scheduled. If user dismisses, no reminder set.

---

### Example 17: Queue-First with Backlog

**User:** Sends message "Buy milk"

**Bot:** Processing...

**User:** *(immediately sends another message "Buy eggs")*

**Bot:** Added to queue

**Bot:** (first message classified, sends result) Saved! [Task] [Remind] [Tag] [Pin]

**Bot:** (second message processed after 5-10s delay for flood control) Saved! [Task] [Remind] [Tag] [Pin]

**Result:** Both messages processed in order with appropriate delays to prevent flooding.

---

## 10. Data Model (Canonical Object Types)

- **Memory (base record):** Every inbound message becomes a Memory first. Stores: `owner_user_id`, `source_chat_id`, `source_message_id`, timestamp, content/caption, media `file_id` references, confirmed tags, status (`confirmed` / `pending`), `pending_expires_at` (for images: timestamp + 7 days; null for text), `is_pinned`, audit log entry.
- **Task:** A Memory promoted to an actionable item. Adds: status (`NOT DONE` / `DONE`), optional due date, `recurrence_minutes` (null if not repeatable), linked source Memory ID.
- **Reminder / Event:** A scheduled notification derived from a Memory. Adds: fire datetime, `recurrence_minutes` (null if not repeatable), linked source Memory ID.
- **Note / Idea (V1):** A Memory categorised for reference. Adds: tags and search-first access.

---

## 11. Success Metrics

- **Capture friction:** Percentage of reminders created via inline button with one or fewer follow-up questions.
- **Retrieval speed:** Median time from `/find` query to useful result selection.
- **Trust:** Low rate of missed or late reminders.
- **Provenance:** 100% of recalled answers include a source link or attachment.
- **Confirmation coverage:** Zero instances of unverified tags or metadata persisted without user approval.
- **Image retention:** Percentage of images that are confirmed (acted on) versus expired.
- **Queue health:** Percentage of messages processed within 14-day expiry window.

---

## 12. MVP Acceptance Criteria

1. In DM and shared group, sending any text queues the message for LLM classification. User receives acknowledgment ("Processing..." or "Added to queue"). Based on classification: reminder/task stored + proposal shown, search returns results without storage, general_note stored with LLM-suggested tags, ambiguous triggers follow-up with queue pause. Sending an image creates a pending Memory with a 7-day retention window.
2. Bot responds with inline buttons; tapping "Remind" schedules a reminder; reminder fires at scheduled time.
3. Tapping "Task" creates a task with optional due date; task can be marked DONE. Repeatable tasks auto-generate next instance on completion.
4. Images processed by the vision model; suggested tags sent to user for confirmation; only confirmed tags persisted. Unconfirmed suggestions discarded after 7 days.
5. Email polling extracts candidate events; user confirms/rejects; unanswered items re-queued after 24 hours; all outcomes audit-logged.
6. `/find <query>` returns top 3-5 matches from confirmed Memories only; "Show details" returns full content and attached media. Pinned items boosted in ranking.
7. Deterministic features (capture, tasks, reminders) function when LLM is unavailable. Text messages remain queued until LLM available. Search fallback behaviour determined during implementation.
8. Reminders and recurring reminders persist across bot restarts.
9. Pending images with no user interaction are hard deleted after 7 days.
10. Delete action performs a hard delete.
11. Queue-first processing with one-at-a-time per-user ordering and flood control.
12. Stale message handling: when LLM resolves relative time to past datetime, notify user with reschedule/dismiss options.

---

## 13. Open Questions (Deferred)

- Advanced summarisation versus raw recall trade-offs.
- Selective restore from backups (per-record granularity).
- UI for bulk confirmation cleanup of pending tags/events.
- Migration path to non-Telegram interfaces.
- Complex permission models if user count grows beyond four.
- Semantic search implementation details and model selection.
- Email integration implementation details (protocol, polling frequency, filtering, authentication).
- Search implementation: whether LLM search relies on keyword search internally (which would provide a natural fallback).
- Tech stack selection.
