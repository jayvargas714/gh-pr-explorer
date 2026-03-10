"""Shared JSON parsing utility for AI agent output.

Extracts JSON from fenced code blocks or raw text using brace-depth counting.
Used by executors that parse structured JSON from AI responses.
"""

import json
import re
from typing import Optional


def extract_json(content: str) -> Optional[dict]:
    """Extract a JSON object from AI output text.

    Tries in order:
    1. Fenced ```json code block
    2. Direct json.loads on the stripped text
    3. Brace-depth scanning for the first balanced { ... } pair
    """
    if not content:
        return None

    text = content.strip()

    # Try fenced code block first
    fenced = re.findall(r"```(?:json)?\s*\n(.*?)```", text, re.DOTALL)
    if fenced:
        text = fenced[0].strip()

    # Direct parse
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        pass

    # Brace-depth fallback — string-aware to handle } inside JSON values
    depth = 0
    start_idx = -1
    in_string = False
    escape = False
    for i, ch in enumerate(text):
        if escape:
            escape = False
            continue
        if ch == '\\' and in_string:
            escape = True
            continue
        if ch == '"' and not escape:
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == '{':
            if depth == 0:
                start_idx = i
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0 and start_idx >= 0:
                try:
                    return json.loads(text[start_idx:i + 1])
                except json.JSONDecodeError:
                    start_idx = -1

    return None
