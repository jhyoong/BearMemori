"""Task match handler -- suggests task completion based on new memories."""

import logging
from typing import Any

from worker.handlers.base import BaseHandler
from worker.prompts import TASK_MATCH_PROMPT
from worker.utils import extract_json

logger = logging.getLogger(__name__)


class TaskMatchHandler(BaseHandler):
    """Check if a new memory indicates an open task is done."""

    async def handle(
        self, job_id: str, payload: dict[str, Any], user_id: int | None
    ) -> dict[str, Any] | None:
        memory_id = payload["memory_id"]
        memory_content = payload["memory_content"]

        # Fetch open tasks from Core API
        tasks = await self.core_api.get_open_tasks(user_id)
        if not tasks:
            logger.info("No open tasks for user %s, skipping match", user_id)
            return None

        # Format task list for the prompt
        tasks_list = "\n".join(
            f"- ID: {t['id']}, Description: {t['description']}" for t in tasks
        )

        prompt = TASK_MATCH_PROMPT.format(
            memory_content=memory_content, tasks_list=tasks_list
        )
        raw_response = await self.llm.complete(prompt, self.config.llm_text_model)

        result = extract_json(raw_response)
        matched_id = result.get("matched_task_id")
        confidence = result.get("confidence", 0.0)

        if matched_id and confidence > 0.7:
            # Find the task description
            task_desc = ""
            for t in tasks:
                if t["id"] == matched_id:
                    task_desc = t["description"]
                    break

            logger.info(
                "Matched memory %s to task %s (confidence: %.2f)",
                memory_id,
                matched_id,
                confidence,
            )
            return {
                "task_id": matched_id,
                "task_description": task_desc,
                "memory_id": memory_id,
            }

        logger.info(
            "No confident task match for memory %s (best: %s at %.2f)",
            memory_id,
            matched_id,
            confidence,
        )
        return None
