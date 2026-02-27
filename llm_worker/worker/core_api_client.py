"""HTTP client for Core REST API."""

import logging
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)


class CoreAPIError(Exception):
    """Raised when a Core API call fails."""


class CoreAPIClient:
    """Async HTTP client for Core service REST API."""

    def __init__(self, base_url: str, session: aiohttp.ClientSession):
        self._base_url = base_url.rstrip("/")
        self._session = session

    async def update_job(
        self,
        job_id: str,
        status: str,
        result: dict[str, Any] | None = None,
        error_message: str | None = None,
    ) -> None:
        """Update an LLM job via PATCH /llm_jobs/{job_id}."""
        body: dict[str, Any] = {"status": status}
        if result is not None:
            body["result"] = result
        if error_message is not None:
            body["error_message"] = error_message
        url = f"{self._base_url}/llm_jobs/{job_id}"
        async with self._session.patch(url, json=body) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise CoreAPIError(f"PATCH {url} returned {resp.status}: {text}")

    async def add_tags(
        self,
        memory_id: str,
        tags: list[str],
        status: str = "suggested",
    ) -> None:
        """Add tags to a memory via POST /memories/{memory_id}/tags."""
        url = f"{self._base_url}/memories/{memory_id}/tags"
        async with self._session.post(
            url, json={"tags": tags, "status": status}
        ) as resp:
            if resp.status not in (200, 201):
                text = await resp.text()
                raise CoreAPIError(f"POST {url} returned {resp.status}: {text}")

    async def create_event(self, event_data: dict[str, Any]) -> dict[str, Any]:
        """Create a pending event via POST /events."""
        url = f"{self._base_url}/events"
        async with self._session.post(url, json=event_data) as resp:
            if resp.status != 201:
                text = await resp.text()
                raise CoreAPIError(f"POST {url} returned {resp.status}: {text}")
            return await resp.json()

    async def get_open_tasks(self, user_id: int) -> list[dict[str, Any]]:
        """Get open tasks for a user via GET /tasks."""
        url = f"{self._base_url}/tasks"
        params = {"owner_user_id": user_id, "state": "NOT_DONE"}
        async with self._session.get(url, params=params) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise CoreAPIError(f"GET {url} returned {resp.status}: {text}")
            return await resp.json()

    async def search(self, query: str, owner_user_id: int) -> list[dict[str, Any]]:
        """Search memories via GET /search."""
        url = f"{self._base_url}/search"
        params = {"q": query, "owner": owner_user_id}
        async with self._session.get(url, params=params) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise CoreAPIError(f"GET {url} returned {resp.status}: {text}")
            return await resp.json()
