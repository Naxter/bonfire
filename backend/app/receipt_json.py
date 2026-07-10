"""Tolerant JSON extraction from LLM output (handles ```json fences, prose)."""

from __future__ import annotations

import json
import re


def extract_json_object(raw: str) -> dict:
    """Pull the first JSON object out of an LLM response, or return {}."""
    if not raw:
        return {}
    text = raw.strip()
    if "```json" in text:
        text = text.split("```json", 1)[1].split("```", 1)[0].strip()
    elif "```" in text:
        text = text.split("```", 1)[1].split("```", 1)[0].strip()

    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return {}
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return {}
