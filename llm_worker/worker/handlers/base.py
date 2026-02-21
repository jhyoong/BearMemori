"""Abstract base handler for LLM job processing."""

from abc import ABC, abstractmethod
from typing import Any

from worker.llm_client import LLMClient
from worker.core_api_client import CoreAPIClient
from worker.config import LLMWorkerSettings


class BaseHandler(ABC):
    """Base class for LLM job handlers.

    Each handler processes a specific job type. It receives a payload,
    calls the LLM, and returns a notification content dict (or None).
    """

    def __init__(
        self,
        llm_client: LLMClient,
        core_api: CoreAPIClient,
        config: LLMWorkerSettings,
    ):
        self.llm = llm_client
        self.core_api = core_api
        self.config = config

    @abstractmethod
    async def handle(
        self, job_id: str, payload: dict[str, Any], user_id: int | None
    ) -> dict[str, Any] | None:
        """Process a job and return notification content.

        Args:
            job_id: The LLM job ID.
            payload: Job-specific payload dict.
            user_id: Telegram user ID (may be None for system jobs).

        Returns:
            Notification content dict for the Telegram consumer,
            or None if no notification should be sent.
        """
