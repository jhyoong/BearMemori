"""Tests for the LLM worker health check."""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import json

import fakeredis.aioredis

from worker.health_check import (
    run_health_check,
    LLMHealthChecker,
    HEALTH_REDIS_KEY,
    HEALTH_TTL_SECONDS,
)
from worker.config import LLMWorkerSettings


@pytest.fixture
def fake_redis_client():
    """Create a fake Redis client for testing."""
    return fakeredis.aioredis.FakeRedis()


@pytest.fixture
def test_llm_config():
    """Create an LLMWorkerSettings instance with test values."""
    return LLMWorkerSettings(
        llm_base_url="http://localhost:8080/v1",
        llm_api_key="test-api-key",
        llm_vision_model="test-vision",
        llm_text_model="test-text",
        llm_max_retries=3,
        redis_url="redis://localhost:6379",
        core_api_url="http://localhost:8000",
        image_storage_path="/tmp/test-images",
    )


class TestLLMHealthChecker:
    """Tests for the LLMHealthChecker class."""

    def test_init_with_default_base_url(self):
        """Test initialization with default OpenAI base URL."""
        config = LLMWorkerSettings(
            llm_base_url="https://api.openai.com/v1",
            llm_api_key="test-key",
        )
        checker = LLMHealthChecker(config)

        assert checker.base_url == "https://api.openai.com/v1"
        assert checker.api_key == "test-key"

    def test_init_with_custom_base_url(self, test_llm_config):
        """Test initialization with custom base URL."""
        checker = LLMHealthChecker(test_llm_config)

        assert checker.base_url == "http://localhost:8080/v1"

    def test_get_health_check_url_openai(self, test_llm_config):
        """Test URL generation for OpenAI-compatible API."""
        config = LLMWorkerSettings(
            llm_base_url="https://api.openai.com/v1",
            llm_api_key="test",
        )
        checker = LLMHealthChecker(config)

        url = checker._get_health_check_url()
        assert url == "https://api.openai.com/v1/models"

    def test_get_health_check_url_custom(self, test_llm_config):
        """Test URL generation for custom LLM endpoint."""
        checker = LLMHealthChecker(test_llm_config)

        url = checker._get_health_check_url()
        assert url == "http://localhost:8080/v1/models"

    @pytest.mark.asyncio
    async def test_check_health_success(self, fake_redis_client, test_llm_config):
        """Test health check returns healthy status on successful API call."""
        checker = LLMHealthChecker(test_llm_config)

        # Mock aiohttp session
        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_session = MagicMock()
            mock_response = MagicMock()

            # Mock successful response with models list
            mock_response.status = 200
            mock_response.json = AsyncMock(
                return_value={
                    "data": [{"id": "mistral"}, {"id": "llava"}],
                    "object": "list",
                }
            )
            mock_response.__aenter__ = AsyncMock(return_value=mock_response)
            mock_session.get = MagicMock()
            mock_session.get.return_value.__aenter__ = AsyncMock(
                return_value=mock_response
            )
            mock_session.close = AsyncMock()
            mock_session_class.return_value = mock_session

            result = await checker.check_health(fake_redis_client)

            assert result["status"] == "healthy"
            assert result["last_check"] is not None
            assert result["last_success"] is not None
            assert result["consecutive_failures"] == 0

            # Verify health status was written to Redis
            stored_data = await fake_redis_client.get(HEALTH_REDIS_KEY)
            assert stored_data is not None
            stored = json.loads(stored_data)
            assert stored["status"] == "healthy"
            assert stored["consecutive_failures"] == 0

    @pytest.mark.asyncio
    async def test_check_health_sets_ttl(self, fake_redis_client, test_llm_config):
        """Test health check sets TTL on the Redis key."""
        checker = LLMHealthChecker(test_llm_config)

        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_session = MagicMock()
            mock_response = MagicMock()
            mock_response.status = 200
            mock_response.json = AsyncMock(
                return_value={"data": [{"id": "test"}], "object": "list"}
            )
            mock_response.__aenter__ = AsyncMock(return_value=mock_response)
            mock_session.get = MagicMock()
            mock_session.get.return_value.__aenter__ = AsyncMock(
                return_value=mock_response
            )
            mock_session.close = AsyncMock()
            mock_session_class.return_value = mock_session

            await checker.check_health(fake_redis_client)

            # Verify TTL was set
            ttl = await fake_redis_client.ttl(HEALTH_REDIS_KEY)
            assert 0 < ttl <= HEALTH_TTL_SECONDS

    @pytest.mark.asyncio
    async def test_check_health_connection_failure(
        self, fake_redis_client, test_llm_config
    ):
        """Test health check returns unhealthy on connection failure."""
        checker = LLMHealthChecker(test_llm_config)

        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_session = MagicMock()
            mock_session.get = MagicMock(
                side_effect=ConnectionRefusedError("Connection refused")
            )
            mock_session.close = AsyncMock()
            mock_session_class.return_value = mock_session

            result = await checker.check_health(fake_redis_client)

            assert result["status"] == "unhealthy"
            assert "ConnectionRefusedError" in result["error"]
            assert result["consecutive_failures"] == 1

            # Verify health status was written to Redis
            stored_data = await fake_redis_client.get(HEALTH_REDIS_KEY)
            assert stored_data is not None
            stored = json.loads(stored_data)
            assert stored["status"] == "unhealthy"
            assert stored["error"] == "ConnectionRefusedError"

    @pytest.mark.asyncio
    async def test_check_health_timeout(self, fake_redis_client, test_llm_config):
        """Test health check returns unhealthy on timeout."""
        checker = LLMHealthChecker(test_llm_config)

        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_session = MagicMock()
            mock_session.get = MagicMock(side_effect=asyncio.TimeoutError())
            mock_session.close = AsyncMock()
            mock_session_class.return_value = mock_session

            result = await checker.check_health(fake_redis_client)

            assert result["status"] == "unhealthy"
            assert "TimeoutError" in result["error"]
            assert result["consecutive_failures"] == 1

            # Verify health status was written to Redis
            stored_data = await fake_redis_client.get(HEALTH_REDIS_KEY)
            assert stored_data is not None
            stored = json.loads(stored_data)
            assert stored["status"] == "unhealthy"
            assert stored["error"] == "TimeoutError"

    @pytest.mark.asyncio
    async def test_check_health_api_error(self, fake_redis_client, test_llm_config):
        """Test health check returns unhealthy on API error."""
        checker = LLMHealthChecker(test_llm_config)

        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_session = MagicMock()
            mock_response = MagicMock()

            # Mock 500 error response
            mock_response.status = 500
            mock_response.text = AsyncMock(return_value="Internal Server Error")
            mock_response.__aenter__ = AsyncMock(return_value=mock_response)
            mock_session.get = MagicMock()
            mock_session.get.return_value.__aenter__ = AsyncMock(
                return_value=mock_response
            )
            mock_session.close = AsyncMock()
            mock_session_class.return_value = mock_session

            result = await checker.check_health(fake_redis_client)

            assert result["status"] == "unhealthy"
            assert "500" in result["error"]
            assert result["consecutive_failures"] == 1

            # Verify health status was written to Redis
            stored_data = await fake_redis_client.get(HEALTH_REDIS_KEY)
            assert stored_data is not None
            stored = json.loads(stored_data)
            assert stored["status"] == "unhealthy"

    @pytest.mark.asyncio
    async def test_check_health_graceful_error_handling(
        self, fake_redis_client, test_llm_config
    ):
        """Test that health check doesn't raise exceptions on errors."""
        checker = LLMHealthChecker(test_llm_config)

        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_session = MagicMock()
            # Raise an unexpected error
            mock_session.get = MagicMock(side_effect=Exception("Unexpected error"))
            mock_session.close = AsyncMock()
            mock_session_class.return_value = mock_session

            # Should not raise
            result = await checker.check_health(fake_redis_client)

            assert result["status"] == "unhealthy"
            assert "Unexpected error" in result["error"]
            assert result["consecutive_failures"] == 1

            # Verify health status was written to Redis
            stored_data = await fake_redis_client.get(HEALTH_REDIS_KEY)
            assert stored_data is not None
            stored = json.loads(stored_data)
            assert stored["status"] == "unhealthy"

    @pytest.mark.asyncio
    async def test_consecutive_failures_increment(
        self, fake_redis_client, test_llm_config
    ):
        """Test that consecutive_failures increments on repeated failures."""
        checker = LLMHealthChecker(test_llm_config)

        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_session = MagicMock()
            mock_session.get = MagicMock(
                side_effect=ConnectionRefusedError("Connection refused")
            )
            mock_session.close = AsyncMock()
            mock_session_class.return_value = mock_session

            # First failure
            result1 = await checker.check_health(fake_redis_client)
            assert result1["consecutive_failures"] == 1

            # Second failure - should read existing data and increment
            result2 = await checker.check_health(fake_redis_client)
            assert result2["consecutive_failures"] == 2

            # Third failure
            result3 = await checker.check_health(fake_redis_client)
            assert result3["consecutive_failures"] == 3

    @pytest.mark.asyncio
    async def test_consecutive_failures_reset_on_success(
        self, fake_redis_client, test_llm_config
    ):
        """Test that consecutive_failures resets to 0 on success."""
        checker = LLMHealthChecker(test_llm_config)

        # Seed with existing failure data
        await fake_redis_client.set(
            HEALTH_REDIS_KEY,
            json.dumps({
                "status": "unhealthy",
                "consecutive_failures": 5,
                "last_success": "2026-01-01T00:00:00+00:00",
                "last_failure": "2026-03-01T00:00:00+00:00",
            }),
        )

        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_session = MagicMock()
            mock_response = MagicMock()
            mock_response.status = 200
            mock_response.json = AsyncMock(
                return_value={"data": [{"id": "test"}], "object": "list"}
            )
            mock_response.__aenter__ = AsyncMock(return_value=mock_response)
            mock_session.get = MagicMock()
            mock_session.get.return_value.__aenter__ = AsyncMock(
                return_value=mock_response
            )
            mock_session.close = AsyncMock()
            mock_session_class.return_value = mock_session

            result = await checker.check_health(fake_redis_client)

            assert result["status"] == "healthy"
            assert result["consecutive_failures"] == 0
            # last_failure should be preserved from existing data
            assert result["last_failure"] == "2026-03-01T00:00:00+00:00"

    @pytest.mark.asyncio
    async def test_full_health_data_model(self, fake_redis_client, test_llm_config):
        """Test that all fields in the health data model are present."""
        checker = LLMHealthChecker(test_llm_config)

        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_session = MagicMock()
            mock_response = MagicMock()
            mock_response.status = 200
            mock_response.json = AsyncMock(
                return_value={"data": [{"id": "test"}], "object": "list"}
            )
            mock_response.__aenter__ = AsyncMock(return_value=mock_response)
            mock_session.get = MagicMock()
            mock_session.get.return_value.__aenter__ = AsyncMock(
                return_value=mock_response
            )
            mock_session.close = AsyncMock()
            mock_session_class.return_value = mock_session

            result = await checker.check_health(fake_redis_client)

            # All required fields present
            assert "status" in result
            assert "last_check" in result
            assert "last_success" in result
            assert "last_failure" in result
            assert "consecutive_failures" in result


class TestRunHealthCheck:
    """Tests for the run_health_check background task."""

    @pytest.mark.asyncio
    async def test_run_health_check_single_iteration(
        self, fake_redis_client, test_llm_config
    ):
        """Test that run_health_check performs a single iteration when stopped."""
        checker = AsyncMock()
        checker.check_health = AsyncMock(
            return_value={"status": "healthy", "error": None}
        )
        checker.close = AsyncMock()

        stop_event = asyncio.Event()

        # Run with very short interval and stop immediately
        task = asyncio.create_task(
            run_health_check(
                fake_redis_client, checker, stop_event, interval=0.1
            )
        )

        # Wait for it to do at least one iteration
        await asyncio.sleep(0.05)

        # Stop the task
        stop_event.set()
        await asyncio.sleep(0.05)  # Give time for cleanup

        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        # Should have been called at least once
        assert checker.check_health.called
        checker.close.assert_called()

    @pytest.mark.asyncio
    async def test_run_health_check_stops_on_stop_event(
        self, fake_redis_client, test_llm_config
    ):
        """Test that the health check loop responds to stop event."""
        checker = AsyncMock()
        checker.check_health = AsyncMock(
            return_value={"status": "healthy", "error": None}
        )
        checker.close = AsyncMock()

        stop_event = asyncio.Event()

        task = asyncio.create_task(
            run_health_check(
                fake_redis_client, checker, stop_event, interval=0.1
            )
        )

        # Wait for it to do first iteration
        await asyncio.sleep(0.05)

        # Stop via event
        stop_event.set()
        await asyncio.sleep(0.05)

        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        # Verify health check was called and checker was closed
        assert checker.check_health.called
        checker.close.assert_called()

    @pytest.mark.asyncio
    async def test_run_health_check_calls_callback_on_transition(
        self, fake_redis_client, test_llm_config
    ):
        """Test that on_status_change callback is called on health transition."""
        call_count = 0
        results = [
            {"status": "healthy"},
            {"status": "unhealthy"},  # transition: healthy -> unhealthy
            {"status": "unhealthy"},  # no transition
            {"status": "healthy"},  # transition: unhealthy -> healthy
        ]
        result_index = 0

        async def mock_check_health(redis_client):
            nonlocal result_index
            r = results[min(result_index, len(results) - 1)]
            result_index += 1
            return r

        checker = AsyncMock()
        checker.check_health = mock_check_health
        checker.close = AsyncMock()

        callback_calls = []

        async def on_change(new_status, previous_status):
            callback_calls.append((new_status, previous_status))

        stop_event = asyncio.Event()

        task = asyncio.create_task(
            run_health_check(
                fake_redis_client,
                checker,
                stop_event,
                interval=0.05,
                on_status_change=on_change,
            )
        )

        # Wait for all 4 iterations
        await asyncio.sleep(0.35)
        stop_event.set()

        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        # Should have 2 transitions: healthy->unhealthy and unhealthy->healthy
        assert len(callback_calls) == 2
        assert callback_calls[0] == ("unhealthy", "healthy")
        assert callback_calls[1] == ("healthy", "unhealthy")

    @pytest.mark.asyncio
    async def test_run_health_check_no_callback_on_first_check(
        self, fake_redis_client, test_llm_config
    ):
        """Test that callback is NOT called on the first check (no previous status)."""
        checker = AsyncMock()
        checker.check_health = AsyncMock(
            return_value={"status": "unhealthy"}
        )
        checker.close = AsyncMock()

        callback_calls = []

        async def on_change(new_status, previous_status):
            callback_calls.append((new_status, previous_status))

        stop_event = asyncio.Event()

        task = asyncio.create_task(
            run_health_check(
                fake_redis_client,
                checker,
                stop_event,
                interval=0.05,
                on_status_change=on_change,
            )
        )

        # Wait for one iteration
        await asyncio.sleep(0.03)
        stop_event.set()

        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        # Should NOT have been called (first check has no previous status)
        assert len(callback_calls) == 0

    @pytest.mark.asyncio
    async def test_run_health_check_callback_error_does_not_crash(
        self, fake_redis_client, test_llm_config
    ):
        """Test that an error in the callback does not crash the health check loop."""
        results = [
            {"status": "healthy"},
            {"status": "unhealthy"},  # triggers callback
            {"status": "unhealthy"},  # no transition
        ]
        result_index = 0

        async def mock_check_health(redis_client):
            nonlocal result_index
            r = results[min(result_index, len(results) - 1)]
            result_index += 1
            return r

        checker = AsyncMock()
        checker.check_health = mock_check_health
        checker.close = AsyncMock()

        async def bad_callback(new_status, previous_status):
            raise RuntimeError("callback error")

        stop_event = asyncio.Event()

        task = asyncio.create_task(
            run_health_check(
                fake_redis_client,
                checker,
                stop_event,
                interval=0.05,
                on_status_change=bad_callback,
            )
        )

        # Wait for iterations -- should not crash
        await asyncio.sleep(0.2)
        stop_event.set()

        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        # The loop should have continued despite callback error
        assert result_index >= 2
