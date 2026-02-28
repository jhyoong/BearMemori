"""Image tagging handler -- uses vision model to suggest tags."""

import base64
import logging
from pathlib import Path
from typing import Any

from worker.handlers.base import BaseHandler
from worker.prompts import IMAGE_TAG_PROMPT
from worker.utils import extract_json

logger = logging.getLogger(__name__)


class ImageTagHandler(BaseHandler):
    """Process image_tag jobs using a vision LLM."""

    async def handle(
        self, job_id: str, payload: dict[str, Any], user_id: int | None
    ) -> dict[str, Any] | None:
        memory_id = payload["memory_id"]
        image_path = payload["image_path"]

        # Read and encode image
        image_bytes = Path(image_path).read_bytes()
        image_b64 = base64.b64encode(image_bytes).decode("utf-8")

        # Call vision model
        logger.info("Image tag request: memory_id=%s, image_path=%s", memory_id, image_path)
        raw_response = await self.llm.complete_with_image(
            self.config.llm_vision_model, IMAGE_TAG_PROMPT, image_b64
        )
        logger.info("Image tag raw LLM response:\n%s", raw_response)

        # Parse structured response
        result = extract_json(raw_response)
        logger.info("Image tag parsed JSON: %s", result)
        tags = result.get("tags", [])
        description = result.get("description", "")

        # Persist suggested tags in Core API
        if tags:
            await self.core_api.add_tags(
                memory_id=memory_id, tags=tags, status="suggested"
            )

        logger.info(
            "Tagged memory %s with %d tags: %s",
            memory_id,
            len(tags),
            tags,
        )

        return {
            "memory_id": memory_id,
            "tags": tags,
            "description": description,
        }
