"""Email event extraction handler -- extracts events from emails."""

import logging
from typing import Any

from worker.handlers.base import BaseHandler
from worker.prompts import EMAIL_EXTRACT_PROMPT
from worker.utils import extract_json

logger = logging.getLogger(__name__)


class EmailExtractHandler(BaseHandler):
    """Extract calendar events from email content."""

    async def handle(
        self, job_id: str, payload: dict[str, Any], user_id: int | None
    ) -> dict[str, Any] | None:
        subject = payload["subject"]
        body = payload["body"]

        prompt = EMAIL_EXTRACT_PROMPT.format(subject=subject, body=body)
        raw_response = await self.llm.complete(self.config.llm_text_model, prompt)

        result = extract_json(raw_response)
        events = result.get("events", [])

        # Filter to high-confidence events and create them in Core
        first_event_notification = None
        for event in events:
            confidence = event.get("confidence", 0.0)
            if confidence <= 0.7:
                continue

            event_data = {
                "owner_user_id": user_id,
                "event_time": event["event_time"],
                "description": event["description"],
                "source_type": "email",
                "source_detail": subject,
            }
            await self.core_api.create_event(event_data)

            # Use the first high-confidence event for the notification
            if first_event_notification is None:
                first_event_notification = {
                    "description": event["description"],
                    "event_date": event["event_time"],
                }

        if first_event_notification:
            logger.info(
                "Extracted %d events from email '%s'",
                len([e for e in events if e.get("confidence", 0) > 0.7]),
                subject[:50],
            )
        else:
            logger.info("No high-confidence events in email '%s'", subject[:50])

        return first_event_notification
