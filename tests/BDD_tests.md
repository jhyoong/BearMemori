# BDD Test Scenarios

Scope: Core, Telegram, LLM. Email and backup features are not in scope.

Key rules:
- All memories (text and image) start as **pending** until confirmed by user action via system buttons.
- Hard delete after **7 days** if waiting for user action. Hard delete after **14 days** if waiting for LLM availability.
- A **conversation** starts only when the LLM requires additional text input (e.g., ambiguous classification). During a conversation, the next incoming text is treated as the answer. Outside of a conversation (system shows buttons), incoming text is added to the queue.
- Conversations conclude via system button press or 7-day timeout. No other timeout mechanism exists.
- The queue processes the next message only after the current conversation has concluded.
- LLM retries differentiate between **invalid responses** (exponential backoff, max 5 attempts) and **unavailability** (queue paused until reachable or 14-day expiry).
- Pin auto-saves any suggested tags.

---

# Image Input Scenarios

Scenario 1 — Image: happy path, user confirms tags
1. User sends an image
2. System is available and running fully
3. LLM processes the image and generates tags
4. System sends proposed tags with buttons: [Confirm Tags] [Edit Tags] [Task] [Remind] [Pin] [Delete]
5. User taps [Confirm Tags]
6. Memory confirmed, tags saved
7. Audit log records confirmation

Scenario 2 — Image: user rejects tags and enters manually
1. User sends an image
2. System is available and running fully
3. LLM processes the image and generates tags
4. System sends proposed tags with buttons: [Confirm Tags] [Edit Tags] [Task] [Remind] [Pin] [Delete]
5. User taps [Edit Tags]
6. System prompts for manual tag input
7. User keys in tags manually
8. Memory confirmed with custom tags
9. Audit log records confirmation

Scenario 3 — Image: LLM unavailable, recovers within 14 days
1. User sends an image
2. System is available but LLM is not reachable
3. Image stored as pending memory, tagging request queued for LLM
4. User gets message: "Saved as pending! I couldn't generate tags — I'll retry when available."
5. LLM becomes reachable (within 14-day window)
6. LLM processes the image and generates tags
7. System sends proposed tags with buttons: [Confirm Tags] [Edit Tags] [Task] [Remind] [Pin] [Delete]
8. User confirms tags
9. Memory confirmed, tags saved

Scenario 4 — Image: LLM unavailable for 14 days, pending memory deleted
1. User sends an image
2. System is available but LLM is not reachable
3. Image stored as pending memory, tagging request queued for LLM
4. LLM remains unreachable for 14 days
5. After 14 days, LLM queue item marked as expired
6. Pending memory and image hard deleted from database
7. Audit log records expiry
8. User notified: "Your image from [date] could not be processed and has expired."

Scenario 5 — Image: tags proposed, user does not respond within 7 days
1. User sends an image
2. System is available and running fully
3. LLM processes the image and generates tags
4. System sends proposed tags with buttons
5. User does not respond within 7 days
6. Pending memory and image hard deleted from database
7. Audit log records expiry

Scenario 6 — Image: user pins, tags auto-saved
1. User sends an image
2. System processes image via LLM
3. System sends proposed tags with buttons: [Confirm Tags] [Edit Tags] [Task] [Remind] [Pin] [Delete]
4. User taps [Pin]
5. Suggested tags auto-saved
6. Memory confirmed and pinned
7. Memory appears in /pinned filter

Scenario 7 — Image: user taps Delete
1. User sends an image
2. System processes image via LLM
3. System sends proposed tags with buttons
4. User taps [Delete]
5. Pending memory and image hard deleted from database
6. Audit log records deletion

Scenario 8 — Image with caption: user promotes to task
1. User sends an image with caption "Receipt for dinner"
2. System processes image via LLM
3. System sends proposed tags with buttons: [Confirm Tags] [Edit Tags] [Task] [Remind] [Pin] [Delete]
4. User taps [Task]
5. Memory confirmed
6. Task created with caption as description, linked to memory

Scenario 9 — Image with caption: user sets reminder
1. User sends an image with caption "Receipt for dinner"
2. System processes image via LLM
3. System sends proposed tags with buttons: [Confirm Tags] [Edit Tags] [Task] [Remind] [Pin] [Delete]
4. User taps [Remind]
5. Memory confirmed
6. System proposes default reminder time
7. User confirms reminder time
8. Reminder scheduled and linked to memory

---

# Text Input Scenarios

Scenario 10 — Text: classified as reminder, user confirms
1. User sends text "Remind me to buy butter at 6pm"
2. System responds: "Processing..."
3. Text queued for LLM classification
4. LLM classifies intent as "reminder"
5. LLM extracts: action="buy butter", time="6pm today" (resolved from original message timestamp)
6. Text stored as pending memory
7. System sends: "Set reminder for 'buy butter' at 6pm today? [Confirm] [Edit time] [Just a note]"
8. User taps [Confirm]
9. Memory confirmed, reminder created and linked to memory

Scenario 11 — Text: classified as task, user confirms
1. User sends text "I need to buy butter later at 6pm"
2. System responds: "Processing..."
3. Text queued for LLM classification
4. LLM classifies intent as "task"
5. LLM extracts: description="buy butter", due_time="6pm today"
6. Text stored as pending memory
7. System sends: "Create task 'buy butter' due at 6pm today? [Confirm] [Edit] [Just a note]"
8. User taps [Confirm]
9. Memory confirmed, task created with due date and linked to memory

Scenario 12 — Text: classified as general note, user confirms tags
1. User sends text "Best method to get to mount fuji from hakone is take the bus"
2. System responds: "Processing..."
3. Text queued for LLM classification
4. LLM classifies intent as "general_note"
5. Text stored as pending memory
6. LLM suggests tags: "travel", "japan", "transport"
7. System sends: "Suggested tags: travel, japan, transport. [Confirm Tags] [Edit Tags] [Task] [Remind] [Pin] [Delete]"
8. User taps [Confirm Tags]
9. Memory confirmed, tags saved

Scenario 13 — Text: classified as search, not saved
1. User sends text "When did I last buy butter?"
2. System responds: "Processing..."
3. Text queued for LLM classification
4. LLM classifies intent as "search"
5. Text is NOT saved as a memory
6. System performs search for "butter"
7. Top 3-5 results returned with snippets
8. User taps [Show details] on a result

Scenario 14 — Text: classified as reminder, user taps Just a note
1. User sends text "Meeting with John at 3pm tomorrow"
2. System responds: "Processing..."
3. Text queued for LLM classification
4. LLM classifies intent as "reminder"
5. Text stored as pending memory
6. System sends: "Set reminder for 'Meeting with John' at 3pm tomorrow? [Confirm] [Edit time] [Just a note]"
7. User taps [Just a note]
8. Memory confirmed, no reminder created

Scenario 15 — Text: group chat message
1. User sends a text message in a group chat
2. System responds: "Processing..."
3. Text queued for LLM classification
4. LLM classifies and processes accordingly
5. Pending memory tagged with sender's user_id and group chat_id
6. User confirms via system button
7. Memory confirmed

---

# Ambiguous Text Input Scenarios

Scenario 16 — Ambiguous: user replies to follow-up, confirms
1. User sends text "I need to buy butter later"
2. System responds: "Processing..."
3. Text queued for LLM classification
4. LLM classifies intent as "ambiguous" — unclear if task, reminder, or note
5. Text stored as pending memory
6. LLM generates follow-up: "Would you like this as a task or a reminder? And when is 'later'?"
7. System sends follow-up question (conversation starts)
8. User replies: "A reminder for 6pm"
9. Reply treated as answer to follow-up (not a new message)
10. LLM re-classifies with full context as "reminder"
11. System sends: "Set reminder for 'buy butter' at 6pm today? [Confirm] [Just a note]"
12. User taps [Confirm]
13. Memory confirmed, reminder created and linked to memory

Scenario 17 — Ambiguous: user does not reply within 7 days
1. User sends text "I need to do something later"
2. System responds: "Processing..."
3. Text queued for LLM classification
4. LLM classifies intent as "ambiguous"
5. Text stored as pending memory
6. LLM generates follow-up question
7. System sends follow-up question (conversation starts)
8. User does not reply or press any button within 7 days
9. Conversation concluded by timeout
10. Pending memory hard deleted from database
11. Audit log records expiry
12. Queue resumes, user's next message treated as a new message

Scenario 18 — Ambiguous: LLM was down, recovers, time is ambiguous
1. User sends text "Remind me to do something after work"
2. System responds: "Processing..."
3. Text queued for LLM classification
4. LLM is not reachable — message stays in queue
5. LLM becomes reachable (within 14-day window)
6. LLM classifies intent as "reminder" but time is ambiguous ("after work")
7. Text stored as pending memory
8. System sends follow-up: "I processed your earlier message. When do you finish work?"
9. System enters conversation state (conversation starts)
10. User replies: "5pm"
11. LLM extracts time, system proposes reminder with buttons
12. User taps [Confirm]
13. Memory confirmed, reminder created

---

# Inline Action Scenarios

Scenario 19 — Inline: general note promoted to task
1. User sends text "Buy groceries"
2. System responds: "Processing..."
3. Text queued for LLM classification
4. LLM classifies as general_note, text stored as pending memory
5. LLM suggests tags, system displays buttons: [Confirm Tags] [Edit Tags] [Task] [Remind] [Pin] [Delete]
6. User taps [Task]
7. Memory confirmed
8. Task created with description "Buy groceries", linked to memory

Scenario 20 — Inline: general note, user edits tags
1. User sends text "Important contract details"
2. System responds: "Processing..."
3. Text queued for LLM classification
4. LLM classifies as general_note, text stored as pending memory
5. LLM suggests tags, system displays buttons: [Confirm Tags] [Edit Tags] [Task] [Remind] [Pin] [Delete]
6. User taps [Edit Tags]
7. System prompts for tag input
8. User enters tags manually
9. Memory confirmed, custom tags saved

Scenario 21 — Inline: general note, user pins (tags auto-saved)
1. User sends text "Key project deadline"
2. System responds: "Processing..."
3. Text queued for LLM classification
4. LLM classifies as general_note, text stored as pending memory
5. LLM suggests tags, system displays buttons: [Confirm Tags] [Edit Tags] [Task] [Remind] [Pin] [Delete]
6. User taps [Pin]
7. Memory confirmed, pinned, suggested tags auto-saved
8. Memory appears in /pinned filter

Scenario 22 — Inline: general note, user deletes
1. User sends text "Temporary note to delete"
2. System responds: "Processing..."
3. Text queued for LLM classification
4. LLM classifies as general_note, text stored as pending memory
5. LLM suggests tags, system displays buttons: [Confirm Tags] [Edit Tags] [Task] [Remind] [Pin] [Delete]
6. User taps [Delete]
7. Pending memory hard deleted from database
8. Audit log records deletion

Scenario 23 — Inline: general note, user sets reminder
1. User sends text "Renew passport by March 20"
2. System responds: "Processing..."
3. Text queued for LLM classification
4. LLM classifies as general_note, text stored as pending memory
5. LLM suggests tags, system displays buttons: [Confirm Tags] [Edit Tags] [Task] [Remind] [Pin] [Delete]
6. User taps [Remind]
7. Memory confirmed
8. System proposes default reminder time
9. User confirms reminder time
10. Reminder scheduled and linked to memory

---

# Task Management Scenarios

Scenario 24 — Task: create with due date
1. User creates a task with due date "Submit report" due Feb 20
2. System creates task with status NOT DONE
3. Task has null recurrence_minutes (non-repeatable)
4. Task linked to source memory

Scenario 25 — Task: mark as DONE
1. User marks task "Submit report" as DONE
2. System updates task status to DONE
3. Completion timestamp recorded in audit log
4. Task remains in database as DONE

Scenario 26 — Task: repeatable daily, mark DONE
1. User has task "Take vitamins" with recurrence_minutes: 1440 (daily)
2. Task has due date Feb 10
3. User marks task as DONE
4. Current task marked DONE with completion timestamp
5. New task auto-created: "Take vitamins", due Feb 11, recurrence_minutes: 1440

Scenario 27 — Task: repeatable weekly, mark DONE
1. User has task "Weekly meeting" with recurrence_minutes: 10080 (weekly)
2. Task has due date Feb 15
3. User marks task as DONE
4. New task created with due date Feb 22 (7 days later)

Scenario 28 — Task: repeatable with no due date, mark DONE
1. User has task "Call mom" with recurrence_minutes: 4320 (every 3 days)
2. Task has no due date
3. User marks task as DONE
4. New task created with due date = completion_timestamp + 4320 minutes

Scenario 29 — Task: repeatable with no due date (generic)
1. User has task with no due date and recurrence_minutes set
2. User marks task as DONE
3. New task created with calculated due date from completion time

Scenario 30 — Task: LLM suggests completion from image, user confirms
1. LLM detects new image relates to existing open task based on keyword overlap
2. System suggests "This looks related to task 'Install shelf'. Mark as DONE?"
3. User taps [Yes]
4. Task marked DONE via deterministic API
5. Completion timestamp recorded
6. Image memory linked to task

Scenario 31 — Task: LLM suggests completion from image, user rejects
1. User sends image related to open task
2. LLM suggests task completion
3. User taps [No]
4. Task remains NOT DONE
5. Image stored as pending memory (standard image flow continues)

---

# Reminder Scenarios

Scenario 32 — Reminder: fires at scheduled time
1. User creates reminder "Call dentist" scheduled for Feb 15 at 9am
2. Reminder persisted in database
3. At scheduled time, reminder fires
4. Message sent to user via Telegram

Scenario 33 — Reminder: default time used
1. User creates reminder with default time
2. System uses configurable default reminder time (e.g., 9am)
3. Reminder scheduled at default time if user doesn't specify

Scenario 34 — Reminder: persists across system restart
1. System restarts
2. Scheduled reminders persist in database
3. Reminders continue firing at scheduled times

Scenario 35 — Reminder: recurring
1. User has recurring reminder with recurrence_minutes: 1440
2. Reminder fires at scheduled time
3. Reminder delivered to user
4. New reminder scheduled at previous_fire_time + recurrence_minutes
5. This happens deterministically (no LLM)

Scenario 36 — Reminder: one-time
1. User creates one-time reminder (null recurrence_minutes)
2. Reminder fires at scheduled time
3. Reminder marked as fired
4. No new reminder created

---

# Search & Recall Scenarios

Scenario 37 — Search: general memory query
1. User sends "/find passport renewal"
2. System uses LLM for intent classification
3. LLM classifies as general memory query
4. Keyword/vector search executed
5. Top 3-5 results returned ranked by match and recency
6. Brief snippets displayed

Scenario 38 — Search: task-specific query
1. User searches for task-specific query
2. LLM classifies as task query
3. Results filtered to open tasks
4. Results returned with brief snippets

Scenario 39 — Search: event-specific query
1. User searches for event-specific query
2. LLM classifies as event query
3. Results filtered to events
4. Results returned

Scenario 40 — Search: no results, follow-up question
1. User sends query with no results
2. LLM generates follow-up question
3. Question sent to user
4. User clarifies query

Scenario 41 — Search: pinned items boosted
1. User has pinned memories
2. User searches for related terms
3. Pinned items ranked higher in results (boost)

Scenario 42 — Search: show details
1. User taps [Show details] on search result
2. System returns full stored record
3. If image, actual image sent
4. Includes timestamp, tags, caption, source reference

Scenario 43 — Search: pending memories excluded
1. User searches for terms matching a pending memory
2. Pending memories excluded from results
3. Only confirmed memories returned

Scenario 44 — Search: vague query, disambiguation
1. User sends vague query "What about the shelf?"
2. Multiple items found (task, image, note)
3. System asks "Which one did you mean?"
4. Options presented to user
5. User selects one
6. Full record returned

---

# Queue Processing Scenarios

Scenario 45 — Queue: multiple non-ambiguous messages processed in order
1. User sends 3 text messages in quick succession:
   - "Remind me to call the dentist at 3pm"
   - "The best pizza place in town is Mario's"
   - "When did I last go to the gym?"
2. System responds "Processing..." to message 1, "Added to queue" to messages 2 and 3
3. LLM processes message 1: classifies as "reminder", proposes it — no conversation needed
4. User confirms reminder via button — conversation concluded
5. After flood control delay, LLM processes message 2: classifies as "general_note", suggests tags — no conversation needed
6. After flood control delay, LLM processes message 3: classifies as "search", returns results — no conversation needed
7. No pauses because no message required additional LLM input

Scenario 46 — Queue: ambiguous message pauses queue, user replies
1. User sends text "I need to buy butter later"
2. System responds: "Processing..." (queue was empty)
3. User immediately sends text "Pick up the kids sometime"
4. System responds: "Added to queue"
5. LLM processes first message, classifies as ambiguous
6. System sends follow-up question (conversation starts)
7. Queue paused — second message waits
8. User replies: "A reminder for 6pm"
9. Reply treated as answer to follow-up (not added to queue)
10. LLM re-classifies first message as reminder, proposes it with buttons
11. User confirms reminder via button — conversation concluded
12. Queue resumes
13. LLM processes second message "Pick up the kids sometime"
14. Process continues

Scenario 47 — Queue: multiple messages, ambiguous, reply as answer
1. User sends 3 text messages in quick succession
2. System responds "Processing..." to message 1, "Added to queue" to messages 2 and 3
3. LLM processes message 1, classifies as ambiguous, sends follow-up question
4. Conversation starts — queue paused, messages 2 and 3 wait
5. User sends text reply to follow-up question
6. Reply treated as answer to the follow-up (not added to queue)
7. LLM re-classifies message 1 with the answer, proposes action with buttons
8. User confirms via button — conversation concluded
9. Queue resumes with message 2

Scenario 48 — Queue: ambiguous, user does not reply within 7 days
1. User sends 2 text messages
2. System responds "Processing..." to message 1, "Added to queue" to message 2
3. LLM processes message 1, classifies as ambiguous, sends follow-up question
4. Conversation starts — queue paused, message 2 waits
5. User does not reply or press any button within 7 days
6. Conversation concluded by 7-day timeout
7. Pending memory for message 1 hard deleted from database
8. Audit log records expiry
9. Queue resumes — LLM processes message 2

Scenario 49 — Queue: text sent while buttons are shown goes to queue
1. User sends text "Buy groceries"
2. System responds: "Processing..."
3. LLM classifies as general_note, stores as pending, shows buttons
4. User sends another text "Call the plumber" instead of pressing a button
5. New text added to queue (not treated as conversation input, because no follow-up question was asked)
6. System still waits for button press on the first message
7. User taps [Confirm Tags] on first message — conversation concluded
8. Queue resumes, "Call the plumber" processed next

Scenario 50 — Queue: stale message, resolved time in the past
1. User sends text "Remind me to call the dentist tomorrow" on Feb 10
2. System responds: "Processing..."
3. LLM is not reachable — message stays in queue
4. LLM becomes reachable on Feb 17
5. LLM processes message, resolves "tomorrow" relative to Feb 10 = Feb 11
6. Feb 11 is in the past
7. Text stored as pending memory
8. System sends: "Your message from Feb 10 mentioned a reminder for Feb 11, which has passed. [Reschedule] [Dismiss]"
9. User taps [Reschedule] and picks a new date
10. Memory confirmed, reminder created with new date

Scenario 51 — Queue: LLM unavailable for 14 days, message expires
1. User sends text "Buy groceries"
2. System responds: "Processing..."
3. LLM is not reachable — message stays in queue
4. LLM remains unreachable for 14 days
5. After 14 days, queue item marked as expired
6. System notifies user: "Your message 'Buy groceries' from [date] could not be processed and has expired."
7. No memory saved (text was never classified)

---

# LLM Behavior & Retry Scenarios

Scenario 52 — LLM: image tag suggestions, nothing persisted until action
1. User sends image
2. Vision model generates suggested tags
3. Tags sent to user as buttons: [Confirm Tags] [Edit Tags] [Task] [Remind] [Pin] [Delete]
4. Nothing persisted as confirmed until user action

Scenario 53 — LLM: invalid response, exponential backoff
1. LLM processes an image tagging request
2. LLM returns an invalid or malformed response
3. System retries with exponential backoff (attempt 1: 1s, attempt 2: 2s, attempt 3: 4s, attempt 4: 8s, attempt 5: 16s)
4. All 5 retry attempts return invalid responses
5. Item marked as failed in audit log
6. User notified: "I couldn't process your image after multiple attempts. You can add tags manually. [Edit Tags] [Delete]"

Scenario 54 — LLM: service unreachable, queue paused
1. LLM processes a queue item
2. LLM service is not reachable (connection refused, timeout, etc.)
3. Queue enters paused state for this job type
4. System periodically checks LLM availability
5. LLM becomes reachable
6. Queue resumes, item reprocessed
7. If LLM remains unreachable for 14 days from original queue time, item marked as expired
8. User notified: "Your [image/message] from [date] could not be processed because the service was unavailable and has expired."

Scenario 55 — LLM: invalid response vs unreachable, different notifications
1. User sends two images in quick succession
2. Image 1 processing: LLM returns invalid response, retries 5 times, all fail
3. User notified for image 1: "I couldn't process your image after multiple attempts. You can add tags manually."
4. Image 2 processing: LLM is not reachable
5. User notified for image 2: "I couldn't generate tags — I'll retry when the service is available."
6. Different messages give user clarity on whether the issue is temporary (unavailable) or persistent (failed)

Scenario 56 — LLM: unavailable during image processing, pending memory retained
1. LLM not reachable during image processing
2. Image stored as pending memory without tags
3. Tagging request placed on LLM queue (up to 14 days)
4. User gets message: "Saved as pending! I couldn't generate tags — I'll retry when available."
5. LLM becomes reachable, processes image, sends tag suggestions
6. Standard tag confirmation flow continues
7. 7-day user action window starts from when tags are presented (not from original send)

Scenario 57 — LLM: tag suggestions not acted on within 7 days
1. Image pending with tag suggestions displayed to user
2. User does not act on suggestions within 7 days
3. Tag suggestions discarded
4. Pending memory and image hard deleted from database
5. Audit log records expiry

Scenario 58 — LLM: queue persists across restarts
1. LLM queue has items pending
2. System restarts
3. Queue items persist in database
4. On restart, queue resumes processing from where it left off

---

# Failure Mode Scenarios

Scenario 59 — Failure: LLM unavailable, text stays in queue
1. LLM is not reachable
2. User sends text message
3. Text added to queue, not stored as a memory
4. User receives: "Processing... (service temporarily unavailable, your message is queued)"
5. Existing confirmed memories remain searchable
6. Search for new content depends on implementation: keyword fallback if available, or search pauses until LLM returns

Scenario 60 — Failure: Telegram API outage
1. Telegram API outage occurs
2. Inbound message capture paused
3. Scheduled reminders queued for delivery
4. When Telegram restored, queued reminders delivered

Scenario 61 — Failure: system restart, reminders persist
1. Reminder scheduled
2. System restarts
3. Reminder persists (stored in database)
4. Reminder fires at scheduled time

Scenario 62 — Failure: image processing, all retries exhausted (invalid responses)
1. Image submitted for LLM processing
2. LLM returns invalid responses on all 5 retry attempts
3. Item marked as failed in audit log
4. User notified: "I couldn't generate tags for your image — you can add them manually. [Edit Tags] [Delete]"
5. Image remains as pending memory, subject to 7-day user action window

---

# Delete & Expiry Scenarios

Scenario 63 — Delete: user deletes confirmed memory
1. User has a confirmed memory
2. User taps [Delete] on memory
3. Memory hard deleted from database
4. All associated data (tags, linked tasks/reminders) removed
5. Audit log records deletion

Scenario 64 — Expiry: pending image, no user action for 7 days
1. User sends image
2. Image stored as pending memory with pending_expires_at = now + 7 days
3. User does nothing for 7 days
4. Pending memory and image hard deleted from database
5. Audit log records expiry

Scenario 65 — Expiry: pending text, no user action for 7 days
1. User sends text "The cafe on 5th street has great coffee"
2. LLM classifies as general_note, text stored as pending memory
3. LLM suggests tags, system displays buttons
4. User does not act on any button within 7 days
5. Pending memory hard deleted from database
6. Audit log records expiry

Scenario 66 — Expiry: LLM queue item, 14 days unreachable
1. User sends a message (text or image)
2. Message queued for LLM processing
3. LLM remains unreachable for 14 days
4. Queue item marked as expired
5. If image: pending memory hard deleted from database
6. If text: no memory was saved (never classified)
7. User notified of expiry
8. Audit log records expiry

---

# System Behavior Scenarios

Scenario 67 — System: DM search scoped to user
1. User in DM sends text message
2. Message processed through standard flow
3. After confirmation, search results scoped to requesting user only
4. Other users' data not included in results

Scenario 68 — System: image with inferred location
1. User sends image with caption
2. Vision model suggests location (inferred)
3. Location marked as inferred
4. Only persisted if user confirms

Scenario 69 — System: image confirm tags flow
1. User sends image
2. LLM generates tag suggestions
3. User taps [Confirm Tags]
4. Tags stored as confirmed
5. Memory status changed from pending to confirmed

Scenario 70 — System: image edit tags flow
1. Image sent and stored as pending
2. User taps [Edit Tags]
3. System prompts for manual tag input
4. User enters custom tags
5. Memory confirmed with custom tags

Scenario 71 — System: task linked to memory
1. User creates task from a memory
2. Source memory ID linked to task
3. Task and memory traceable to each other
4. Task completion can reference source

Scenario 72 — System: reminder linked to memory
1. Reminder created from a memory
2. Source memory ID linked to reminder
3. When reminder fires, can reference memory details
4. User gets contextual reminder
