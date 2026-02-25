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

Possible intents:
- reminder: user wants to be reminded about something at a specific time
- task: user wants to create a task or to-do item with a due date
- search: user is searching for a memory, note, or past information
- general_note: user is saving a general note or thought without specific time/action requirements
- ambiguous: cannot determine intent with confidence, need more context

For each intent, extract the following structured entities:

If intent is "reminder":
{{"intent": "reminder", "action": "what the user wants to be reminded about", "time": "raw time reference from message", "resolved_time": "absolute ISO8601 datetime resolved relative to original_timestamp"}}

If intent is "task":
{{"intent": "task", "description": "task description", "due_time": "raw due date from message", "resolved_due_time": "absolute ISO8601 datetime resolved relative to original_timestamp"}}

If intent is "search":
{{"intent": "search", "query": "search query", "keywords": ["extracted", "keywords"]}}

If intent is "general_note":
{{"intent": "general_note", "suggested_tags": ["relevant", "tags"]}}

If intent is "ambiguous":
{{"intent": "ambiguous", "followup_question": "natural follow-up question to clarify intent", "possible_intents": ["list", "of", "possible", "intents"]}}

Resolve relative time references (like "tomorrow", "next week", "in 2 hours") to absolute ISO8601 datetimes relative to the original_timestamp provided.
Generate a natural, conversational follow-up question for ambiguous intents.

Respond ONLY with valid JSON in the appropriate format above."""

RECLASSIFY_PROMPT = """\
The user originally sent: {original_message}
A clarifying question was asked: {followup_question}
The user answered: {user_answer}
Original timestamp: {original_timestamp}

Based on this conversation context, re-classify the intent and extract entities.

Possible intents:
- reminder: user wants to be reminded about something at a specific time
- task: user wants to create a task or to-do item with a due date
- search: user is searching for a memory, note, or past information
- general_note: user is saving a general note or thought without specific time/action requirements
- ambiguous: cannot determine intent with confidence, need more context

For each intent, extract the following structured entities:

If intent is "reminder":
{{"intent": "reminder", "action": "what the user wants to be reminded about", "time": "raw time reference from message", "resolved_time": "absolute ISO8601 datetime resolved relative to original_timestamp"}}

If intent is "task":
{{"intent": "task", "description": "task description", "due_time": "raw due date from message", "resolved_due_time": "absolute ISO8601 datetime resolved relative to original_timestamp"}}

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
