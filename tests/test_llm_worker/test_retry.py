"""Tests for the retry module."""

from worker.retry import RetryTracker


def test_record_attempt_increments():
    """record_attempt returns 1, 2, 3..."""
    tracker = RetryTracker(max_retries=5)
    assert tracker.record_attempt("job-1") == 1
    assert tracker.record_attempt("job-1") == 2
    assert tracker.record_attempt("job-1") == 3


def test_should_retry_under_limit():
    """True when attempts < max_retries."""
    tracker = RetryTracker(max_retries=5)
    tracker.record_attempt("job-1")
    assert tracker.should_retry("job-1") is True
    tracker.record_attempt("job-1")
    assert tracker.should_retry("job-1") is True


def test_should_retry_at_limit():
    """False when attempts == max_retries."""
    tracker = RetryTracker(max_retries=3)
    tracker.record_attempt("job-1")
    tracker.record_attempt("job-1")
    tracker.record_attempt("job-1")
    assert tracker.should_retry("job-1") is False


def test_clear_removes_tracking():
    """After clear, should_retry returns True again."""
    tracker = RetryTracker(max_retries=3)
    tracker.record_attempt("job-1")
    tracker.record_attempt("job-1")
    tracker.record_attempt("job-1")
    assert tracker.should_retry("job-1") is False
    tracker.clear("job-1")
    assert tracker.should_retry("job-1") is True


def test_backoff_seconds_exponential():
    """1, 2, 4, 8, 16, 32, 60, 60 (capped)."""
    tracker = RetryTracker(max_retries=10)
    assert tracker.backoff_seconds("unknown") == 1.0
    tracker.record_attempt("job-1")
    assert tracker.backoff_seconds("job-1") == 1.0
    tracker.record_attempt("job-1")
    assert tracker.backoff_seconds("job-1") == 2.0
    tracker.record_attempt("job-1")
    assert tracker.backoff_seconds("job-1") == 4.0
    tracker.record_attempt("job-1")
    assert tracker.backoff_seconds("job-1") == 8.0
    tracker.record_attempt("job-1")
    assert tracker.backoff_seconds("job-1") == 16.0
    tracker.record_attempt("job-1")
    assert tracker.backoff_seconds("job-1") == 32.0
    tracker.record_attempt("job-1")
    assert tracker.backoff_seconds("job-1") == 60.0
    tracker.record_attempt("job-1")
    assert tracker.backoff_seconds("job-1") == 60.0


def test_backoff_seconds_default():
    """Returns 1.0 for unknown job_id."""
    tracker = RetryTracker(max_retries=5)
    assert tracker.backoff_seconds("unknown-job") == 1.0