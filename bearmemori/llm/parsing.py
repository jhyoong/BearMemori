"""Utilities for extracting JSON from LLM responses."""

import json
import logging
import re

logger = logging.getLogger(__name__)


def extract_json(raw: str) -> dict:
    """Extract a JSON object from an LLM response string.

    Handles common LLM output quirks:
    - <think>...</think> blocks (Qwen3 thinking mode)
    - Markdown code fences (```json ... ```)
    - Leading/trailing whitespace

    Raises json.JSONDecodeError if no valid JSON can be found.
    """
    if not raw or not raw.strip():
        raise json.JSONDecodeError("Empty response", raw or "", 0)

    # Strip <think>...</think> blocks
    cleaned = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()

    # Try direct parse first
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Try extracting from markdown code fences
    fence_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", cleaned, re.DOTALL)
    if fence_match:
        try:
            return json.loads(fence_match.group(1).strip())
        except json.JSONDecodeError:
            pass

    # Try finding a JSON object anywhere in the text
    brace_match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if brace_match:
        try:
            return json.loads(brace_match.group(0))
        except json.JSONDecodeError:
            pass

    raise json.JSONDecodeError("No valid JSON found in response", cleaned, 0)
