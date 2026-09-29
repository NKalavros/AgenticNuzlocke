"""Known trainers and bosses (``trainers_red.yaml``), for System 3's briefing and System 2's plans."""

from __future__ import annotations

from functools import cache
from pathlib import Path
from typing import Any

import yaml

_DATA = Path(__file__).with_name("trainers_red.yaml")
# Boss per badge count, in the order the level caps use.
_BOSS_ORDER = ("brock", "misty", "lt_surge", "erika", "koga", "saber", "blaine", "giovanni")


@cache
def trainers() -> tuple[dict[str, Any], ...]:
    return tuple(yaml.safe_load(_DATA.read_text(encoding="utf-8")) or ())


def _team(entry: dict[str, Any]) -> str:
    return ", ".join(f"{species} L{level}" for species, level in entry.get("team") or [])


def on_map(map_id: int | None) -> list[str]:
    """One line per known trainer on this map."""
    lines = []
    for entry in trainers():
        if entry.get("map_id") != map_id:
            continue
        must = {False: "must fight", True: "can be avoided"}.get(entry.get("avoidable"), "")
        line = f"{entry['trainer']}: {_team(entry)}" + (f" ({must})" if must else "")
        lines.append(line + (f". {entry['note']}" if entry.get("note") else ""))
    return lines


def next_boss(badge_count: int) -> str | None:
    """The next gym leader's line, while the data file knows them."""
    if badge_count >= len(_BOSS_ORDER):
        return None
    boss = _BOSS_ORDER[badge_count]
    entry = next((e for e in trainers() if e.get("boss") == boss), None)
    if entry is None:
        return None
    return f"next boss {entry['trainer']} ({entry['map']}): {_team(entry)}. {entry.get('note', '')}".strip()
