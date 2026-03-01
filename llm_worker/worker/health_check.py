"""Background health check for LLM worker."""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine

import aiohttp

from worker.config import LLMWorkerSettings

logger = logging.getLogger(__name__)

HEALTH_REDIS_KEY = "llm:health_status"
HEALTH_TTL_SECONDS = 300


class LLMHealthChecker:
    """Checks the health of the LLM endpoint."""

    def __init__(self, config: LLMWorkerSettings):
        """Initialize the health checker.

        Args:
            config: LLM worker configuration with LLM endpoint details.
        """
        self.config = config
        self.base_url = config.llm_base_url.rstrip("/")
        self.api_key = config.llm_api_key
        self._session: aiohttp.ClientSession | None = None

    def _get_health_check_url(self) -> str:
        """Get the URL for health check.

        Uses the /models endpoint which is lightweight and available
        in most OpenAI-compatible APIs.

        Returns:
            The health check endpoint URL.
        """
        return f"{self.base_url}/models"

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create the aiohttp session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=10)
            )
        return self._session

    async def check_health(self, redis_client) -> dict[str, Any]:
        """Check LLM endpoint health and update Redis.

        Reads existing health data from Redis to maintain consecutive_failures,
        last_success, and last_failure timestamps. Writes the full health data
        model back to Redis with a TTL.

        Args:
            redis_client: Async Redis client for storing health status.

        Returns:
            Dict with full health data model.
        """
        url = self._get_health_check_url()
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        now = datetime.now(timezone.utc).isoformat()

        # Read existing health data from Redis
        existing_raw = await redis_client.get(HEALTH_REDIS_KEY)
        if existing_raw:
            try:
                existing = json.loads(existing_raw)
            except json.JSONDecodeError:
                existing = {}
        else:
            existing = {}

        consecutive_failures = existing.get("consecutive_failures", 0)
        last_success = existing.get("last_success")
        last_failure = existing.get("last_failure")

        try:
            session = await self._get_session()
            async with session.get(url, headers=headers) as response:
                if response.status == 200:
                    # Parse response to verify it's a valid models response
                    data = await response.json()
                    models = data.get("data", [])

                    if isinstance(models, list):
                        result = {
                            "status": "healthy",
                            "last_check": now,
                            "last_success": now,
                            "last_failure": last_failure,
                            "consecutive_failures": 0,
                        }
                        logger.info(
                            "LLM health check passed: %s models available",
                            len(models),
                        )
                    else:
                        consecutive_failures += 1
                        result = {
                            "status": "unhealthy",
                            "error": "Invalid models response format",
                            "last_check": now,
                            "last_success": last_success,
                            "last_failure": now,
                            "consecutive_failures": consecutive_failures,
                        }
                        logger.warning(
                            "LLM health check failed: invalid response format"
                        )

                else:
                    consecutive_failures += 1
                    error_msg = (
                        f"HTTP {response.status}: {await response.text()}"
                    )
                    result = {
                        "status": "unhealthy",
                        "error": error_msg,
                        "last_check": now,
                        "last_success": last_success,
                        "last_failure": now,
                        "consecutive_failures": consecutive_failures,
                    }
                    logger.warning("LLM health check failed: %s", error_msg)

        except asyncio.TimeoutError:
            consecutive_failures += 1
            result = {
                "status": "unhealthy",
                "error": "TimeoutError",
                "last_check": now,
                "last_success": last_success,
                "last_failure": now,
                "consecutive_failures": consecutive_failures,
            }
            logger.warning("LLM health check failed: timeout")
        except ConnectionRefusedError:
            consecutive_failures += 1
            result = {
                "status": "unhealthy",
                "error": "ConnectionRefusedError",
                "last_check": now,
                "last_success": last_success,
                "last_failure": now,
                "consecutive_failures": consecutive_failures,
            }
            logger.warning("LLM health check failed: connection refused")
        except aiohttp.ClientConnectorError as e:
            consecutive_failures += 1
            result = {
                "status": "unhealthy",
                "error": f"ClientConnectorError: {e}",
                "last_check": now,
                "last_success": last_success,
                "last_failure": now,
                "consecutive_failures": consecutive_failures,
            }
            logger.warning("LLM health check failed: connection error")
        except aiohttp.ClientError as e:
            consecutive_failures += 1
            result = {
                "status": "unhealthy",
                "error": f"ClientError: {e}",
                "last_check": now,
                "last_success": last_success,
                "last_failure": now,
                "consecutive_failures": consecutive_failures,
            }
            logger.warning("LLM health check failed: client error")
        except Exception as e:
            consecutive_failures += 1
            result = {
                "status": "unhealthy",
                "error": str(e),
                "last_check": now,
                "last_success": last_success,
                "last_failure": now,
                "consecutive_failures": consecutive_failures,
            }
            logger.error(
                "LLM health check failed with unexpected error: %s", e
            )

        # Write health status to Redis with TTL
        await redis_client.set(
            HEALTH_REDIS_KEY, json.dumps(result), ex=HEALTH_TTL_SECONDS
        )

        return result

    async def close(self) -> None:
        """Close the HTTP session."""
        if self._session is not None and not self._session.closed:
            await self._session.close()
            self._session = None


# Type alias for the on_status_change callback
OnStatusChangeCallback = Callable[
    [str, str], Coroutine[Any, Any, None]
]


async def run_health_check(
    redis_client,
    checker: LLMHealthChecker,
    stop_event: asyncio.Event,
    interval: float = 30.0,
    on_status_change: OnStatusChangeCallback | None = None,
) -> None:
    """Run the health check periodically in the background.

    Tracks previous health status and calls the on_status_change callback
    when transitions occur (healthy->unhealthy or unhealthy->healthy).

    Args:
        redis_client: Async Redis client for storing health status.
        checker: LLMHealthChecker instance.
        stop_event: Event to signal when to stop.
        interval: Time between health checks in seconds (default 30).
        on_status_change: Optional async callback(new_status, previous_status)
            called when health status transitions.
    """
    logger.info("Starting LLM health check task (interval: %.1fs)", interval)
    previous_status: str | None = None

    try:
        while not stop_event.is_set():
            result = await checker.check_health(redis_client)
            current_status = result["status"]
            logger.debug("LLM health check completed: %s", current_status)

            # Detect status transitions and call callback
            if (
                previous_status is not None
                and current_status != previous_status
                and on_status_change is not None
            ):
                logger.info(
                    "LLM health status changed: %s -> %s",
                    previous_status,
                    current_status,
                )
                try:
                    await on_status_change(current_status, previous_status)
                except Exception:
                    logger.exception(
                        "Error in on_status_change callback"
                    )

            previous_status = current_status

            try:
                # Use wait_for to allow the event to be set during wait
                await asyncio.wait_for(
                    stop_event.wait(),
                    timeout=interval,
                )
                break  # Exit if stop_event is set
            except asyncio.TimeoutError:
                # Timeout is expected, continue to next check
                pass
    except asyncio.CancelledError:
        logger.info("LLM health check cancelled")
        raise
    finally:
        await checker.close()
        logger.info("LLM health check stopped")
