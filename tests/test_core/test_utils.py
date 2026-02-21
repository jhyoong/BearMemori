"""Tests for core_svc.utils."""

from datetime import datetime, timezone
from core_svc.utils import parse_db_datetime


class TestParseDbDatetime:
    def test_none_returns_none(self):
        assert parse_db_datetime(None) is None

    def test_empty_string_returns_none(self):
        assert parse_db_datetime("") is None

    def test_z_suffix(self):
        result = parse_db_datetime("2026-01-15T10:30:00Z")
        assert result == datetime(2026, 1, 15, 10, 30, 0, tzinfo=timezone.utc)

    def test_plus_offset(self):
        result = parse_db_datetime("2026-01-15T10:30:00+00:00")
        assert result == datetime(2026, 1, 15, 10, 30, 0, tzinfo=timezone.utc)

    def test_plus_offset_with_trailing_z(self):
        result = parse_db_datetime("2026-01-15T10:30:00+00:00Z")
        assert result == datetime(2026, 1, 15, 10, 30, 0, tzinfo=timezone.utc)

    def test_milliseconds(self):
        result = parse_db_datetime("2026-01-15T10:30:00.123Z")
        assert result.microsecond == 123000
