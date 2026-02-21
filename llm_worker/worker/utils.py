"""Utility functions for the LLM Worker."""

import json
import logging
import re

logger = logging.getLogger(__name__)


def extract_json(text: str) -> dict:
    """Extract the first JSON object from text.

    LLMs often wrap JSON in markdown code blocks or add surrounding text.
    This function finds the first {...} block and parses it.

    Args:
        text: Raw text from LLM response.

    Returns:
        Parsed dict from the JSON block.

    Raises:
        ValueError: If no valid JSON object is found.
    """
    # Try parsing the entire text first
    stripped = text.strip()
    if stripped.startswith("{"):
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            pass

    # Find the first {...} block using brace matching
    match = re.search(r"\{", text)
    if match:
        start = match.start()
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[start : i + 1]
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        break

    raise ValueError(f"No valid JSON object found in text: {text[:200]}")