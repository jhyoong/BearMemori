# Plan C: BDD New Scenarios

## Context

The revised queue-first text message flow introduces several new behaviours that have no BDD coverage. This plan adds 9 new scenarios to `tests/BDD_tests.md`. These should be added after the existing scenarios are fixed (Plan B).

## Background

Key new behaviours that need coverage:
- Follow-up context expiry (user does not reply to LLM follow-up)
- Tag suggestions on general text notes
- Stale queued messages (time-relative content processed days later)
- Queue expiry after 14 days
- Flood control after LLM outage recovery
- Multiple messages in queue with various interaction patterns
- One-at-a-time processing with pause/resume semantics
- Acknowledgment rule: "Processing..." when queue is empty/idle; "Added to queue" when queue has items or is mid-processing

---

## New Scenarios to Add

### New Scenario: Follow-up context expiry
1. User sends text "I need to do something later"
2. System responds: "Processing..."
3. LLM classifies as ambiguous, asks follow-up question
4. System sets conversation context with 5-minute timeout
5. User does not reply within 5 minutes
6. Context expires
7. Original text remains saved as confirmed memory with no additional action
8. User's next message is treated as a new message

### New Scenario: Text tag suggestions (general note)
1. User sends text "The cafe on 5th street has great coffee"
2. System responds: "Processing..."
3. LLM classifies as general_note
4. Text saved as confirmed memory
5. LLM suggests tags: "cafe", "coffee", "food"
6. System shows tag suggestions with [Confirm Tags] [Edit Tags]
7. User does not act on tag suggestions within 7 days
8. Suggested tags are discarded
9. Memory remains (text memories are not subject to the 7-day image deletion rule)

### New Scenario: Stale queued message
1. User sends text "Remind me to call the dentist tomorrow" on Feb 10
2. System responds: "Processing..."
3. LLM is down — message stays in queue
4. LLM recovers on Feb 17
5. LLM processes message, resolves "tomorrow" relative to Feb 10 = Feb 11
6. Feb 11 is in the past
7. System saves text as confirmed memory
8. System sends: "Your message from Feb 10 mentioned a reminder for Feb 11, which has passed. [Reschedule] [Dismiss]"
9. User taps [Reschedule] and picks a new date
10. Reminder created with new date

### New Scenario: Queue expiry (14 days)
1. User sends text "Buy groceries"
2. System responds: "Processing..."
3. LLM is down — message stays in queue
4. After 14 days, message expires in queue
5. System marks job as expired
6. System notifies user: "Your message 'Buy groceries' from [date] could not be processed and has expired."
7. No memory is saved (text was never classified)

### New Scenario: Flood control after outage
1. LLM has been down for 3 days
2. 15 text messages are queued
3. LLM recovers
4. System processes messages in order (oldest first), one at a time
5. Each result delivered with 5-10 second delay before the next message is processed
6. User receives each result as an individual follow-up message

### New Scenario: Two ambiguous messages in sequence
1. User sends text "I need to buy butter later"
2. System responds: "Processing..." (queue was empty)
3. User immediately sends text "Pick up the kids sometime"
4. System responds: "Added to queue" (queue is mid-processing)
5. LLM processes first message, classifies as ambiguous
6. System asks follow-up: "Would you like this as a task or a reminder? When is 'later'?"
7. Queue paused — second message waits
8. User replies: "A reminder for 6pm"
9. LLM re-classifies first message as reminder, proposes it
10. User confirms reminder
11. Conversation resolved — queue resumes
12. LLM processes second message "Pick up the kids sometime", classifies as ambiguous
13. System asks follow-up for second message
14. Process continues

### New Scenario: Follow-up reply while queue has backlog
1. User sends 3 text messages in quick succession
2. System responds "Processing..." to message 1, "Added to queue" to messages 2 and 3
3. LLM processes message 1, classifies as ambiguous, asks follow-up
4. Queue paused — messages 2 and 3 wait
5. User sends reply to follow-up question
6. Reply is treated as answer to the follow-up (not added to queue as message 4)
7. LLM re-classifies message 1 with the answer, resolves it
8. Conversation resolved — queue resumes with message 2

### New Scenario: Follow-up timeout with queued messages
1. User sends 2 text messages
2. System responds "Processing..." to message 1, "Added to queue" to message 2
3. LLM processes message 1, classifies as ambiguous, asks follow-up
4. Queue paused — message 2 waits
5. User does not reply within 5 minutes
6. Follow-up context expires
7. Message 1 remains saved as confirmed memory with no additional action
8. Queue resumes — LLM processes message 2

### New Scenario: Clear classification in backlog (no pause)
1. User sends 3 text messages in quick succession:
   - "Remind me to call the dentist at 3pm"
   - "The best pizza place in town is Mario's"
   - "When did I last go to the gym?"
2. System responds "Processing..." to message 1, "Added to queue" to messages 2 and 3
3. LLM processes message 1: classifies as "reminder", proposes it — conversation resolved immediately
4. After delay, LLM processes message 2: classifies as "general_note", saves + suggests tags — resolved immediately
5. After delay, LLM processes message 3: classifies as "search", returns results — resolved immediately
6. No pauses because no message was ambiguous

---

## Files to Edit

- `tests/BDD_tests.md` — add all new scenarios above

## Dependencies

- Plan B (BDD Scenario Fixes) should be completed first so scenario numbering is correct.
- Plan A (PRD Updates) should be completed first so scenarios align with the PRD.

## Notes

- Number the new scenarios sequentially after the last existing scenario (post-renumbering from Plan B).
- Use the same formatting style as existing scenarios in BDD_tests.md.
- Each scenario should have a clear, descriptive title.
