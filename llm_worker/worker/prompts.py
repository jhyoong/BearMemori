"""Prompt templates for LLM Worker handlers."""

IMAGE_TAG_PROMPT = """\
Analyze this image and provide:
1. A brief one-sentence description
2. A list of 3-7 relevant tags (single words or short phrases)

Respond ONLY with valid JSON in this exact format:
{{"description": "A short description of the image", "tags": ["tag1", "tag2", "tag3"]}}"""

INTENT_CLASSIFY_PROMPT = """\
Classify the search intent of this query: "{query}"

Possible intents:
- memory_search: looking for a saved memory or note
- task_lookup: looking for a task or to-do item
- reminder_check: looking for a reminder
- event_search: looking for an event or appointment
- ambiguous: cannot determine intent

Respond ONLY with valid JSON:
{{"intent": "one_of_the_above", "keywords": ["extracted", "keywords"]}}"""

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
