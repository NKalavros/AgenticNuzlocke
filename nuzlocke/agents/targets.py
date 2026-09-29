"""Places worth walking to, with the first step of a path to each.

Targets are the planner's named cell plus the map's warps, signs, and NPCs
from WRAM. They are written onto Jev's button options ("first step of the
path to the door, 3 tiles"); nothing here walks on its own.

The screen is the 10×9 walk grid with the player at E5. A map tile
``(tx, ty)`` is cell ``(4 + tx - x, 4 + ty - y)``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from pokemon_agent.pathfinding import find_path

from nuzlocke.agents.locomotion import _parsed_grid
from nuzlocke.state.models import PlayerObservation

_COLS = "ABCDEFGHIJ"
_PLAYER_COL = 4
_PLAYER_ROW = 4
_CELL = re.compile(r"^\s*([A-Ja-j])\s*([1-9])\s*$")
_STEP = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}
_LAST_MAP = 255
# Sprite picture ids read on Red Star (pokered's sprite constants).
_PICTURES = {
    2: "rival",
    3: "Prof. Oak",
    13: "girl",
    32: "scientist",
    74: "item ball",
    78: "Pokédex",
}


@dataclass(frozen=True)
class Target:
    label: str
    x: int
    y: int
    # A warp is entered; a person, sign, or ball is faced and talked to with A.
    enter: bool
    distance: int
    cell: str | None = None
    # The first walk of an on-screen path, or a straight-line guess when there is none.
    first_step: str | None = None
    path_len: int | None = None

    def as_state(self) -> dict[str, Any]:
        out: dict[str, Any] = {"what": self.label, "tiles_away": self.distance}
        if self.cell:
            out["cell"] = self.cell
        if self.first_step:
            out["first_step"] = f"walk_{self.first_step}"
        if self.path_len is not None:
            out["path_tiles"] = self.path_len
        return out


def cell_to_tile(cell: str | None, obs: PlayerObservation) -> tuple[int, int] | None:
    """The map tile under a screen cell like ``G7``, from where the player stands now."""
    match = _CELL.match(cell or "")
    if match is None or obs.x is None or obs.y is None:
        return None
    col = _COLS.index(match.group(1).upper())
    row = int(match.group(2)) - 1
    return obs.x + col - _PLAYER_COL, obs.y + row - _PLAYER_ROW


def tile_to_cell(x: int, y: int, obs: PlayerObservation) -> str | None:
    if obs.x is None or obs.y is None:
        return None
    col = _PLAYER_COL + x - obs.x
    row = _PLAYER_ROW + y - obs.y
    if 0 <= col < len(_COLS) and 0 <= row < 9:
        return f"{_COLS[col]}{row + 1}"
    return None


def _walkable(obs: PlayerObservation, blocked_tiles: set[tuple[int, int]]) -> dict | None:
    """``find_path``'s collision map in map tiles, from the on-screen grid."""
    parsed = _parsed_grid(obs.collision_ascii)
    if parsed is None or obs.x is None or obs.y is None:
        return None
    rows, (p_row, p_col) = parsed
    walkable = {}
    for row_index, row in enumerate(rows):
        for col_index, cell in enumerate(row):
            tile = (obs.x + col_index - p_col, obs.y + row_index - p_row)
            walkable[tile] = cell in {".", "@"} and tile not in blocked_tiles
    return walkable


def _straight(dx: int, dy: int) -> str | None:
    if dx == dy == 0:
        return None
    if abs(dx) >= abs(dy):
        return "right" if dx > 0 else "left"
    return "down" if dy > 0 else "up"


def _route(
    obs: PlayerObservation, goal: tuple[int, int], *, enter: bool, walkable: dict | None
) -> tuple[str | None, int | None]:
    """First step and length of an on-screen path; a straight-line step without one."""
    start = (obs.x, obs.y)
    dx, dy = goal[0] - obs.x, goal[1] - obs.y
    if walkable is not None and goal in walkable:
        if enter:
            # Door mats and stairs read # on the grid. The warp itself is the goal.
            ends = [goal]
        else:
            # Stand next to it; the last walk turns the player to face it.
            ends = [
                (goal[0] - sx, goal[1] - sy)
                for sx, sy in _STEP.values()
                if walkable.get((goal[0] - sx, goal[1] - sy))
            ]
        best: list[str] | None = None
        for end in ends:
            grid = dict(walkable)
            grid[end] = True
            path = [] if end == start else find_path(start, end, grid, max_iterations=2_000)
            if end != start and not path:
                continue
            if not enter:
                # Face the goal from ``end``.
                path = [*path, _straight(goal[0] - end[0], goal[1] - end[1])]
            if best is None or len(path) < len(best):
                best = path
        if best:
            return best[0], len(best)
    return _straight(dx, dy), None


def build_targets(
    obs: PlayerObservation, *, plan_target: dict[str, Any] | None = None, limit: int = 5
) -> list[Target]:
    """Nearest first; the planner's target leads whatever its distance."""
    if obs.x is None or obs.y is None:
        return []
    npc_tiles = {(int(npc["x"]), int(npc["y"])) for npc in obs.npcs if npc.get("on_screen", True)}
    walkable = _walkable(obs, npc_tiles)
    found: list[tuple[str, int, int, bool]] = []
    seen_warps: set[int] = set()
    for warp in sorted(obs.warps, key=lambda w: abs(w["x"] - obs.x) + abs(w["y"] - obs.y)):
        dest = int(warp.get("dest_map", -1))
        if dest in seen_warps:
            # A two-tile door is one target: the nearer tile.
            continue
        seen_warps.add(dest)
        label = "exit (door or stairs out)" if dest == _LAST_MAP else f"warp to map {dest}"
        found.append((label, int(warp["x"]), int(warp["y"]), True))
    for sign in obs.signs:
        found.append(("sign", int(sign["x"]), int(sign["y"]), False))
    for npc in obs.npcs:
        if not npc.get("on_screen", True):
            continue
        label = _PICTURES.get(int(npc.get("picture", 0)), "person")
        found.append((label, int(npc["x"]), int(npc["y"]), False))
    found.sort(key=lambda item: abs(item[1] - obs.x) + abs(item[2] - obs.y))
    if plan_target and plan_target.get("x") is not None:
        found.insert(
            0,
            (
                f"planner target: {plan_target.get('label') or 'goal'}",
                int(plan_target["x"]),
                int(plan_target["y"]),
                bool(plan_target.get("enter", True)),
            ),
        )
    targets = []
    for label, x, y, enter in found[:limit]:
        first, length = _route(obs, (x, y), enter=enter, walkable=walkable)
        targets.append(
            Target(
                label=label,
                x=x,
                y=y,
                enter=enter,
                distance=abs(x - obs.x) + abs(y - obs.y),
                cell=tile_to_cell(x, y, obs),
                first_step=first,
                path_len=length,
            )
        )
    return targets


def facing_target(obs: PlayerObservation, targets: list[Target]) -> Target | None:
    """The talkable target on the tile the player faces."""
    if obs.x is None or obs.y is None or obs.facing not in _STEP:
        return None
    sx, sy = _STEP[obs.facing]
    front = (obs.x + sx, obs.y + sy)
    return next((t for t in targets if not t.enter and (t.x, t.y) == front), None)


class ObjectTrust:
    """Whether each map's WRAM objects have matched where the map really changed.

    A map change after a walk from a tile that is not on or next to a listed
    warp is a strike. After ``strikes`` of them the map's warps, signs, and
    NPCs are withheld for the rest of the run: they come from the same tables.
    """

    def __init__(self, strikes: int = 2) -> None:
        self._strikes = max(1, int(strikes))
        self._counts: dict[object, int] = {}

    @staticmethod
    def _key(obs: PlayerObservation) -> object:
        return obs.map_id if obs.map_id is not None else obs.map_name

    def trusted(self, obs: PlayerObservation) -> bool:
        return self._counts.get(self._key(obs), 0) < self._strikes

    def view(self, obs: PlayerObservation) -> PlayerObservation:
        if self.trusted(obs) or not (obs.warps or obs.signs or obs.npcs):
            return obs
        return obs.model_copy(update={"warps": [], "signs": [], "npcs": []})

    def record(
        self,
        before: PlayerObservation,
        after: PlayerObservation,
        walks: list[dict[str, Any]] | None = None,
    ) -> bool:
        """Score one cycle's map change. True when it just made the map untrusted."""
        if not before.warps or self._key(before) == self._key(after):
            return False
        last = (before.x, before.y)
        for step in walks or []:
            if step.get("x0") is not None:
                # The tile the walk started on: next to a door, or the mat itself.
                last = (step["x0"], step["y0"])
            if step.get("map_id") is not None and step["map_id"] != before.map_id:
                break
            if step.get("x1") is not None:
                last = (step["x1"], step["y1"])
        if None in last:
            return False
        near = any(abs(w["x"] - last[0]) + abs(w["y"] - last[1]) <= 1 for w in before.warps)
        if near:
            return False
        was = self.trusted(before)
        key = self._key(before)
        self._counts[key] = self._counts.get(key, 0) + 1
        return was and not self.trusted(before)
