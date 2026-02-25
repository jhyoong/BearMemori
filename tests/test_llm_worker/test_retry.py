"""Tests for the RetryManager class."""

import time
from unittest.mock import patch

import pytest

from worker.retry import FailureType, RetryManager


class TestInvalidResponse:
    """Tests for INVALID_RESPONSE failure type."""

    def test_invalid_response_exponential_backoff_sequence(self):
        """Exponential backoff: 1s, 2s, 4s, 8s, 16s (capped at 16s)."""
        manager = RetryManager()

        # First attempt - should return 1.0
        manager.record_attempt("job-1", FailureType.INVALID_RESPONSE)
        assert manager.backoff_seconds("job-1") == 1.0

        # Second attempt - should return 2.0
        manager.record_attempt("job-1", FailureType.INVALID_RESPONSE)
        assert manager.backoff_seconds("job-1") == 2.0

        # Third attempt - should return 4.0
        manager.record_attempt("job-1", FailureType.INVALID_RESPONSE)
        assert manager.backoff_seconds("job-1") == 4.0

        # Fourth attempt - should return 8.0
        manager.record_attempt("job-1", FailureType.INVALID_RESPONSE)
        assert manager.backoff_seconds("job-1") == 8.0

        # Fifth attempt - should return 16.0 (capped)
        manager.record_attempt("job-1", FailureType.INVALID_RESPONSE)
        assert manager.backoff_seconds("job-1") == 16.0

        # Sixth attempt - should still return 16.0 (capped)
        manager.record_attempt("job-1", FailureType.INVALID_RESPONSE)
        assert manager.backoff_seconds("job-1") == 16.0

    def test_invalid_response_max_5_attempts(self):
        """should_retry returns False after 5 attempts."""
        manager = RetryManager()

        # Attempt 1-4: should retry
        for _ in range(4):
            manager.record_attempt("job-1", FailureType.INVALID_RESPONSE)
            assert manager.should_retry("job-1") is True

        # Attempt 5: should NOT retry (exhausted)
        manager.record_attempt("job-1", FailureType.INVALID_RESPONSE)
        assert manager.should_retry("job-1") is False

    def test_invalid_response_different_jobs_independent(self):
        """Each job has independent retry counts."""
        manager = RetryManager()

        # Job 1: exhaust
        for _ in range(5):
            manager.record_attempt("job-1", FailureType.INVALID_RESPONSE)

        # Job 2: still has retries
        manager.record_attempt("job-2", FailureType.INVALID_RESPONSE)

        assert manager.should_retry("job-1") is False
        assert manager.should_retry("job-2") is True


class TestUnavailable:
    """Tests for UNAVAILABLE failure type."""

    def test_unavailable_sets_queue_paused_on_first_failure(self):
        """On first UNAVAILABLE failure, _queue_paused should be True."""
        manager = RetryManager()

        assert manager.is_queue_paused() is False

        manager.record_attempt("job-1", FailureType.UNAVAILABLE)

        assert manager.is_queue_paused() is True

    def test_unavailable_tracks_first_unavailable_time_per_job(self):
        """Each job tracks its own first_unavailable_time."""
        current_time = [1000.0]
        manager = RetryManager(time_func=lambda: current_time[0])

        # Record at different times
        current_time[0] = 1000.0
        manager.record_attempt("job-1", FailureType.UNAVAILABLE)

        current_time[0] = 2000.0
        manager.record_attempt("job-2", FailureType.UNAVAILABLE)

        # Each job should have its own timestamp and be retryable
        assert manager.should_retry("job-1") is True
        assert manager.should_retry("job-2") is True

    def test_unavailable_should_retry_true_within_14_days(self):
        """should_retry returns True if within 14-day window."""
        current_time = [1000000.0]
        manager = RetryManager(time_func=lambda: current_time[0])

        # Record failure at time T
        manager.record_attempt("job-1", FailureType.UNAVAILABLE)

        # At T + 1 day (within 14 days): should retry
        current_time[0] = 1000000.0 + 1 * 24 * 3600
        assert manager.should_retry("job-1") is True

        # At T + 13 days (still within 14 days): should retry
        current_time[0] = 1000000.0 + 13 * 24 * 3600
        assert manager.should_retry("job-1") is True

    def test_unavailable_should_retry_false_after_14_days(self):
        """should_retry returns False if after 14-day window."""
        current_time = [1000000.0]
        manager = RetryManager(time_func=lambda: current_time[0])

        # Record failure at time T
        manager.record_attempt("job-1", FailureType.UNAVAILABLE)

        # At T + 14 days: should NOT retry
        current_time[0] = 1000000.0 + 14 * 24 * 3600
        assert manager.should_retry("job-1") is False


class TestRetryManagerInterface:
    """Tests for the full RetryManager interface."""

    def test_record_attempt_with_invalid_response(self):
        """record_attempt with INVALID_RESPONSE increments count."""
        manager = RetryManager()

        result = manager.record_attempt("job-1", FailureType.INVALID_RESPONSE)

        assert result == 1
        assert manager.get_failure_type("job-1") == FailureType.INVALID_RESPONSE

    def test_record_attempt_with_unavailable(self):
        """record_attempt with UNAVAILABLE sets queue paused."""
        manager = RetryManager()

        manager.record_attempt("job-1", FailureType.UNAVAILABLE)

        assert manager.is_queue_paused() is True
        assert manager.get_failure_type("job-1") == FailureType.UNAVAILABLE

    def test_get_failure_type_returns_none_for_unknown_job(self):
        """get_failure_type returns None for job not in tracker."""
        manager = RetryManager()

        result = manager.get_failure_type("unknown-job")

        assert result is None

    def test_backoff_seconds_for_unavailable_returns_zero(self):
        """backoff_seconds returns 0 for UNAVAILABLE type."""
        manager = RetryManager()

        manager.record_attempt("job-1", FailureType.UNAVAILABLE)

        # UNAVAILABLE doesn't use backoff - returns 0
        assert manager.backoff_seconds("job-1") == 0.0

    def test_backoff_seconds_unknown_job_returns_zero(self):
        """backoff_seconds returns 0 for unknown job."""
        manager = RetryManager()

        result = manager.backoff_seconds("unknown-job")

        assert result == 0.0
