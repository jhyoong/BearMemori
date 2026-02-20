import logging
from httpx import AsyncClient, ConnectError, TimeoutException

from shared_lib.schemas import (
    LLMJobCreate,
    LLMJobResponse,
    MemoryCreate,
    MemorySearchResult,
    MemoryUpdate,
    MemoryResponse,
    MemoryWithTags,
    ReminderCreate,
    ReminderResponse,
    TagsAddRequest,
    TaskCreate,
    TaskUpdate,
    TaskResponse,
    UserSettingsResponse,
)

logger = logging.getLogger(__name__)


class CoreClientError(Exception):
    """Base exception for all Core API errors."""

    pass


class CoreUnavailableError(CoreClientError):
    """Core is unreachable (connection error, timeout)."""

    pass


class CoreNotFoundError(CoreClientError):
    """Entity not found (404 response)."""

    pass


class CoreClient:
    def __init__(self, base_url: str, timeout: float = 10.0):
        self._client = AsyncClient(base_url=base_url, timeout=timeout)

    async def close(self):
        """Close the HTTP client."""
        await self._client.aclose()

    async def create_memory(self, data: MemoryCreate) -> MemoryResponse:
        """Create a new memory."""
        try:
            response = await self._client.post(
                "/memories",
                json=data.model_dump(exclude_none=True),
            )
        except (ConnectError, TimeoutException) as e:
            logger.exception("Failed to connect to Core API")
            raise CoreUnavailableError(f"Core API unavailable: {e}") from e

        if response.status_code == 404:
            raise CoreNotFoundError("Memory not found")

        if not response.is_success:
            logger.error(
                f"Failed to create memory: {response.status_code} {response.text}"
            )
            raise CoreClientError(
                f"Failed to create memory: {response.status_code} {response.text}"
            )

        return MemoryResponse.model_validate(response.json())

    async def get_memory(self, memory_id: str) -> MemoryWithTags | None:
        """Get a memory by ID. Returns None on 404."""
        try:
            response = await self._client.get(f"/memories/{memory_id}")
        except (ConnectError, TimeoutException) as e:
            logger.exception("Failed to connect to Core API")
            raise CoreUnavailableError(f"Core API unavailable: {e}") from e

        if response.status_code == 404:
            return None

        if not response.is_success:
            logger.error(
                f"Failed to get memory: {response.status_code} {response.text}"
            )
            raise CoreClientError(
                f"Failed to get memory: {response.status_code} {response.text}"
            )

        return MemoryWithTags.model_validate(response.json())

    async def update_memory(self, memory_id: str, data: MemoryUpdate) -> MemoryResponse:
        """Update an existing memory."""
        try:
            response = await self._client.patch(
                f"/memories/{memory_id}",
                json=data.model_dump(exclude_none=True),
            )
        except (ConnectError, TimeoutException) as e:
            logger.exception("Failed to connect to Core API")
            raise CoreUnavailableError(f"Core API unavailable: {e}") from e

        if response.status_code == 404:
            raise CoreNotFoundError(f"Memory {memory_id} not found")

        if not response.is_success:
            logger.error(
                f"Failed to update memory: {response.status_code} {response.text}"
            )
            raise CoreClientError(
                f"Failed to update memory: {response.status_code} {response.text}"
            )

        return MemoryResponse.model_validate(response.json())

    async def delete_memory(self, memory_id: str) -> bool:
        """Delete a memory. Returns True on success."""
        try:
            response = await self._client.delete(f"/memories/{memory_id}")
        except (ConnectError, TimeoutException) as e:
            logger.exception("Failed to connect to Core API")
            raise CoreUnavailableError(f"Core API unavailable: {e}") from e

        if response.status_code == 404:
            raise CoreNotFoundError(f"Memory {memory_id} not found")

        if not response.is_success:
            logger.error(
                f"Failed to delete memory: {response.status_code} {response.text}"
            )
            raise CoreClientError(
                f"Failed to delete memory: {response.status_code} {response.text}"
            )

        return True

    async def add_tags(self, memory_id: str, data: TagsAddRequest) -> MemoryWithTags:
        """Add tags to a memory."""
        try:
            response = await self._client.post(
                f"/memories/{memory_id}/tags",
                json=data.model_dump(exclude_none=True),
            )
        except (ConnectError, TimeoutException) as e:
            logger.exception("Failed to connect to Core API")
            raise CoreUnavailableError(f"Core API unavailable: {e}") from e

        if response.status_code == 404:
            raise CoreNotFoundError(f"Memory {memory_id} not found")

        if not response.is_success:
            logger.error(f"Failed to add tags: {response.status_code} {response.text}")
            raise CoreClientError(
                f"Failed to add tags: {response.status_code} {response.text}"
            )

        return MemoryWithTags.model_validate(response.json())

    async def upload_image(self, memory_id: str, file_bytes: bytes) -> str:
        """Upload an image for a memory. Returns the local path from the response."""
        try:
            response = await self._client.post(
                f"/memories/{memory_id}/image",
                files={"file": file_bytes},
            )
        except (ConnectError, TimeoutException) as e:
            logger.exception("Failed to connect to Core API")
            raise CoreUnavailableError(f"Core API unavailable: {e}") from e

        if response.status_code == 404:
            raise CoreNotFoundError(f"Memory {memory_id} not found")

        if not response.is_success:
            logger.error(
                f"Failed to upload image: {response.status_code} {response.text}"
            )
            raise CoreClientError(
                f"Failed to upload image: {response.status_code} {response.text}"
            )

        data = response.json()
        return data.get("local_path", "")

    async def create_task(self, data: TaskCreate) -> TaskResponse:
        """Create a new task."""
        try:
            response = await self._client.post(
                "/tasks",
                json=data.model_dump(exclude_none=True),
            )
        except (ConnectError, TimeoutException) as e:
            logger.exception("Failed to connect to Core API")
            raise CoreUnavailableError(f"Core API unavailable: {e}") from e

        if response.status_code == 404:
            raise CoreNotFoundError("Task not found")

        if not response.is_success:
            logger.error(
                f"Failed to create task: {response.status_code} {response.text}"
            )
            raise CoreClientError(
                f"Failed to create task: {response.status_code} {response.text}"
            )

        return TaskResponse.model_validate(response.json())

    async def list_tasks(
        self, owner_user_id: int, state: str | None = None
    ) -> list[TaskResponse]:
        """List tasks for an owner, optionally filtered by state."""
        params: dict = {"owner_user_id": owner_user_id}
        if state is not None:
            params["state"] = state

        try:
            response = await self._client.get("/tasks", params=params)
        except (ConnectError, TimeoutException) as e:
            logger.exception("Failed to connect to Core API")
            raise CoreUnavailableError(f"Core API unavailable: {e}") from e

        if response.status_code == 404:
            raise CoreNotFoundError("Tasks not found")

        if not response.is_success:
            logger.error(
                f"Failed to list tasks: {response.status_code} {response.text}"
            )
            raise CoreClientError(
                f"Failed to list tasks: {response.status_code} {response.text}"
            )

        return [TaskResponse.model_validate(item) for item in response.json()]

    async def update_task(self, task_id: str, data: TaskUpdate) -> TaskResponse:
        """Update an existing task."""
        try:
            response = await self._client.patch(
                f"/tasks/{task_id}",
                json=data.model_dump(exclude_none=True),
            )
        except (ConnectError, TimeoutException) as e:
            logger.exception("Failed to connect to Core API")
            raise CoreUnavailableError(f"Core API unavailable: {e}") from e

        if response.status_code == 404:
            raise CoreNotFoundError(f"Task {task_id} not found")

        if not response.is_success:
            logger.error(
                f"Failed to update task: {response.status_code} {response.text}"
            )
            raise CoreClientError(
                f"Failed to update task: {response.status_code} {response.text}"
            )

        return TaskResponse.model_validate(response.json())

    async def create_reminder(self, data: ReminderCreate) -> ReminderResponse:
        """Create a new reminder."""
        try:
            response = await self._client.post(
                "/reminders",
                json=data.model_dump(exclude_none=True),
            )
        except (ConnectError, TimeoutException) as e:
            logger.exception("Failed to connect to Core API")
            raise CoreUnavailableError(f"Core API unavailable: {e}") from e

        if response.status_code == 404:
            raise CoreNotFoundError("Reminder not found")

        if not response.is_success:
            logger.error(
                f"Failed to create reminder: {response.status_code} {response.text}"
            )
            raise CoreClientError(
                f"Failed to create reminder: {response.status_code} {response.text}"
            )

        return ReminderResponse.model_validate(response.json())

    async def search(
        self, query: str, owner: int, pinned: bool = False
    ) -> list[MemorySearchResult]:
        """Search memories."""
        try:
            response = await self._client.get(
                "/search",
                params={"q": query, "owner": owner, "pinned": pinned},
            )
        except (ConnectError, TimeoutException) as e:
            logger.exception("Failed to connect to Core API")
            raise CoreUnavailableError(f"Core API unavailable: {e}") from e

        if response.status_code == 404:
            raise CoreNotFoundError("Search not found")

        if not response.is_success:
            logger.error(f"Failed to search: {response.status_code} {response.text}")
            raise CoreClientError(
                f"Failed to search: {response.status_code} {response.text}"
            )

        return [MemorySearchResult.model_validate(item) for item in response.json()]

    async def get_settings(self, user_id: int) -> UserSettingsResponse:
        """Get user settings."""
        try:
            response = await self._client.get(f"/settings/{user_id}")
        except (ConnectError, TimeoutException) as e:
            logger.exception("Failed to connect to Core API")
            raise CoreUnavailableError(f"Core API unavailable: {e}") from e

        if response.status_code == 404:
            raise CoreNotFoundError(f"Settings for user {user_id} not found")

        if not response.is_success:
            logger.error(
                f"Failed to get settings: {response.status_code} {response.text}"
            )
            raise CoreClientError(
                f"Failed to get settings: {response.status_code} {response.text}"
            )

        return UserSettingsResponse.model_validate(response.json())

    async def create_llm_job(self, data: LLMJobCreate) -> LLMJobResponse:
        """Create a new LLM job."""
        try:
            response = await self._client.post(
                "/llm-jobs",
                json=data.model_dump(exclude_none=True),
            )
        except (ConnectError, TimeoutException) as e:
            logger.exception("Failed to connect to Core API")
            raise CoreUnavailableError(f"Core API unavailable: {e}") from e

        if response.status_code == 404:
            raise CoreNotFoundError("LLM job not found")

        if not response.is_success:
            logger.error(
                f"Failed to create LLM job: {response.status_code} {response.text}"
            )
            raise CoreClientError(
                f"Failed to create LLM job: {response.status_code} {response.text}"
            )

        return LLMJobResponse.model_validate(response.json())
