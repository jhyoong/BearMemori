"""Tests for the utils module."""

import pytest

from worker.utils import extract_json


def test_extract_json_clean():
    """'{"key": "value"}' -> {"key": "value"}."""
    result = extract_json('{"key": "value"}')
    assert result == {"key": "value"}


def test_extract_json_with_text():
    """'Here is the result: {"key": "value"} Hope that helps!' -> {"key": "value"}."""
    text = 'Here is the result: {"key": "value"} Hope that helps!'
    result = extract_json(text)
    assert result == {"key": "value"}


def test_extract_json_markdown_block():
    """'```json\n{"key": "value"}\n```' -> {"key": "value"}."""
    text = '```json\n{"key": "value"}\n```'
    result = extract_json(text)
    assert result == {"key": "value"}


def test_extract_json_nested():
    """'{"outer": {"inner": [1, 2]}}' -> correctly nested."""
    text = '{"outer": {"inner": [1, 2]}}'
    result = extract_json(text)
    assert result == {"outer": {"inner": [1, 2]}}


def test_extract_json_no_json():
    """'no json here' -> raises ValueError."""
    with pytest.raises(ValueError):
        extract_json("no json here")


def test_extract_json_invalid_json():
    """'{broken json}' -> raises ValueError."""
    with pytest.raises(ValueError):
        extract_json("{broken json}")