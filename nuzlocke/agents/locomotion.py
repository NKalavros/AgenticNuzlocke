"""Steps from the on-screen walk grid.

A screenshot that says "walk left" is a glance, not a heading to hold. The beat
names the direction that matters. While the tiles that way are open, walk them
in one run, up to five. When the next tile is blocked, step to one open side
and try the heading again on the next cycle. A sidestep is never stored as the
new heading.
"""

from __future__ import annotations

from typing import NamedTuple

from nuzlocke.state.models import GameAction, PlayerObservation

_DELTA = {"up": (-1, 0), "down": (1, 0), "left": (0, -1), "right": (0, 1)}
_LATERAL = {
    "up": ("left", "right"),
    "down": ("left", "right"),
    "left": ("up", "down"),
    "right": ("up", "down"),
}
_OPPOSITE = {"up": "down", "down": "up", "left": "right", "right": "left"}
_ACTION = {name: GameAction(f"walk_{name}") for name in _DELTA}


class TileStep(NamedTuple):
    action: GameAction | None
    reason: str
    choices: tuple[GameAction, ...] = ()


def _parsed_grid(text: str | None) -> tuple[list[list[str]], tuple[int, int]] | None:
    """Walk-grid rows and the ``@`` cell. None when the grid cannot be read."""
    rows = [
        [part for part in line.split() if part in {".", "#", "@"}]
        for line in (text or "").splitlines()
    ]
    rows = [row for row in rows if row]
    for row_index, row in enumerate(rows):
        if "@" in row:
            return rows, (row_index, row.index("@"))
    return None


def _cell(rows: list[list[str]], row_index: int, col_index: int) -> str | None:
    if 0 <= row_index < len(rows) and 0 <= col_index < len(rows[row_index]):
        return rows[row_index][col_index]
    return None


def neighbors_from_ascii(text: str | None) -> dict[str, bool]:
    """Adjacent cells around ``@``; True means ``.`` (walkable). Empty when there is no grid."""
    parsed = _parsed_grid(text)
    if parsed is None:
        return {}
    rows, (row, col) = parsed
    return {
        name: _cell(rows, row + d_row, col + d_col) == "."
        for name, (d_row, d_col) in _DELTA.items()
    }


def tile_at(text: str | None, d_col: int, d_row: int) -> str | None:
    """The cell ``d_col`` east and ``d_row`` south of ``@``, or None off the grid.

    ``d_row`` follows the walk grid: up is negative, the same axis as a change
    in the player's y.
    """
    parsed = _parsed_grid(text)
    if parsed is None:
        return None
    rows, (row, col) = parsed
    return _cell(rows, row + d_row, col + d_col)


def _closed(name: str, blocked: set[str]) -> bool:
    return f"walk_{name}" in blocked


def next_tile(*, heading: str | None, grid: str | None, blocked: set[str]) -> TileStep | None:
    """The next tile toward ``heading``, or a one-tile sidestep when it is shut.

    With no grid, the heading is still the button to press. A direction that
    already failed to move the player is not pressed again.
    """
    if heading not in _ACTION:
        return None
    tiles = neighbors_from_ascii(grid)
    if not tiles:
        return (
            None if _closed(heading, blocked) else TileStep(_ACTION[heading], f"heading {heading}")
        )
    open_dirs = {name for name, open_ in tiles.items() if open_ and not _closed(name, blocked)}
    if heading in open_dirs:
        return TileStep(_ACTION[heading], f"grid open {heading}")
    laterals = [name for name in _LATERAL[heading] if name in open_dirs]
    if len(laterals) == 1:
        return TileStep(_ACTION[laterals[0]], f"{heading} blocked; one open side {laterals[0]}")
    if laterals:
        choices = tuple(_ACTION[name] for name in laterals)
        return TileStep(None, f"{heading} blocked; choose one open side", choices)
    back = _OPPOSITE[heading]
    if back in open_dirs:
        return TileStep(_ACTION[back], f"{heading} blocked; only open tile is {back}")
    return None


def map_context(obs: PlayerObservation) -> dict[str, object] | None:
    """Position plus the walk grid, for the planner and for Jev."""
    grid = (obs.collision_ascii or "").strip()
    if obs.x is None and not grid:
        return None
    if grid:
        note = (
            "On-screen walk grid, read from the tilemap, in the same A-J / 1-9 "
            "cells as the screenshot grid. @ is the player (E5), . can be "
            "entered, # is blocked. up is the row above @. It is usually "
            "right, but a door mat or stairs can read as #, and "
            "blocked_on_tile is what actually failed. The screenshot still "
            "decides whether someone is talking."
        )
    else:
        note = (
            "No walk grid for this map: it is unavailable or it disagreed with "
            "where the player really walked. Read the tiles from the screenshot."
        )
    ctx: dict[str, object] = {"note": note}
    if obs.map_name:
        ctx["map"] = obs.map_name
    if obs.x is not None:
        ctx["x"] = obs.x
        ctx["y"] = obs.y
    if obs.facing:
        ctx["facing"] = obs.facing
    if grid:
        ctx["grid"] = grid
    tiles = neighbors_from_ascii(grid)
    if tiles:
        ctx["tiles"] = {name: "open" if open_ else "blocked" for name, open_ in tiles.items()}
    return ctx


class GridTrust:
    """Whether each map's walk grid has matched where the player really went.

    The grid comes from vanilla pokered collision tables, which Red Star's maps
    do not always follow. A walk that lands on a tile the grid called ``#`` is
    a strike; after ``strikes`` of them the map's grid is withheld from prompts
    and from the step picker until eight corroborating open-tile walks. A press into ``#`` that
    does not move is the grid being right, and a door mat that reads ``#``
    changes the map, so neither counts.
    """

    def __init__(self, strikes: int = 2) -> None:
        self._strikes = max(1, int(strikes))
        self._counts: dict[object, int] = {}
        self._confirmed: dict[object, int] = {}

    @staticmethod
    def _key(obs: PlayerObservation) -> object:
        return obs.map_id if obs.map_id is not None else obs.map_name

    def trusted(self, obs: PlayerObservation) -> bool:
        return self._counts.get(self._key(obs), 0) < self._strikes

    def view(self, obs: PlayerObservation) -> PlayerObservation:
        """``obs`` without its grid when this map's grid has proven wrong."""
        if self.trusted(obs) or not obs.collision_ascii:
            return obs
        return obs.model_copy(update={"collision_ascii": None})

    def record(
        self, before: PlayerObservation, after: PlayerObservation, actions: list[str]
    ) -> bool:
        """Score one step. True when this step just made the map untrusted."""
        if len(actions) != 1:
            return False
        name = actions[0].removeprefix("walk_")
        if name not in _DELTA or not before.collision_ascii:
            return False
        if self._key(before) != self._key(after):
            return False
        if None in (before.x, before.y, after.x, after.y):
            return False
        d_row, d_col = _DELTA[name]
        if (after.x - before.x, after.y - before.y) != (d_col, d_row):
            return False
        tiles = neighbors_from_ascii(before.collision_ascii)
        if not tiles or tiles.get(name):
            return False
        return self._strike(before)

    def record_path(self, before: PlayerObservation, steps: list[dict[str, object]]) -> bool:
        """Score each walk of a burst, ``(x0, y0)`` to ``(x1, y1)``, against the grid at its start.

        A walk that does not move is not a strike, and a map change ends the
        scoring. True when this burst is what made the map untrusted.
        """
        if not before.collision_ascii or before.x is None or before.y is None:
            return False
        crossed = False
        for step in steps:
            name = str(step.get("action") or "").removeprefix("walk_")
            if name not in _DELTA:
                continue
            if step.get("map_name") and before.map_name and step["map_name"] != before.map_name:
                break
            if (
                before.map_id is not None
                and step.get("map_id") is not None
                and step["map_id"] != before.map_id
            ):
                break
            x0, y0, x1, y1 = (step.get(key) for key in ("x0", "y0", "x1", "y1"))
            if None in (x0, y0, x1, y1):
                continue
            d_row, d_col = _DELTA[name]
            if (int(x1) - int(x0), int(y1) - int(y0)) != (d_col, d_row):  # type: ignore[arg-type]
                continue
            cell = tile_at(
                before.collision_ascii,
                int(x1) - int(before.x),  # type: ignore[arg-type]
                int(y1) - int(before.y),  # type: ignore[arg-type]
            )
            key = self._key(before)
            if cell == ".":
                self._confirmed[key] = self._confirmed.get(key, 0) + 1
                if self._confirmed[key] >= 8:
                    self._counts[key] = 0
            elif cell == "#":
                self._confirmed[key] = 0
            if cell == "#" and self._strike(before):
                crossed = True
        return crossed

    def _strike(self, obs: PlayerObservation) -> bool:
        was_trusted = self.trusted(obs)
        key = self._key(obs)
        self._counts[key] = self._counts.get(key, 0) + 1
        return was_trusted and not self.trusted(obs)
