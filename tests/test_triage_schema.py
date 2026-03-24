"""Tests for TriageRequest schema accepting current_time."""

from bearmemori.api.schemas import TriageRequest


def test_triage_request_accepts_current_time():
    """TriageRequest should accept an optional current_time field."""
    req = TriageRequest(
        conversation=[{"role": "user", "content": "hello"}],
        current_time="Monday, March 24, 2026, 07:33 PM +0800 (Asia/Singapore)",
    )
    assert req.current_time == "Monday, March 24, 2026, 07:33 PM +0800 (Asia/Singapore)"


def test_triage_request_current_time_defaults_to_none():
    """current_time should default to None when not provided."""
    req = TriageRequest(
        conversation=[{"role": "user", "content": "hello"}],
    )
    assert req.current_time is None
