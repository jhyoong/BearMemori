# Plan B: BDD Scenario Fixes (Existing Scenarios)

## Context

Several existing BDD scenarios in `tests/BDD_tests.md` have critical issues: internal contradictions, incomplete steps, and design contradictions with the revised text message flow (queue-first with LLM classification). This plan covers fixing the existing broken scenarios. New scenarios are covered in Plan C.

## Background

The revised text message flow (see Plan A) changes the fundamental behaviour:
- Text messages are queued for LLM classification instead of being saved immediately
- User gets "Processing..." if the queue is empty/idle, or "Added to queue" if the queue has items or is mid-processing
- LLM classifies intent as: reminder, task, search, general_note, or ambiguous
- Search queries are NOT saved as memories
- Ambiguous messages trigger follow-up questions with conversation context tracking

---

## Scenarios to Fix

### Scenario 4 — Rewrite (LLM recovers after image expired)

**Problem:** Says LLM recovers after 14 days, but image is hard-deleted at 7 days per retention policy. The LLM would find nothing to tag.

**Replacement steps:**
1. User sends an image
2. System is available but LLM system is not available
3. Image stored as pending memory, tagging queued for LLM
4. LLM system remains down for 14 days
5. After 7 days with no user interaction, pending memory and image hard deleted
6. LLM recovers on day 14, finds no memory for the queued job
7. LLM job marked as failed, no further action

### Scenario 6 — Rewrite (reminder via queue + LLM classification)

**Problem:** Must align with queue-first flow instead of immediate save.

**Replacement steps:**
1. User sends text "Remind me to buy butter at 6pm"
2. System responds: "Processing..."
3. Text queued for LLM classification
4. LLM classifies intent as "reminder"
5. LLM extracts: action="buy butter", time="6pm today" (resolved from original message timestamp)
6. System saves text as confirmed memory
7. System sends: "Set reminder for 'buy butter' at 6pm today? [Confirm] [Edit time] [Just a note]"
8. User taps [Confirm]
9. Reminder created, linked to memory

### Scenario 7 — Complete (task via queue + LLM classification)

**Problem:** Steps trail off after step 4 with no content.

**Replacement steps:**
1. User sends text "I need to buy butter later at 6pm"
2. System responds: "Processing..."
3. Text queued for LLM classification
4. LLM classifies intent as "task"
5. LLM extracts: description="buy butter", due_time="6pm today"
6. System saves text as confirmed memory
7. System sends: "Create task 'buy butter' due at 6pm today? [Confirm] [Edit] [Just a note]"
8. User taps [Confirm]
9. Task created with due date, linked to memory

### Scenario 8 — Complete (general note with tag suggestions)

**Problem:** Steps trail off after step 4.

**Replacement steps:**
1. User sends text "Best method to get to mount fuji from hakone is take the bus"
2. System responds: "Processing..."
3. Text queued for LLM classification
4. LLM classifies intent as "general_note"
5. System saves text as confirmed memory
6. LLM suggests tags: "travel", "japan", "transport"
7. System sends: "Saved! Suggested tags: travel, japan, transport. [Confirm Tags] [Edit Tags] [Task] [Remind] [Pin] [Delete]"
8. User confirms tags
9. Tags stored as confirmed

### Scenario 9 — Complete (search — no memory saved)

**Problem:** Steps trail off after step 4.

**Replacement steps:**
1. User sends text "When did I last buy butter?"
2. System responds: "Processing..."
3. Text queued for LLM classification
4. LLM classifies intent as "search"
5. Text is NOT saved as a memory
6. System performs search for "butter"
7. Top 3-5 results returned with snippets
8. User taps [Show details] on a result

### Scenario 10 — Complete (ambiguous with follow-up tracking)

**Problem:** Steps trail off after step 5.

**Replacement steps:**
1. User sends text "I need to buy butter later"
2. System responds: "Processing..."
3. Text queued for LLM classification
4. LLM classifies intent as "ambiguous" — unclear if task, reminder, or note
5. System saves text as confirmed memory
6. LLM generates follow-up: "Would you like this as a task or a reminder? And when is 'later'?"
7. System sets conversation context (timeout: 5 minutes)
8. User replies: "A reminder for 6pm"
9. System treats reply as answer to follow-up (not a new message)
10. LLM re-classifies with full context as "reminder"
11. System sends: "Set reminder for 'buy butter' at 6pm today? [Confirm] [Just a note]"
12. User confirms
13. Reminder created, linked to original memory

### Scenario 11 — Rewrite (LLM down, message stays in queue)

**Problem:** Step 2 says "LLM is down" but step 3 says "LLM processes the text message." Internal contradiction.

**Replacement steps:**
1. User sends text "Remind me to do something after work"
2. System responds: "Processing..."
3. Text queued for LLM classification
4. LLM system is down — message stays in queue
5. LLM recovers (within 14-day window)
6. LLM classifies intent as "reminder" but time is ambiguous ("after work")
7. System saves text as confirmed memory
8. System sends follow-up: "I processed your earlier message. When do you finish work?"
9. System sets conversation context
10. User replies: "5pm"
11. LLM extracts time, proposes reminder
12. User confirms

### Scenario 38b — Renumber

**Problem:** Duplicate scenario number (38 already exists).

**Fix:** Renumber 38b to 39 and shift all subsequent scenario numbers by 1.

### Scenario 16 — Revisit TODO header

**Problem:** Has a "TODO: REVISIT" header.

**Fix:** Remove the TODO marker. The new queue-first text flow addresses the concern. Review the scenario content and update if it contradicts the new flow.

---

## Files to Edit

- `tests/BDD_tests.md` — all scenario changes above

## Dependencies

- Plan A (PRD Updates) should be completed first so the BDD scenarios align with the updated PRD.

## Notes

- When editing, preserve the existing formatting style used in BDD_tests.md.
- Verify scenario numbers are sequential after renumbering 38b.
- Cross-reference each rewritten scenario against the revised text flow diagram in Plan A.
- Acknowledgment rule: scenarios with a single message and empty queue use "Processing...". Scenarios where the queue already has items or is mid-processing use "Added to queue". All single-message scenarios (6-11) assume an empty queue, so "Processing..." is correct for those.
