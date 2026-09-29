"""What System 1 did, one line per cycle, for System 2 to read at its next look.

Kept at ``runs/<run-id>/journal.jsonl``. Each line says where the player
was, what was chosen and how sure Jev was, what was pressed, what happened
("entered Pallet Town", "moved 5 tiles", "no progress"), and the text on
screen afterwards. System 2 gets the lines since its last look instead of the
raw action history.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_CAP = 40


class Journal:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lines: list[str] = []
        self._mark = 0

    def add(self, entry: dict[str, Any]) -> str:
        line = format_line(entry)
        self.lines.append(line)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({**entry, "line": line}, default=str) + "\n")
        return line

    def since_last_look(self) -> list[str]:
        return self.lines[self._mark :][-_CAP:]

    def looked(self) -> None:
        self._mark = len(self.lines)


def format_line(entry: dict[str, Any]) -> str:
    where = f"{entry.get('map')} ({entry.get('x')},{entry.get('y')})"
    choice = entry.get("choice") or entry.get("kind") or "-"
    if entry.get("p") is not None:
        choice += f" p={float(entry['p']):.2f}"
    label = entry.get("label")
    actions = _squash(entry.get("actions") or [])
    parts = [f"c{entry.get('cycle')} {where}: {choice}"]
    if label:
        parts[0] += f" ({label})"
    parts.append(f"pressed {actions}" if actions else "pressed nothing")
    parts.append(str(entry.get("outcome") or "ok"))
    if entry.get("text"):
        parts.append(f"text: {entry['text']!r}")
    return " | ".join(parts)


def _squash(actions: list[str]) -> str:
    """``walk_up, walk_up, walk_up`` reads as ``walk_up x3``."""
    out: list[str] = []
    for action in actions:
        if out and out[-1].split(" x")[0] == action:
            head, _, count = out[-1].partition(" x")
            out[-1] = f"{head} x{int(count or 1) + 1}"
        else:
            out.append(action)
    return ", ".join(out)


def outcome(
    before: Any, after: Any, *, moved_tiles: int, text: str | None, stopped: str | None
) -> str:
    """One phrase for what a cycle's presses did."""
    if after.in_battle and not before.in_battle:
        return "a battle started"
    if (after.map_id, after.map_name) != (before.map_id, before.map_name):
        return f"entered {after.map_name}"
    if text:
        return "text opened" if moved_tiles == 0 else f"moved {moved_tiles} tiles, text opened"
    if moved_tiles:
        return f"moved {moved_tiles} tiles" + (f", stopped: {stopped}" if stopped else "")
    return "no progress" + (f" ({stopped})" if stopped else "")
