"""Intent classification handler -- classifies search queries."""

import logging
from datetime import datetime, timezone
from typing import Any

from worker.handlers.base import BaseHandler
from worker.prompts import INTENT_CLASSIFY_PROMPT, RECLASSIFY_PROMPT
from worker.utils import extract_json

logger = logging.getLogger(__name__)


class IntentHandler(BaseHandler):
    """Classify the intent of a user's search query."""

    async def handle(
        self, job_id: str, payload: dict[str, Any], user_id: int | None
    ) -> dict[str, Any] | None:
        # Extract message from payload (support both 'message' and 'query' for backward compatibility)
        message = payload.get("message") or payload.get("query")
        memory_id = payload.get("memory_id", "")
        original_timestamp = payload.get("original_timestamp")
        followup_context = payload.get("followup_context")

        # Determine if using legacy format (only 'query', no 'original_timestamp')
        is_legacy = "query" in payload and "original_timestamp" not in payload

        # Determine which prompt to use
        if followup_context:
            # Use RECLASSIFY_PROMPT with followup context
            followup_question = followup_context.get("followup_question", "")
            user_answer = followup_context.get("user_answer", "")
            prompt = RECLASSIFY_PROMPT.format(
                original_message=message,
                followup_question=followup_question,
                user_answer=user_answer,
                original_timestamp=original_timestamp or "",
            )
        else:
            # Use standard INTENT_CLASSIFY_PROMPT
            prompt = INTENT_CLASSIFY_PROMPT.format(
                message=message,
                original_timestamp=original_timestamp or "",
            )

        logger.info(
            "Intent classify request: message=%r, memory_id=%s, has_followup=%s",
            message, memory_id, bool(followup_context),
        )
        logger.debug("Intent classify prompt:\n%s", prompt)

        raw_response = await self.llm.complete(self.config.llm_text_model, prompt)
        logger.info("Intent classify raw LLM response:\n%s", raw_response)

        result = extract_json(raw_response)
        logger.info("Intent classify parsed JSON: %s", result)

        intent = result.get("intent", "ambiguous")
        logger.info("Classified query %r as intent: %s", message, intent)

        # For non-search intents (reminder, task, general_note, ambiguous), create memory
        # For search intents, no memory should be created (search is self-contained)
        memory_id = None
        if intent in ("reminder", "task", "general_note", "ambiguous"):
            memory_response = await self.core_api.create_memory(
                content=message, owner_user_id=user_id
            )
            memory_id = memory_response.get("memory_id")

        # For legacy format (old 'query' only, no 'original_timestamp'), maintain old behavior
        # But if search intent, still call the search API
        if is_legacy:
            if intent == "search":
                # Extract keywords from LLM response and call Core API search endpoint
                keywords = result.get("keywords", [])
                if isinstance(keywords, list):
                    search_query = " ".join(keywords)
                else:
                    search_query = str(keywords)
                logger.info(
                    "Legacy search: keywords=%s, search_query=%r, user_id=%s",
                    keywords, search_query, user_id,
                )
                raw_results = await self.core_api.search(
                    search_query, owner_user_id=user_id
                )
                logger.info(
                    "Legacy search returned %d results", len(raw_results)
                )
                return {
                    "query": message,
                    "intent": intent,
                    "results": self._normalize_search_results(raw_results),
                }
            return {
                "query": message,
                "intent": intent,
                "results": [],
            }

        # Build the full structured response for new format
        structured_result = {
            "query": message,
            "intent": intent,
            "memory_id": memory_id,
            "results": [],
        }

        # Add all fields from the LLM response
        for key, value in result.items():
            if key != "intent":
                structured_result[key] = value

        # Handle stale flag for reminder and task intents
        if intent == "reminder":
            resolved_time = result.get("resolved_time")
            if resolved_time and self._is_stale(resolved_time):
                structured_result["stale"] = True
        elif intent == "task":
            resolved_due_time = result.get("resolved_due_time")
            if resolved_due_time and self._is_stale(resolved_due_time):
                structured_result["stale"] = True
        elif intent == "search":
            # Extract keywords from LLM response and call Core API search endpoint
            keywords = result.get("keywords", [])
            if isinstance(keywords, list):
                search_query = " ".join(keywords)
            else:
                search_query = str(keywords)
            logger.info(
                "Search: keywords=%s, search_query=%r, user_id=%s",
                keywords, search_query, user_id,
            )
            raw_results = await self.core_api.search(
                search_query, owner_user_id=user_id
            )
            logger.info("Search returned %d results: %s", len(raw_results), raw_results)
            structured_result["results"] = self._normalize_search_results(raw_results)

        return structured_result

    def _normalize_search_results(self, raw_results: list) -> list[dict]:
        """Normalize MemorySearchResult format from Core API to flat display format.

        Core API returns: [{"memory": {"id": "...", "content": "..."}, "score": 0.9}]
        Telegram consumer expects: [{"memory_id": "...", "title": "..."}]
        """
        normalized = []
        for r in raw_results:
            mem = r.get("memory", {})
            if mem:
                title = mem.get("content") or ""
                if not title:
                    # Fall back to tags for image memories with no content
                    tags = mem.get("tags", [])
                    if tags:
                        tag_names = [
                            t["tag"] if isinstance(t, dict) else t
                            for t in tags
                        ]
                        title = ", ".join(tag_names[:3])
                        if len(tag_names) > 3:
                            title += f" (+{len(tag_names) - 3} more)"
                if not title:
                    title = "Untitled"
                # Prefix image memories so the user knows it's a photo
                if mem.get("media_type") == "image":
                    title = f"[Image] {title}"
                normalized.append(
                    {
                        "memory_id": mem.get("id", ""),
                        "title": title,
                    }
                )
            else:
                # Already flat format — pass through unchanged
                normalized.append(r)
        return normalized

    def _is_stale(self, time_str: str) -> bool:
        """Check if the given timestamp is in the past relative to current time.

        Args:
            time_str: ISO8601 datetime string.

        Returns:
            True if the timestamp is in the past, False otherwise.
        """
        if not time_str:
            return False

        try:
            # Parse the ISO8601 timestamp
            # Handle various formats that might be returned
            time_str_stripped = time_str.strip()

            # Handle common malformed formats
            # Try to parse the timestamp
            if time_str_stripped.endswith("Z"):
                # Format: 2026-02-25T10:00:00Z
                dt = datetime.fromisoformat(time_str_stripped.replace("Z", "+00:00"))
            elif time_str_stripped.endswith("UTC"):
                # Format: 2026-02-22T14:07:UTC (malformed - missing seconds)
                # This is produced by strftime("%Y-%m-%dT%H:%M:%Z")
                # Parse as UTC timezone
                # Replace UTC with +00:00 and parse
                cleaned = time_str_stripped.replace("UTC", "+00:00")
                dt = datetime.fromisoformat(cleaned)
            elif "UTC" in time_str_stripped:
                # Handle any other UTC variant
                cleaned = time_str_stripped.replace("UTC", "+00:00")
                dt = datetime.fromisoformat(cleaned)
            else:
                dt = datetime.fromisoformat(time_str_stripped)

            # Make sure timezone aware for comparison
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)

            # Compare with current UTC time
            now = datetime.now(timezone.utc)
            return dt < now
        except (ValueError, TypeError):
            # If we can't parse, assume not stale
            return False
