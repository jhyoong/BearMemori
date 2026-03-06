"""Prompt templates for LLM Worker handlers."""

IMAGE_TAG_PROMPT = """\
Analyze this image and provide:
1. A brief one-sentence description
2. A list of 3-7 relevant tags (single words or short phrases)

Respond ONLY with valid JSON in this exact format:
{{"description": "A short description of the image", "tags": ["tag1", "tag2", "tag3"]}}"""

INTENT_CLASSIFY_PROMPT = """\
Classify the intent of this user message and extract structured entities.

User message: {message}
Original timestamp: {original_timestamp}
User timezone: {user_timezone}

Possible intents:
- reminder: user wants to be reminded about something at a specific time
- task: user wants to create a task or to-do item with a due date
- search: user is searching for a memory, note, or past information
- general_note: user is saving a general note or thought without specific time/action requirements
- ambiguous: cannot determine intent with confidence, need more context

CRITICAL RULES FOR INTENT CLASSIFICATION:
- reminder: ONLY return this intent if the message contains an EXPLICIT time reference (e.g., "at 5pm", "tomorrow", "in 30 minutes", "next week", "on Monday"). If no explicit time is mentioned, return "ambiguous".
- task: ONLY return this intent if the message contains an EXPLICIT due date/deadline (e.g., "due tomorrow", "due on Friday", "due next week"). If no explicit due date is mentioned, return "ambiguous".
- NEVER make up a time or date. If the message lacks explicit time information, you MUST return "ambiguous".
- Examples of messages that should be "ambiguous": "remind me", "remind me about the meeting", "remind me to call mom", "create a task", "add a todo". These have no specific time/deadline.
- Examples of valid "reminder": "remind me in 10 minutes", "remind me tomorrow at 3pm", "remind me on Monday at 9am".
- Examples of valid "task": "task to submit report due tomorrow", "todo due Friday", "task due next week".

For each intent, extract the following structured entities:

If intent is "reminder":
{{"intent": "reminder", "action": "what the user wants to be reminded about", "time": "raw time reference from message", "resolved_time": "absolute ISO8601 datetime in UTC. For relative times (e.g. 'in 10 minutes'), add offset to original_timestamp. For absolute times (e.g. 'at 5pm'), interpret in user_timezone and convert to UTC."}}

If intent is "task":
{{"intent": "task", "description": "task description", "due_time": "raw due date from message", "resolved_due_time": "absolute ISO8601 datetime in UTC. For relative times (e.g. 'due tomorrow'), add offset to original_timestamp. For absolute times (e.g. 'due at 5pm'), interpret in user_timezone and convert to UTC."}}

If intent is "search":
{{"intent": "search", "query": "search query", "keywords": ["extracted", "keywords"]}}

If intent is "general_note":
{{"intent": "general_note", "suggested_tags": ["relevant", "tags"]}}

If intent is "ambiguous":
{{"intent": "ambiguous", "followup_question": "natural follow-up question to clarify intent", "possible_intents": ["list", "of", "possible", "intents"]}}

CRITICAL: When resolving time references, use the provided user_timezone ({user_timezone})
to convert to UTC. For absolute times like "5pm" or "at 10pm", interpret them in the
user's timezone and convert to UTC. For example, if user_timezone is "Asia/Singapore"
(UTC+8) and user says "at 10pm", resolved_time = 2026-03-05T14:00:00Z (10pm SGT = 22:00 - 8h = 14:00 UTC).
For relative times like "in 10 minutes", add the offset to original_timestamp.
Do NOT assume times are in UTC - always use the provided user_timezone.
NEVER return the original_timestamp unchanged - always compute the correct resolved time.
If the resolved time would be in the past relative to the original_timestamp, resolve to
the NEXT future occurrence. For example, if it is 7pm on March 6 and the user says
"at 3pm", resolve to 3pm on March 7 (not March 6, which is already past).
Similarly, "at 11" when current time is 7pm should resolve to 11am the next day.
Generate a natural, conversational follow-up question for ambiguous intents.

Respond ONLY with valid JSON in the appropriate format above."""

RECLASSIFY_PROMPT = """\
The user originally sent: {original_message}
A clarifying question was asked: {followup_question}
The user answered: {user_answer}
Original timestamp: {original_timestamp}
User timezone: {user_timezone}

CRITICAL: When resolving time references like "5pm", use the provided
user_timezone ({user_timezone}) to convert to UTC. For example, if
user_timezone is "Asia/Singapore" and user says "5pm", the resolved
time should be computed as 5pm in Singapore = 17:00 - 8 hours = 09:00 UTC.
Do NOT assume times are in UTC - always use the provided user_timezone.
If the resolved time would be in the past relative to the original_timestamp, resolve to
the NEXT future occurrence. For example, if it is 7pm on March 6 and the user says
"at 3pm", resolve to 3pm on March 7 (not March 6, which is already past).
Similarly, "at 11" when current time is 7pm should resolve to 11am the next day.

Based on this conversation context, re-classify the intent and extract entities.

CRITICAL RULES FOR INTENT CLASSIFICATION:
- reminder: ONLY return this intent if the message contains an EXPLICIT time reference (e.g., "at 5pm", "tomorrow", "in 30 minutes", "next week", "on Monday"). If no explicit time is mentioned, return "ambiguous".
- task: ONLY return this intent if the message contains an EXPLICIT due date/deadline (e.g., "due tomorrow", "due on Friday", "due next week"). If no explicit due date is mentioned, return "ambiguous".
- NEVER make up a time or date. If the message lacks explicit time information, you MUST return "ambiguous".
- Use the user's answer to the follow-up question to extract the missing time/deadline information.

Possible intents:
- reminder: user wants to be reminded about something at a specific time
- task: user wants to create a task or to-do item with a due date
- search: user is searching for a memory, note, or past information
- general_note: user is saving a general note or thought without specific time/action requirements
- ambiguous: cannot determine intent with confidence, need more context

For each intent, extract the following structured entities:

If intent is "reminder":
{{"intent": "reminder", "action": "what the user wants to be reminded about", "time": "raw time reference from message", "resolved_time": "absolute ISO8601 datetime (original_timestamp PLUS the relative offset). For example, if original_timestamp is 2026-03-04T10:00:00Z and user says 'in 10 minutes', resolved_time must be 2026-03-04T10:10:00Z. NEVER return the original_timestamp unchanged."}}

If intent is "task":
{{"intent": "task", "description": "task description", "due_time": "raw due date from message", "resolved_due_time": "absolute ISO8601 datetime (original_timestamp PLUS the relative offset). For example, if original_timestamp is 2026-03-04T10:00:00Z and user says 'due tomorrow', resolved_due_time must be 2026-03-05T10:00:00Z. NEVER return the original_timestamp unchanged."}}

If intent is "search":
{{"intent": "search", "query": "search query", "keywords": ["extracted", "keywords"]}}

If intent is "general_note":
{{"intent": "general_note", "suggested_tags": ["relevant", "tags"]}}

If intent is "ambiguous":
{{"intent": "ambiguous", "followup_question": "natural follow-up question to clarify intent", "possible_intents": ["list", "of", "possible", "intents"]}}

Use the full conversation context to make a more accurate classification.

Respond ONLY with valid JSON in the appropriate format above."""

FOLLOWUP_PROMPT = """\
The user searched for: "{message}"
Context from their recent data: {context}

The search returned few or no results. Generate a single clarifying \
follow-up question to help narrow down what the user is looking for.
Respond with ONLY the question text, nothing else."""

TASK_MATCH_PROMPT = """\
A user just saved this new memory: "{memory_content}"

Their open tasks are:
{tasks_list}

Does this new memory indicate that any of these tasks might be completed?
Respond ONLY with valid JSON:
{{"matched_task_id": "the_task_id_or_null", "confidence": 0.0, "reason": "brief explanation"}}

If no task matches, set matched_task_id to null and confidence to 0.0."""

EMAIL_EXTRACT_PROMPT = """\
Extract any calendar events or appointments from this email.

Subject: {subject}
Body:
{body}

Respond ONLY with valid JSON:
{{"events": [{{"description": "event description", "event_time": "ISO8601 datetime", "confidence": 0.8}}]}}

If no events are found, return {{"events": []}}."""
