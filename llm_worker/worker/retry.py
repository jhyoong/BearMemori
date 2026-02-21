"""In-memory retry tracker with exponential backoff."""

import logging

logger = logging.getLogger(__name__)


class RetryTracker:
    """Tracks job retry attempts in memory.

    If the worker restarts, counts reset. This is acceptable because
    unacknowledged Redis messages will be redelivered.
    """

    def __init__(self, max_retries: int = 5):
        self._attempts: dict[str, int] = {}
        self._max_retries = max_retries

    def record_attempt(self, job_id: str) -> int:
        """Increment and return the attempt count for a job."""
        self._attempts[job_id] = self._attempts.get(job_id, 0) + 1
        return self._attempts[job_id]

    def should_retry(self, job_id: str) -> bool:
        """Return True if the job has not exceeded max retries."""
        return self._attempts.get(job_id, 0) < self._max_retries

    def clear(self, job_id: str) -> None:
        """Remove a job from the tracker (on success or final failure)."""
        self._attempts.pop(job_id, None)

    def backoff_seconds(self, job_id: str) -> float:
        """Calculate exponential backoff: min(2^(attempts-1), 60)."""
        attempts = self._attempts.get(job_id, 1)
        return min(2.0 ** (attempts - 1), 60.0)