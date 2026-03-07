"""Tests for timezone utility functions."""

import os
import sys

import pytest

telegram_dir = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "telegram",
)
if telegram_dir not in sys.path:
    sys.path.insert(0, telegram_dir)

from tg_gateway.tz_utils import offset_to_iana


class TestOffsetToIana:
    def test_positive_offset(self):
        assert offset_to_iana("+8") == "Etc/GMT-8"

    def test_negative_offset(self):
        assert offset_to_iana("-5") == "Etc/GMT+5"

    def test_zero_offset(self):
        assert offset_to_iana("+0") == "Etc/GMT+0"

    def test_negative_zero(self):
        assert offset_to_iana("-0") == "Etc/GMT+0"

    def test_leading_zero(self):
        assert offset_to_iana("+08") == "Etc/GMT-8"

    def test_max_positive(self):
        assert offset_to_iana("+14") == "Etc/GMT-14"

    def test_max_negative(self):
        assert offset_to_iana("-12") == "Etc/GMT+12"

    def test_out_of_range_raises(self):
        with pytest.raises(ValueError, match="out of range"):
            offset_to_iana("+15")

    def test_negative_out_of_range_raises(self):
        with pytest.raises(ValueError, match="out of range"):
            offset_to_iana("-13")

    def test_half_hour_rejected(self):
        with pytest.raises(ValueError, match="whole hour"):
            offset_to_iana("+5:30")

    def test_invalid_format(self):
        with pytest.raises(ValueError):
            offset_to_iana("abc")

    def test_missing_sign(self):
        with pytest.raises(ValueError):
            offset_to_iana("8")