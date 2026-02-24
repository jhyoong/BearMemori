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

Scenario 57
1. Database corruption occurs
2. System uses latest S3 backup
3. Full restore performed
4. Up to 7 days data loss acceptable

# Shared Chat Scenarios

Scenario 53
1. User A in shared chat sends message "Dinner at restaurant"
2. User B in same chat sends message "Signed contract"
3. User A searches "dinner"
4. Results include User A's message
5. Results also include User B's message if chat is shared context
6. All users' confirmed Memories searchable

Scenario 54
1. User A sends message in shared chat
2. Message stored with owner_user_id
3. Memory record includes source_chat_id
4. Records tagged for filtering but searchable by all

# Email Integration Scenarios

Scenario 44
1. Email poller polls inbox
2. Candidate event extracted from email
3. Event sent to user for confirmation via Telegram
4. User taps [Yes]
5. Event stored in database
6. Reminder scheduled
7. Audit log records confirmation

Scenario 45
1. Email poller extracts candidate event
2. User receives confirmation prompt
3. User taps [No]
4. Event discarded
5. Audit log records rejection

Scenario 46
1. Email poller extracts candidate event
2. Confirmation prompt sent to user
3. User does not respond within 24 hours
4. Event re-queued for another prompt
5. Audit log records re-queue

Scenario 47
1. Email poller receives email with date, description, confidence level
2. LLM extracts candidate events
3. Zero or more events generated
4. Each candidate sent to user