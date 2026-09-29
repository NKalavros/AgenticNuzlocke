"""Extract the first JSON object from model text."""

from __future__ import annotations

import json
import re
from typing import Any

_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def extract_json_object(text: str) -> dict[str, Any] | None:
    if not text:
        return None
    fenced = _FENCE_RE.search(text)
    start, end = text.find("{"), text.rfind("}")
    if fenced:
        candidate = fenced.group(1)
    elif 0 <= start < end:
        candidate = text[start : end + 1]
    else:
        return None
    try:
        value = json.loads(candidate)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None
