"""Intent classification handler -- classifies search queries."""

import logging
from typing import Any

from worker.handlers.base import BaseHandler
from worker.prompts import INTENT_CLASSIFY_PROMPT
from worker.utils import extract_json

logger = logging.getLogger(__name__)


class IntentHandler(BaseHandler):
    """Classify the intent of a user's search query."""

    async def handle(
        self, job_id: str, payload: dict[str, Any], user_id: int | None
    ) -> dict[str, Any] | None:
        query = payload["query"]

        prompt = INTENT_CLASSIFY_PROMPT.format(query=query)
        raw_response = await self.llm.complete(self.config.llm_text_model, prompt)

        result = extract_json(raw_response)
        intent = result.get("intent", "ambiguous")

        logger.info("Classified query '%s' as intent: %s", query, intent)

        return {
            "query": query,
            "intent": intent,
            "results": [],
        }
