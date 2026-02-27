"""Follow-up question handler -- generates clarifying questions."""

import logging
from typing import Any

from worker.handlers.base import BaseHandler
from worker.prompts import FOLLOWUP_PROMPT

logger = logging.getLogger(__name__)


class FollowupHandler(BaseHandler):
    """Generate a clarifying follow-up question."""

    async def handle(
        self, job_id: str, payload: dict[str, Any], user_id: int | None
    ) -> dict[str, Any] | None:
        message = payload.get("message", "")
        if not message:
            logger.error("Followup job %s missing 'message' in payload: %s", job_id, payload)
            return None
        context = payload.get("context") or payload.get(
            "followup_context", "No additional context available."
        )

        prompt = FOLLOWUP_PROMPT.format(message=message, context=context)
        raw_response = await self.llm.complete(self.config.llm_text_model, prompt)

        question = raw_response.strip()
        logger.info("Generated followup question: %s", question[:80])

        return {"question": question}
