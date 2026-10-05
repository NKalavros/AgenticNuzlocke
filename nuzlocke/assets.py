"""Read packaged, non-executable reference data and prompt text."""

import json
from functools import cache
from pathlib import Path


@cache
def text(name: str) -> str:
    return (Path(__file__).with_name("assets") / name).read_text(encoding="utf-8")


@cache
def data(name: str):
    return json.loads(text(name))
