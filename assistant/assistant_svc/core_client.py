import logging
from httpx import AsyncClient, ConnectError, TimeoutException

from shared_lib.schemas import (
    EventResponse,
    MemorySearchResult,
    MemoryWithTags,
    ReminderCreate,
    ReminderResponse,
    TaskCreate,
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


class AssistantCoreClient:
    def __init__(self, base_url: str, timeout: float = 10.0):
        self._client = AsyncClient(base_url=base_url, timeout=timeout)

    async def close(self):
        """Close the HTTP client."""
        await self._client.aclose()

    async def search_memories(self, query: str, owner_user_id: int) -> list[MemorySearchResult]:
        """Search memories by query for a given owner."""
        try:
            response = await self._client.get(
                "/search",
                params={"q": query, "owner": owner_user_id},
            )
        except (ConnectError, TimeoutException) as e:
            logger.exception("Failed to connect to Core API")
            raise CoreUnavailableError(f"Core API unavailable: {e}") from e

        if not response.is_success:
            logger.error(f"Failed to search memories: {response.status_code} {response.text}")
            raise CoreClientError(
                f"Failed to search memories: {response.status_code} {response.text}"
            )

        return [MemorySearchResult.model_validate(item) for item in response.json()]

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
            logger.error(f"Failed to get memory: {response.status_code} {response.text}")
            raise CoreClientError(
                f"Failed to get memory: {response.status_code} {response.text}"
            )

        return MemoryWithTags.model_validate(response.json())

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

        if not response.is_success:
            logger.error(f"Failed to list tasks: {response.status_code} {response.text}")
            raise CoreClientError(
                f"Failed to list tasks: {response.status_code} {response.text}"
            )

        return [TaskResponse.model_validate(item) for item in response.json()]

    async def list_reminders(
        self,
        owner_user_id: int,
        fired: bool | None = None,
        upcoming_only: bool | None = None,
    ) -> list[ReminderResponse]:
        """List reminders for an owner with optional filters."""
        params: dict = {"owner_user_id": owner_user_id}
        if fired is not None:
            params["fired"] = fired
        if upcoming_only is not None:
            params["upcoming_only"] = upcoming_only

        try:
            response = await self._client.get("/reminders", params=params)
        except (ConnectError, TimeoutException) as e:
            logger.exception("Failed to connect to Core API")
            raise CoreUnavailableError(f"Core API unavailable: {e}") from e

        if not response.is_success:
            logger.error(f"Failed to list reminders: {response.status_code} {response.text}")
            raise CoreClientError(
                f"Failed to list reminders: {response.status_code} {response.text}"
            )

        return [ReminderResponse.model_validate(item) for item in response.json()]

    async def list_events(
        self, owner_user_id: int, status: str | None = None
    ) -> list[EventResponse]:
        """List events for an owner, optionally filtered by status."""
        params: dict = {"owner_user_id": owner_user_id}
        if status is not None:
            params["status"] = status

        try:
            response = await self._client.get("/events", params=params)
        except (ConnectError, TimeoutException) as e:
            logger.exception("Failed to connect to Core API")
            raise CoreUnavailableError(f"Core API unavailable: {e}") from e

        if not response.is_success:
            logger.error(f"Failed to list events: {response.status_code} {response.text}")
            raise CoreClientError(
                f"Failed to list events: {response.status_code} {response.text}"
            )

        return [EventResponse.model_validate(item) for item in response.json()]

    async def create_task(
        self,
        memory_id: str,
        owner_user_id: int,
        description: str,
        due_at: str | None = None,
    ) -> TaskResponse:
        """Create a new task linked to a memory."""
        data = TaskCreate(
            memory_id=memory_id,
            owner_user_id=owner_user_id,
            description=description,
            due_at=due_at,
        )

        try:
            response = await self._client.post(
                "/tasks",
                json=data.model_dump(mode="json", exclude_none=True),
            )
        except (ConnectError, TimeoutException) as e:
            logger.exception("Failed to connect to Core API")
            raise CoreUnavailableError(f"Core API unavailable: {e}") from e

        if response.status_code == 404:
            raise CoreNotFoundError("Memory not found when creating task")

        if not response.is_success:
            logger.error(f"Failed to create task: {response.status_code} {response.text}")
            raise CoreClientError(
                f"Failed to create task: {response.status_code} {response.text}"
            )

        return TaskResponse.model_validate(response.json())

    async def create_reminder(
        self,
        memory_id: str,
        owner_user_id: int,
        text: str,
        fire_at: str,
    ) -> ReminderResponse:
        """Create a new reminder linked to a memory."""
        data = ReminderCreate(
            memory_id=memory_id,
            owner_user_id=owner_user_id,
            text=text,
            fire_at=fire_at,
        )

        try:
            response = await self._client.post(
                "/reminders",
                json=data.model_dump(mode="json", exclude_none=True),
            )
        except (ConnectError, TimeoutException) as e:
            logger.exception("Failed to connect to Core API")
            raise CoreUnavailableError(f"Core API unavailable: {e}") from e

        if response.status_code == 404:
            raise CoreNotFoundError("Memory not found when creating reminder")

        if not response.is_success:
            logger.error(f"Failed to create reminder: {response.status_code} {response.text}")
            raise CoreClientError(
                f"Failed to create reminder: {response.status_code} {response.text}"
            )

        return ReminderResponse.model_validate(response.json())

    async def get_settings(self, user_id: int) -> UserSettingsResponse:
        """Get user settings by user ID."""
        try:
            response = await self._client.get(f"/settings/{user_id}")
        except (ConnectError, TimeoutException) as e:
            logger.exception("Failed to connect to Core API")
            raise CoreUnavailableError(f"Core API unavailable: {e}") from e

        if response.status_code == 404:
            raise CoreNotFoundError(f"Settings for user {user_id} not found")

        if not response.is_success:
            logger.error(f"Failed to get settings: {response.status_code} {response.text}")
            raise CoreClientError(
                f"Failed to get settings: {response.status_code} {response.text}"
            )

        return UserSettingsResponse.model_validate(response.json())
