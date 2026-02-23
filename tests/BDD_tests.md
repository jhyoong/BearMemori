# Image input scenarios
Scenario 1
1. User sends an image
2. System is available and running fully
3. LLM processes the image and generates tags
4. System sends proposed tags
5. User confirms tags
6. Memory saved

Scenario 2
1. User sends an image
2. System is available and running fully
3. LLM processes the image and generates tags
4. System sends the proposed tags
5. User rejects the tags
6. System follows up with "key in tags" and "Delete entry"
7. User keys in tags manually
8. Memory saved

Scenario 3
1. User sends an image
2. System is available and not running fully, LLM system is not available.
3. Image is sent to the queue
4. System waits for the LLM system to be available
5. LLM system has recovered
6. LLM processes the image and generates tags
7. System sends proposed tags
8. User confirms tags
9. Memory saved

Scenario 4
1. User sends an image
2. System is available and not running fully, LLM system is not available.
3. Image is sent to the queue
4. System waits for the LLM system to be available
5. LLM system has recovered after 14 days
6. LLM processes the image and generates tags
7. System sends proposed tags
8. User confirms tags
9. Memory saved

Scenario 5
1. User sends an image
2. System is available and running fully
3. Image is sent to the queue
4. LLM processes the image and generates tags
5. System sends proposed tags
6. User did not respond within 7 days
7. Image discarded, no memory saved

# Text input scenarios
Task, Reminder, General text, Search

Scenario 6
1. User sends a text message "Remind me to do something in 5 mins"
2. System is available and running fully
3. LLM processes the text message
4. LLM recognises that it should trigger a reminder tool call
5. Reminder tool call shall be set to 5 minutes from message (input event) timestamp
6. System records this reminder and sets a time trigger
7. Time trigger sends a message to the user


Scenario 7
1. User sends a text message "I need to buy butter later at 6pm"
2. System is available and running fully
3. LLM processes the text message
4. LLM recognises that it should trigger a task tool call
5. 

Scenario 8
1. User sends a text message "Best method to get to mount fuji from hakone is ..."
2. System is available and running fully
3. LLM processes the text message
4. LLM recognises that it should generate tags for this generic text message
5. 

Scenario 9
1. User sends a text message "When did I last buy butter?"
2. System is available and running fully
3. LLM processes the text message
4. LLM recognises that it should trigger search with keywords extracted from text message
5. 

## Ambiguous text input
Scenario 10
1. User sends a text message "I need to buy butter later"
2. System is available and running fully
3. LLM processes the text message
4. LLM recognises that it needs more information, asks for clarity on `later`.
5. Systems sends question from LLM back to user
6. User answers the question
7. LLM proceess the text message
8. LLM recognises that it should trigger a task tool call
9. 


Scenario 11
1. User sends a text message "Remind me to do something after work"
2. System is available and not running fully, LLM system is down
3. LLM processes the text message
4. LLM recognises that it needs more information, asks for clarity on `after work`.
5. 

# Additional Image Input Scenarios

Scenario 12
1. User sends an image
2. System processes image via LLM
3. System sends proposed tags
4. User taps [Pin] button without confirming tags
5. Image confirmed as Memory and pinned
6. Tag suggestions discarded (user chose pin but not tags)
7. Image retained permanently because pin counts as interaction

Scenario 13
1. User sends an image
2. System processes image via LLM
3. System sends proposed tags
4. User taps [Delete] button
5. Image and pending Memory hard deleted from database
6. Audit log records deletion

Scenario 14
1. User sends an image with caption "Receipt for dinner"
2. System processes image via LLM
3. System sends proposed tags and description
4. User taps [Task] button
5. Task created from the image with caption as description
6. Memory linked to task

Scenario 15
1. User sends an image with caption "Receipt for dinner"
2. System processes image via LLM
3. System sends proposed tags
4. User taps [Remind] button
5. System proposes default reminder time
6. User confirms reminder time
7. Reminder scheduled and linked to Memory

# Text Memory Capture Scenarios (TODO: REVISIT THIS REQUIREMENT)

Scenario 16
1. User sends a text message "Meeting with John at 3pm tomorrow"
2. System is available and running fully
3. Text message immediately stored as confirmed Memory
4. No pending status (unlike images)
5. Memory tagged to user's Telegram ID with timestamp

Scenario 17
1. User sends a text message in a group chat
2. System captures the message
3. Message stored as confirmed Memory
4. Memory tagged with sender's user_id and group chat_id

# Inline Actions Scenarios

Scenario 18
1. User sends a text message "Buy groceries"
2. System stores Memory
3. Inline buttons displayed: [Task] [Remind] [Tag] [Pin] [Delete]
4. User taps [Task]
5. Task created with description "Buy groceries"
6. Task linked to source Memory

Scenario 19
1. User sends a text message "Renew passport by March 20"
2. System stores Memory
3. User taps [Remind] button
4. System proposes March 18 at 9am (configurable default)
5. User confirms
6. Reminder scheduled for March 18

Scenario 20
1. User sends a text message "Important contract details"
2. System stores Memory
3. User taps [Tag] button
4. System prompts for tag input
5. User enters tags manually
6. Tags saved to Memory

Scenario 21
1. User sends a text message "Key project deadline"
2. System stores Memory
3. User taps [Pin] button
4. Memory is pinned with search boost
5. Memory appears in /pinned filter

Scenario 22
1. User sends a text message "Temporary note to delete"
2. System stores Memory
3. User taps [Delete] button
4. Memory hard deleted from database
5. Audit log records deletion

# Task Management Scenarios

Scenario 23
1. User creates a task with due date "Submit report" due Feb 20
2. System creates task with status NOT DONE
3. Task has null recurrence_minutes (non-repeatable)
4. Task linked to source Memory

Scenario 24
1. User marks task "Submit report" as DONE
2. System updates task status to DONE
3. Completion timestamp recorded in audit log
4. Task remains in database as DONE

Scenario 25
1. User has task "Take vitamins" with recurrence_minutes: 1440 (daily)
2. Task has due date Feb 10
3. User marks task as DONE
4. Current task marked DONE with completion timestamp
5. New task auto-created: "Take vitamins", due Feb 11, recurrence_minutes: 1440

Scenario 26
1. User has task "Weekly meeting" with recurrence_minutes: 10080 (weekly)
2. Task has due date Feb 15
3. User marks task as DONE
4. New task created with due date Feb 22 (7 days later)

Scenario 27
1. User has task "Call mom" with recurrence_minutes: 4320 (every 3 days)
2. Task has no due date
3. User marks task as DONE
4. New task created with due date = completion_timestamp + 4320 minutes

Scenario 28
1. User has task with no due date and recurrence_minutes set
2. User marks task as DONE
3. New task created with calculated due date from completion time

Scenario 29
1. LLM detects new image relates to existing open task based on keyword overlap
2. System suggests "This looks related to task 'Install shelf'. Mark as DONE?"
3. User taps [Yes]
4. Task marked DONE via deterministic API
5. Completion timestamp recorded
6. New image Memory linked to task

Scenario 30
1. User sends image related to open task
2. LLM suggests task completion
3. User taps [No]
4. Task remains NOT DONE
5. Image stored as Memory

# Reminder Scenarios

Scenario 31
1. User creates reminder "Call dentist" scheduled for Feb 15 at 9am
2. Reminder persisted in database
3. At scheduled time, reminder fires
4. Message sent to user via Telegram

Scenario 32
1. User creates reminder with default time
2. System uses configurable default reminder time (e.g., 9am)
3. Reminder scheduled at default time if user doesn't specify

Scenario 33
1. System restarts
2. Scheduled reminders persist in database
3. Reminders continue firing at scheduled times

Scenario 34
1. User has recurring reminder with recurrence_minutes: 1440
2. Reminder fires at scheduled time
3. Reminder delivered to user
4. New reminder scheduled at previous_fire_time + recurrence_minutes
5. This happens deterministically (no LLM)

Scenario 35
1. User creates one-time reminder (null recurrence_minutes)
2. Reminder fires at scheduled time
3. Reminder marked as fired
4. No new reminder created

# Search & Recall Scenarios

Scenario 36
1. User sends "/find passport renewal"
2. System uses LLM for intent classification
3. LLM classifies as general memory query
4. Keyword/vector search executed
5. Top 3-5 results returned ranked by match and recency
6. Brief snippets displayed

Scenario 37
1. User searches for task-specific query
2. LLM classifies as task query
3. Results filtered to open tasks
4. Results returned with brief snippets

Scenario 38
1. User searches for event-specific query
2. LLM classifies as event query
3. Results filtered to events
4. Results returned

Scenario 38b
1. User sends query with no results
2. LLM generates follow-up question
3. Question sent to user
4. User clarifies query

Scenario 39
1. User has pinned memories
2. User searches for related terms
3. Pinned items ranked higher in results (boost)

Scenario 40
1. User taps [Show details] on search result
2. System returns full stored record
3. If image, actual image sent
4. Includes timestamp, tags, caption, source reference

Scenario 41
1. User searches for terms matching pending image
2. Pending images excluded from results
3. Only confirmed memories returned

Scenario 42
1. User sends vague query "What about the shelf?"
2. Multiple items found (task, image, note)
3. System asks "Which one did you mean?"
4. Options presented to user
5. User selects one
6. Full record returned

# Email Integration Scenarios

Scenario 43
1. Email poller polls inbox
2. Candidate event extracted from email
3. Event sent to user for confirmation via Telegram
4. User taps [Yes]
5. Event stored in database
6. Reminder scheduled
7. Audit log records confirmation

Scenario 44
1. Email poller extracts candidate event
2. User receives confirmation prompt
3. User taps [No]
4. Event discarded
5. Audit log records rejection

Scenario 45
1. Email poller extracts candidate event
2. Confirmation prompt sent to user
3. User does not respond within 24 hours
4. Event re-queued for another prompt
5. Audit log records re-queue

Scenario 46
1. Email poller receives email with date, description, confidence level
2. LLM extracts candidate events
3. Zero or more events generated
4. Each candidate sent to user

# LLM Behavior Scenarios

Scenario 47
1. User sends image
2. Vision model generates suggested tags
3. Tags sent to user as buttons: [Confirm Tags] [Edit Tags]
4. Nothing persisted until user action

Scenario 48
1. LLM processing fails for image
2. Image added to retry queue
3. Image stored as pending Memory without tags
4. Retry happens with exponential backoff
5. User notified if all retries fail (after 5 attempts)

Scenario 49
1. Image pending with tag suggestions
2. User does not act on suggestions within 7 days
3. Tag suggestions discarded
4. If no other action taken, pending Memory and image hard deleted
5. Audit log records expiry

Scenario 50
1. LLM queue has multiple items
2. LLM becomes unavailable
3. Queue items retry with exponential backoff
4. Queue persists across restarts (stored in database)
5. After 5 failed retries, item marked failed in audit log

Scenario 51
1. LLM unavailable during image processing
2. Image still stored as pending Memory
3. Tagging request placed on LLM retry queue
4. User gets message: "I couldn't generate tags — I'll retry shortly"

# Shared Chat Scenarios

Scenario 52
1. User A in shared chat sends message "Dinner at restaurant"
2. User B in same chat sends message "Signed contract"
3. User A searches "dinner"
4. Results include User A's message
5. Results also include User B's message if chat is shared context
6. All users' confirmed Memories searchable

Scenario 53
1. User A sends message in shared chat
2. Message stored with owner_user_id
3. Memory record includes source_chat_id
4. Records tagged for filtering but searchable by all

# Failure Mode Scenarios

Scenario 54
1. LLM is unavailable
2. User sends image
3. Image still stored as pending Memory
4. Tagging paused, added to retry queue
5. Capture continues (text immediate, image pending)

Scenario 55
1. LLM unavailable
2. User sends text message
3. Message stored as confirmed Memory
4. Search query gets keyword fallback (if implementation uses keyword internally)
5. Or search pauses until LLM returns

Scenario 56
1. Telegram API outage
2. Inbound capture paused
3. Scheduled reminders queued
4. When Telegram restored, queued reminders delivered

Scenario 57
1. Database corruption occurs
2. System uses latest S3 backup
3. Full restore performed
4. Up to 7 days data loss acceptable

Scenario 58
1. Reminder scheduled
2. System restarts
3. Reminder persists (stored in database)
4. Reminder fires at scheduled time

Scenario 59
1. Image processing via queue
2. All 5 retries exhausted
3. Item marked as failed in audit log
4. User notified: "I couldn't generate tags for your image — you can add them manually"

# Delete & Expiry Scenarios

Scenario 60
1. User has Memory
2. User taps [Delete] on Memory
3. Memory hard deleted from database
4. All associated data removed
5. Audit log records deletion

Scenario 61
1. User sends image
2. Image stored as pending Memory with pending_expires_at = now + 7 days
3. User does nothing for 7 days
4. Pending Memory and image hard deleted
5. Audit log records expiry

Scenario 62
1. User sends image
2. User pins image (counts as interaction)
3. Even without tag confirmation, image retained permanently
4. Pin confirms the pending image

# System Behavior Scenarios

Scenario 63
1. User in DM sends text message
2. Message stored as confirmed Memory
3. Search scoped to requesting user only
4. Other users' data not included in results

Scenario 64
1. User sends image with caption
2. Vision model also suggests location (inferred)
3. Location marked as inferred
4. Only persisted if user confirms

Scenario 65
1. User sends image
2. User confirms tags via [Confirm Tags]
3. Tags stored as confirmed
4. Memory status changed from pending to confirmed

Scenario 66
1. Image sent and stored as pending
2. User edits tags manually via [Edit Tags]
3. Custom tags saved
4. Memory confirmed (no longer pending)

Scenario 67
1. User creates task from Memory
2. Source Memory ID linked to task
3. Task and Memory traceable to each other
4. Task completion can reference source

Scenario 68
1. Reminder created from Memory
2. Source Memory ID linked to reminder
3. When reminder fires, can reference Memory details
4. User gets contextual reminder

# Additional Edge Cases

Scenario 69
1. User sends very long text message
2. System stores full text
3. Search still works with long content
4. Memory captured in full

Scenario 70
1. User sends image with existing file_id (same image sent twice)
2. System handles file_id reference
3. Actual bytes retrieved via Telegram getFile when needed

Scenario 71
1. Multiple users in group chat
2. Each user's messages captured separately
3. Each message tagged with correct owner_user_id
4. All searchable by all group members