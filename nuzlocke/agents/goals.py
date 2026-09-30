"""System 1 overworld goals: what Jev chooses between, and the buttons each one becomes.

Jev picks a goal ("exit to Pallet Town", "talk to Prof. Oak", "north edge",
"explore"), not a joystick press. Code turns the pick into an A* path and
presses it as one burst. Each option's description carries the facts Jev
needs: distance, whether a path exists, whether it is the current objective,
and how often it already failed on this visit.

Paths run over the best map knowledge there is: the tilemap walk grid when it
is trusted, plus every tile the player has actually stood on (``RoomMap``),
minus tiles a walk bumped into and tiles an NPC stands on. On a map whose grid
is withheld (Oak's Lab), unknown tiles are tried optimistically and each bump
is remembered, so the room is learned by walking it.
"""

from __future__ import annotations

import heapq
import re
from dataclasses import dataclass, field
from typing import Any

from nuzlocke.agents.locomotion import _parsed_grid
from nuzlocke.environment.maps import map_name
from nuzlocke.environment.terrain import step_delta
from nuzlocke.knowledge.objects import object_facts
from nuzlocke.state.models import GameAction, PlayerObservation

DIRS = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}
OPPOSITE = {"up": "down", "down": "up", "left": "right", "right": "left"}
_WALK = {name: GameAction(f"walk_{name}") for name in DIRS}
_WALK.update({f"jump_{name}": GameAction(f"walk_{name}") for name in ("down", "left", "right")})
# A burst stops at a text box, a prompt, a battle, a map change, or a walk that does not move.
MAX_BURST = 8
# A bump by a wandering NPC must not become a permanent wall.
_BLOCK_TTL = 6
_FAILS_BEFORE_RUNNER_UP = 2

Tile = tuple[int, int]

_ITEM_BALL = 74
_CELL = re.compile(r"^\s*([A-Ja-j])\s*([1-9])\s*$")


def cell_to_tile(cell: str | None, obs: PlayerObservation) -> Tile | None:
    """The map tile under a screen cell like ``G7``; the player is always at E5."""
    match = _CELL.match(cell or "")
    if match is None or obs.x is None or obs.y is None:
        return None
    col = "ABCDEFGHIJ".index(match.group(1).upper())
    return obs.x + col - 4, obs.y + int(match.group(2)) - 5


def map_key(obs: PlayerObservation) -> Any:
    return obs.map_id if obs.map_id is not None else obs.map_name


def _manhattan(a: Tile, b: Tile) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


class RoomMap:
    """Per map: the walk grid of every screen seen, tiles stood on, and tiles bumped into.

    Remembering the grid lets a path run across the whole known map, not just the 10x9 screen:
    Viridian Forest's maze sent screen-only paths back into the same dead ends for hours.
    """

    def __init__(self) -> None:
        self.visited: dict[Any, set[Tile]] = {}
        self.known: dict[Any, dict[Tile, bool]] = {}
        self._blocked: dict[Any, dict[Tile, int]] = {}
        self.cycle = 0
        self.edge_blocks: dict[Any, dict[tuple[int, int, str], int]] = {}
        self.crossed_edges: dict[Any, set[tuple[int, int, str]]] = {}
        self.terrain_tiles: dict[Any, dict[Tile, tuple[int, int]]] = {}
        self.costs: dict[Tile, float] = {}

    def visit(self, obs: PlayerObservation) -> None:
        self.cycle += 1
        if obs.x is None or obs.y is None:
            return
        tile = (obs.x, obs.y)
        self.visited.setdefault(map_key(obs), set()).add(tile)
        self._blocked.get(map_key(obs), {}).pop(tile, None)
        from nuzlocke.environment.screen_text import find_boxes

        if not obs.in_battle and not obs.cutscene and not find_boxes(obs.screen_rows):
            self.known.setdefault(map_key(obs), {}).update(_grid_tiles(obs))
            self.terrain_tiles.setdefault(map_key(obs), {}).update(
                {(t["x"], t["y"]): (t["tileset"], t["id"]) for t in obs.terrain_tiles}
            )

    def record_walks(self, before: PlayerObservation, walks: list[dict[str, Any]]) -> None:
        """Every tile a burst stood on is open; a walk that did not move marks the tile ahead."""
        key = map_key(before)
        for step in walks:
            if step.get("map_id") is not None and step["map_id"] != before.map_id:
                break
            x0, y0, x1, y1 = (step.get(name) for name in ("x0", "y0", "x1", "y1"))
            if None in (x0, y0, x1, y1):
                continue
            if (x0, y0) != (x1, y1):
                edge = (x0, y0, str(step.get("action", "")).removeprefix("walk_"))
                self.edge_blocks.get(key, {}).pop(edge, None)
                delta = DIRS.get(edge[2])
                if delta and (x1 - x0, y1 - y0) == delta:
                    # A verified crossing overrides vanilla terrain in a ROM hack.
                    # A two-tile jump does not prove the intermediate edge is walkable.
                    self.crossed_edges.setdefault(key, set()).add(edge)
                self.visited.setdefault(key, set()).add((x1, y1))
                continue
            direction = str(step.get("action") or "").removeprefix("walk_")
            if direction in DIRS and step.get("blocked", True):
                self.edge_blocks.setdefault(key, {})[(x0, y0, direction)] = self.cycle

    def blocked_edges(self, obs: PlayerObservation) -> set[tuple[int, int, str]]:
        return self.terrain_edges(obs) | self.temporary_edges(obs)

    def terrain_edges(self, obs: PlayerObservation) -> set[tuple[int, int, str]]:
        from nuzlocke.environment.terrain import pair_blocked
        from nuzlocke.knowledge.map_reference import reference

        data = reference(obs)
        blocked = {tuple(edge) for edge in (data or {}).get("blocked_edges", [])}
        tiles = self.terrain_tiles.get(map_key(obs), {})
        for (x, y), tile in tiles.items():
            for direction, (dx, dy) in DIRS.items():
                other = tiles.get((x + dx, y + dy))
                if other is not None:
                    edge = (x, y, direction)
                    blocked.discard(edge)
                    if pair_blocked(tile, other):
                        blocked.add(edge)
        return blocked - self.crossed_edges.get(map_key(obs), set())

    def temporary_edges(self, obs: PlayerObservation) -> set[tuple[int, int, str]]:
        return {
            edge
            for edge, at in self.edge_blocks.get(map_key(obs), {}).items()
            if self.cycle - at <= 6
        }

    def blocked(self, obs: PlayerObservation) -> set[Tile]:
        stamps = self._blocked.get(map_key(obs), {})
        return {tile for tile, at in stamps.items() if self.cycle - at <= _BLOCK_TTL}

    def seen(self, obs: PlayerObservation) -> set[Tile]:
        return self.visited.get(map_key(obs), set())


@dataclass
class Goal:
    key: str
    kind: str  # objective | exit | edge | talk | explore | heading | wait
    label: str
    actions: list[GameAction]
    facts: list[str] = field(default_factory=list)
    # The walk directions of the path, for anti-pacing and the journal.
    path: list[str] = field(default_factory=list)
    objective: bool = False
    # What an exit leads to, or who a talk goal is for (matched against the objective).
    dest_map: int | None = None
    raw_dest_map: int | None = None
    warp_tiles: list[Tile] = field(default_factory=list)
    picture: int | None = None
    name: str = ""
    finish: GameAction | None = None
    complete: bool = False  # True for an exit reached by a full observed path.

    def criterion(self) -> str:
        return "; ".join([self.label, *self.facts])


def _grid_tiles(obs: PlayerObservation) -> dict[Tile, bool]:
    """The trusted walk grid in map tiles, or nothing when it is missing or boxes the player in."""
    parsed = _parsed_grid(obs.collision_ascii)
    if parsed is None or obs.x is None or obs.y is None or _boxed_in(*parsed):
        return {}
    rows, (p_row, p_col) = parsed
    # At an indoor entrance the only '.' can be the adjacent door mat. That is
    # still a trapped player once non-goal warps are excluded from paths.
    obstructions = {(w["x"], w["y"]) for w in obs.warps}
    obstructions |= {(n["x"], n["y"]) for n in obs.npcs if n.get("on_screen", True)}
    usable = False
    for dx, dy in DIRS.values():
        r, c = p_row + dy, p_col + dx
        if (
            0 <= r < len(rows)
            and 0 <= c < len(rows[r])
            and rows[r][c] in {".", "@"}
            and (obs.x + dx, obs.y + dy) not in obstructions
        ):
            usable = True
    if not usable:
        return {}
    return {
        (obs.x + col_index - p_col, obs.y + row_index - p_row): cell in {".", "@"}
        for row_index, row in enumerate(rows)
        for col_index, cell in enumerate(row)
    }


def collision_map(obs: PlayerObservation, room: RoomMap) -> dict[Tile, bool] | None:
    """Which tiles can be walked: every screen seen on this map, the current grid over it, the
    tiles walked, minus bumps, NPCs, and doors that are not the goal."""
    if obs.x is None or obs.y is None:
        return None
    walkable: dict[Tile, bool] = dict(room.known.get(map_key(obs), {}))
    screen = _grid_tiles(obs)
    if screen:
        walkable.update(screen)
    else:
        # No trusted grid: every on-screen tile is worth one try.
        for dx in range(-4, 6):
            for dy in range(-4, 5):
                walkable.setdefault((obs.x + dx, obs.y + dy), True)
    for tile in room.seen(obs):
        walkable[tile] = True
    from nuzlocke.knowledge.map_reference import ledge_jumps

    for x, y, d in ledge_jumps(obs, room):
        dx, dy = DIRS[d]
        walkable[x + dx, y + dy] = False
    for tile in room.blocked(obs):
        walkable[tile] = False
    for npc in obs.npcs:
        if npc.get("on_screen", True):
            walkable[(int(npc["x"]), int(npc["y"]))] = False
    # A door on the way is a map change, not a tile to cross. It is walkable only as a goal.
    for warp in obs.warps:
        walkable[(int(warp["x"]), int(warp["y"]))] = False
    if obs.map_size:
        width, height = obs.map_size.get("w", 0), obs.map_size.get("h", 0)
        if width and height:
            walkable = {
                (x, y): open_
                for (x, y), open_ in walkable.items()
                if 0 <= x < width and 0 <= y < height
            }
    walkable[(obs.x, obs.y)] = True
    return walkable


class Routes:
    """Minimum-cost paths from the player; uniform costs reduce to shortest walks."""

    def __init__(
        self,
        start: Tile,
        walkable: dict[Tile, bool],
        limit: int = 4000,
        seen: set[Tile] | None = None,
        size: tuple[int, int] | None = None,
        costs: dict[Tile, float] | None = None,
        blocked_edges: set[tuple[int, int, str]] | None = None,
        crossed_edges: set[tuple[int, int, str]] | None = None,
        terrain_edges: set[tuple[int, int, str]] | None = None,
        jumps: dict[tuple[int, int, str], Tile] | None = None,
    ) -> None:
        self.start = start
        self.walkable = walkable
        self.seen = seen or set()
        self.size = size
        self.blocked_edges = blocked_edges or set()
        self.crossed_edges = crossed_edges or set()
        self.terrain_edges = terrain_edges
        self.jumps = jumps or {}
        self.paths: dict[Tile, list[str]] = {start: []}
        distance = {start: 0.0}
        queue = [(0.0, start)]
        while queue and len(self.paths) < limit:
            total, here = heapq.heappop(queue)
            if total != distance[here]:
                continue
            for name, (dx, dy) in DIRS.items():
                jump = self.jumps.get((*here, name))
                tile = jump or (here[0] + dx, here[1] + dy)
                if (here[0], here[1], name) in self.blocked_edges or not walkable.get(tile):
                    continue
                cost = total + max(1.0, (costs or {}).get(tile, 1.0))
                if cost < distance.get(tile, float("inf")):
                    distance[tile] = cost
                    self.paths[tile] = [*self.paths[here], f"jump_{name}" if jump else name]
                    heapq.heappush(queue, (cost, tile))

    def onto(self, tile: Tile) -> list[str] | None:
        """Walk onto ``tile``, which may be a door or other tile the map marks shut."""
        if tile in self.paths:
            return self.paths[tile]
        entries = [
            [*self.paths[(tile[0] - dx, tile[1] - dy)], name]
            for name, (dx, dy) in DIRS.items()
            if (tile[0] - dx, tile[1] - dy) in self.paths
            and (tile[0] - dx, tile[1] - dy, name) not in self.blocked_edges
        ]
        return min(entries, key=len) if entries else None

    def facing(self, tile: Tile, sides: tuple[str, ...]) -> list[str] | None:
        """Stand next to ``tile`` on one of ``sides`` and turn to face it."""
        entries = [
            [*self.paths[stand], OPPOSITE[side]]
            for side in sides
            if (stand := (tile[0] + DIRS[side][0], tile[1] + DIRS[side][1])) in self.paths
        ]
        return min(entries, key=len) if entries else None

    def furthest(self, side: str) -> list[str] | None:
        """The nearest reachable tile that gets furthest toward ``side``, if any beats here."""
        dx, dy = DIRS[side]

        def reach(tile: Tile) -> int:
            return tile[0] * dx + tile[1] * dy

        best = max(self.paths, key=lambda tile: (reach(tile), -len(self.paths[tile])))
        return self.paths[best] if reach(best) > reach(self.start) else None

    def closest(self, tile: Tile) -> list[str] | None:
        """Toward a target with no known way in: the unvisited reachable tile nearest to it.

        Heading for the nearest tile of any kind walked Viridian Forest's maze into the same
        dead-end pocket forty times. A tile already stood on no longer pulls, so the search
        works its way around walls. With nothing new in reach, any tile that is strictly nearer.
        """
        fresh = [t for t in self.paths if t not in self.seen and t != self.start]
        # New ground is where the known map ends: a reachable tile next to one never seen.
        frontier = [t for t in self.paths if t != self.start and self._borders_unknown(t)]
        pool = frontier or fresh or list(self.paths)
        best = min(pool, key=lambda t: (_manhattan(t, tile), len(self.paths[t])))
        if not (frontier or fresh) and _manhattan(best, tile) >= _manhattan(self.start, tile):
            return None
        return self.paths[best][:MAX_BURST] or None

    def _borders_unknown(self, tile: Tile) -> bool:
        for dx, dy in DIRS.values():
            near = (tile[0] + dx, tile[1] + dy)
            inside = self.size is None or (
                0 <= near[0] < self.size[0] and 0 <= near[1] < self.size[1]
            )
            if inside and near not in self.walkable:
                return True
        return False

    def slide(self, side: str, toward: str) -> list[str] | None:
        """Along a shut edge: the reachable tile on this row or column furthest ``toward``."""
        dx, dy = DIRS[side]
        lx, ly = DIRS[toward]
        level = self.start[0] * dx + self.start[1] * dy
        row = [tile for tile in self.paths if tile[0] * dx + tile[1] * dy == level]
        best = max(row, key=lambda tile: tile[0] * lx + tile[1] * ly)
        return self.paths[best][:MAX_BURST] if best != self.start else None

    def frontier(self, seen: set[Tile]) -> list[str] | None:
        """The nearest reachable tile never stood on, two or more steps away."""
        for tile, path in self.paths.items():  # BFS order: nearest first
            if len(path) >= 2 and tile not in seen:
                return path
        return None

    def step(self, direction: str | None) -> str | None:
        """``direction`` as a blind first step, unless the tile that way is known to be shut."""
        if direction is None:
            return None
        dx, dy = DIRS[direction]
        return (
            direction
            if self.walkable.get((self.start[0] + dx, self.start[1] + dy), True)
            and (*self.start, direction) not in self.blocked_edges
            else None
        )


def _boxed_in(rows: list[list[str]], at: tuple[int, int]) -> bool:
    """All four neighbours read #: the player walked here, so the grid is wrong (Oak's Lab)."""
    row, col = at
    around = [(row - 1, col), (row + 1, col), (row, col - 1), (row, col + 1)]
    return all(
        not (0 <= r < len(rows) and 0 <= c < len(rows[r])) or rows[r][c] == "#" for r, c in around
    )


def _straight(dx: int, dy: int) -> str | None:
    if dx == dy == 0:
        return None
    if abs(dx) >= abs(dy):
        return "right" if dx > 0 else "left"
    return "down" if dy > 0 else "up"


def build_goals(
    obs: PlayerObservation,
    room: RoomMap,
    *,
    objective: dict[str, Any] | None = None,
    objective_text: str | None = None,
    heading: str | None = None,
    tried: dict[str, int] | None = None,
    last_direction: str | None = None,
    last_texts: dict[str, str] | None = None,
) -> list[Goal]:
    """The goal menu for this overworld cycle, objective first. Goals with no move are dropped."""
    from nuzlocke.knowledge.map_reference import guided_path, ledge_jumps

    if obs.x is None or obs.y is None:
        return []
    start = (obs.x, obs.y)
    size = (obs.map_size or {}).get("w"), (obs.map_size or {}).get("h")
    routes = Routes(
        start,
        collision_map(obs, room) or {start: True},
        seen=room.seen(obs),
        size=size if all(size) else None,
        costs=room.costs,
        blocked_edges=room.blocked_edges(obs),
        crossed_edges=room.crossed_edges.get(map_key(obs), set()),
        terrain_edges=room.terrain_edges(obs),
        jumps=ledge_jumps(obs, room),
    )

    def toward(tile: Tile) -> str | None:
        return routes.step(_straight(tile[0] - start[0], tile[1] - start[1]))

    goals: list[Goal] = []
    # Adjacent mats form one door; disconnected doors retain distinct identities.
    clusters: list[tuple[int, list[Tile]]] = []
    for warp in obs.warps:
        dest, tile = int(warp.get("dest_map", -1)), (int(warp["x"]), int(warp["y"]))
        group = next(
            (
                tiles
                for d, tiles in clusters
                if d == dest and any(_manhattan(t, tile) <= 1 for t in tiles)
            ),
            None,
        )
        if group is None:
            clusters.append((dest, [tile]))
        else:
            group.append(tile)
    for dest, tiles in clusters:
        entries = [(tile, routes.onto(tile)) for tile in tiles]
        reachable = [(tile, path) for tile, path in entries if path is not None]
        if reachable:
            tile, path = min(reachable, key=lambda pair: len(pair[1]))
        else:
            tile = min(tiles, key=lambda t: _manhattan(start, t))
            path = None
        resolved = obs.return_map if dest == 255 and obs.return_map is not None else dest
        name = map_name(resolved)
        anchor = min(tiles)
        duplicate = sum(d == dest for d, _ in clusters) > 1
        key = f"exit_{dest}" + (f"_{anchor[0]}_{anchor[1]}" if duplicate else "")
        goal = _goal(
            key,
            "exit",
            f"door or stairs to {name}",
            path,
            extra=[_exit_step(obs, tile, path)],
            fallback=toward(tile),
            distance=_manhattan(start, tile),
            partial=None
            if path is not None
            else (guided_path(obs, routes, [tile]) or routes.closest(tile)),
        )
        goal.dest_map, goal.raw_dest_map = resolved, dest
        goal.warp_tiles = tiles
        goal.complete = path is not None
        goals.append(goal)

    goals.extend(_edge_goal(obs, side, routes) for side in obs.connections)

    # People, balls, and signs. Signs and balls answer from below: a starter ball faced from
    # the side in Oak's Lab ignored A (AGENTS pitfall #9).
    # Keys stay the same while the player moves: a sprite slot, or a sign's tile.
    def wanted(npc):
        if not objective or objective.get("kind") != "npc":
            return False
        if objective.get("slot") is not None:
            return npc.get("slot") == objective["slot"]
        return objective.get("picture") == npc.get("picture") or bool(
            objective.get("name")
            and str(objective["name"]).casefold() in object_facts(obs, npc)["name"].casefold()
        )

    wanted_keys = {f"talk_{npc.get('slot', 0)}" for npc in obs.npcs if wanted(npc)}
    talkers: list[tuple[str, str, Tile, tuple[str, ...], int | None]] = [
        (
            f"talk_{npc.get('slot', 0)}",
            object_facts(obs, npc)["name"],
            (int(npc["x"]), int(npc["y"])),
            ("down",) if int(npc.get("picture", 0)) in {_ITEM_BALL, 75} else tuple(DIRS),
            int(npc.get("picture", 0)),
        )
        for npc in obs.npcs
        if npc.get("on_screen", True) or wanted(npc)
    ]
    talkers += [
        (f"sign_{s['x']}_{s['y']}", "sign", (int(s["x"]), int(s["y"])), ("down",), None)
        for s in obs.signs
    ]
    talkers.sort(key=lambda item: (item[0] not in wanted_keys, _manhattan(start, item[2])))
    for key, label, tile, sides, picture in talkers[:6]:
        path = routes.facing(tile, sides)
        goal = _goal(
            key,
            "talk",
            f"talk to the {label}" if label != "sign" else "read the sign",
            path,
            extra=[],
            fallback=toward(tile),
            distance=_manhattan(start, tile),
            finish=GameAction.PRESS_A,
            partial=None
            if path is not None
            else (
                guided_path(
                    obs, routes, [(tile[0] + DIRS[s][0], tile[1] + DIRS[s][1]) for s in sides]
                )
                or routes.closest(tile)
            ),
        )
        goal.picture, goal.name = picture, label
        goal.facts.append(f"Object at map tile ({tile[0]},{tile[1]}); face it and press A")
        if picture == 75:
            goal.facts.append(
                "Fossil: approach from below and confirm YES; bag receipt opens the exit"
            )
        if any(
            f"talk_{n.get('slot', 0)}" == key and not n.get("on_screen", True) for n in obs.npcs
        ):
            goal.facts.append("Off screen or hidden; verify the object on arrival")
        goals.append(goal)

    goals.append(
        _goal(
            "explore",
            "explore",
            "explore: walk to the nearest tile not visited yet",
            routes.frontier(room.seen(obs)),
            extra=[],
            fallback=None,
            distance=0,
            more=[f"{len(room.seen(obs))} tiles of this map visited"],
        )
    )
    if heading in DIRS:
        goals.append(
            _goal(
                f"heading_{heading}",
                "heading",
                f"walk {_COMPASS[heading]} (the story direction)",
                _heading_run(start, heading, routes.walkable),
                extra=[],
                fallback=None,
                distance=0,
            )
        )
    goals.append(
        Goal(
            key="wait",
            kind="wait",
            label="wait: let a scene play out (someone is walking or talking)",
            actions=[GameAction.WAIT_60],
        )
    )

    _mark_objective(goals, obs, objective, objective_text, routes)
    goals = [goal for goal in goals if goal.actions or goal.objective]
    for goal in goals:
        count = (tried or {}).get(goal.key, 0)
        if count:
            goal.facts.append(f"picked {count}x on this map with no progress; try another")
        if (last_texts or {}).get(goal.key):
            goal.facts.append(f"last time it ended in the text {last_texts[goal.key]!r}")
        if last_direction and goal.path and goal.path[0] == OPPOSITE.get(last_direction):
            goal.facts.append("goes back the way you just came")
    goals.sort(key=lambda goal: not goal.objective)
    return goals


_COMPASS = {"up": "north", "down": "south", "left": "west", "right": "east"}


def _goal(
    key: str,
    kind: str,
    label: str,
    path: list[str] | None,
    *,
    extra: list[str],
    fallback: str | None,
    distance: int,
    finish: GameAction | None = None,
    more: list[str] | None = None,
    partial: list[str] | None = None,
) -> Goal:
    """Its path; else the reachable route that gets closest; else one blind step."""
    facts = list(more or [])
    if path is not None:
        walks = [*path, *extra]
        facts.insert(0, f"{len(path)} steps, path open")
    elif partial:
        walks = partial
        facts.insert(
            0, f"{distance} tiles away; walks {len(partial)} steps closer (no full path yet)"
        )
    elif fallback:
        walks = [fallback]
        facts.insert(0, f"{distance} tiles away, no known path (tries one step {fallback})")
    else:
        walks = []
        facts.insert(0, "no way there from here")
    if any(step.startswith("jump_") for step in walks):
        facts.append("Includes one-way ledge drops; the reverse route cannot climb them")
    actions = [_WALK[step] for step in walks[:MAX_BURST]]
    if finish is not None and path is not None and len(walks) <= MAX_BURST:
        actions.append(finish)
    return Goal(
        key=key, kind=kind, label=label, actions=actions, facts=facts, path=walks, finish=finish
    )


def _exit_step(obs: PlayerObservation, tile: Tile, path: list[str] | None) -> str:
    """The walk after reaching a warp. A door mat only warps when walked off the map's edge;
    a door or stairs warp on arrival, and the map change ends the burst before this step."""
    width = (obs.map_size or {}).get("w", 0)
    height = (obs.map_size or {}).get("h", 0)
    if height and tile[1] == height - 1:
        return "down"
    if tile[1] == 0 and height:
        return "up"
    if width and tile[0] == 0:
        return "left"
    if width and tile[0] == width - 1:
        return "right"
    last = (path or [None])[-1]
    return last if last in ("up", "down") else "down"


def _edge_goal(obs: PlayerObservation, side: str, routes: Routes) -> Goal:
    from nuzlocke.knowledge.map_reference import exits, guided_path

    connection = exits(obs, side)
    guided = guided_path(obs, routes, connection["tiles"]) if connection else None
    width = (obs.map_size or {}).get("w", 0)
    height = (obs.map_size or {}).get("h", 0)

    def distance(tile: Tile) -> int:
        return {
            "up": tile[1],
            "down": height - 1 - tile[1],
            "left": tile[0],
            "right": width - 1 - tile[0],
        }[side]

    boundary = [
        t
        for t in routes.paths
        if width and height and distance(t) == 0 and (t[0], t[1], side) not in routes.blocked_edges
    ]
    if guided:
        end = (
            obs.x + sum(step_delta(d)[0] for d in guided),
            obs.y + sum(step_delta(d)[1] for d in guided),
        )
        path, extra = guided, [side] if list(end) in connection["tiles"] else []
    elif boundary:
        end = min(boundary, key=lambda t: len(routes.paths[t]))
        path, extra = routes.paths[end], [side]
    elif width and height:
        # A dead-end pocket can be closer to the boundary than the actual exit.
        # Search new frontier tiles instead of returning to that visited pocket
        # after every perpendicular detour (the old wider-side rule oscillated).
        fresh = [t for t in routes.paths if t != routes.start and t not in routes.seen]
        frontier = [t for t in fresh if routes._borders_unknown(t)]
        pool = frontier or fresh
        end = min(pool, key=lambda t: (distance(t), len(routes.paths[t]))) if pool else None
        path, extra = routes.paths[end] if end is not None else None, []
    else:
        path, extra = routes.furthest(side), [side]
        if path is None:
            path, extra = routes.slide(side, _wider(obs, side)), []
    return _goal(
        f"edge_{side}",
        "edge",
        (
            f"take the {_COMPASS[side]} exit to {map_name(connection['dest_map'])}"
            if connection
            else f"walk off the {_COMPASS[side]} edge into the next area"
        ),
        path,
        extra=extra,
        fallback=routes.step(side),
        distance=_edge_distance(obs, side),
        more=[f"Known exit tiles: {connection['tiles']} (vanilla map reference)"]
        if connection
        else None,
    )


def _wider(obs: PlayerObservation, side: str) -> str:
    """The perpendicular direction with more map left in it."""
    width = (obs.map_size or {}).get("w", 0)
    height = (obs.map_size or {}).get("h", 0)
    if side in ("up", "down"):
        return "right" if obs.x < width / 2 else "left"
    return "down" if obs.y < height / 2 else "up"


def _edge_distance(obs: PlayerObservation, side: str) -> int:
    width = (obs.map_size or {}).get("w", 0)
    height = (obs.map_size or {}).get("h", 0)
    return {
        "up": obs.y,
        "down": max(height - 1 - obs.y, 0),
        "left": obs.x,
        "right": max(width - 1 - obs.x, 0),
    }[side]


def _heading_run(start: Tile, heading: str, walkable: dict[Tile, bool]) -> list[str] | None:
    dx, dy = DIRS[heading]
    run: list[str] = []
    x, y = start
    for _ in range(MAX_BURST):
        x, y = x + dx, y + dy
        if not walkable.get((x, y), False):
            break
        run.append(heading)
    return run or None


def _mark_objective(
    goals: list[Goal],
    obs: PlayerObservation,
    objective: dict[str, Any] | None,
    objective_text: str | None,
    routes: Routes,
) -> None:
    """Flag the option that is the objective, or add one for a plain tile target."""
    from nuzlocke.knowledge.map_reference import guided_path

    if not objective:
        return
    kind = objective.get("kind")
    match: Goal | None = None
    if kind == "warp":
        candidates = [
            g
            for g in goals
            if (
                g.dest_map == objective.get("dest_map")
                or g.raw_dest_map == objective.get("dest_map")
            )
            and ("x" not in objective or (objective["x"], objective["y"]) in g.warp_tiles)
        ]
        if candidates:
            from nuzlocke.knowledge.map_reference import shortest_path

            def exit_rank(goal):
                if goal.complete:
                    return (0, len(goal.path))
                route = shortest_path(
                    obs,
                    goal.warp_tiles,
                    observed=routes.walkable,
                    blocked=routes.blocked_edges,
                    crossed=routes.crossed_edges,
                    terrain=routes.terrain_edges,
                    jumps=routes.jumps,
                )
                return (1, len(route)) if route else (2, len(goal.path) or 10000)

            # Several ladders can share a destination map but lead to disconnected rooms.
            # Choose a reachable ladder, never the first table entry across a cliff.
            match = min(candidates, key=exit_rank)
    elif kind == "edge":
        match = next((g for g in goals if g.key == f"edge_{objective.get('dir')}"), None)
        if match is None and objective.get("dir") in DIRS:
            if obs.connections and objective["dir"] not in obs.connections:
                # A story hint cannot invent an exit contradicted by this map's table.
                # Leave an unexecutable objective so System 1 requests a director look.
                match = Goal(
                    key=f"edge_{objective['dir']}",
                    kind="edge",
                    label=f"No {objective['dir']} connection on this map; revise the objective",
                    actions=[],
                )
            else:
                match = _edge_goal(obs, str(objective["dir"]), routes)
            goals.append(match)
    elif kind == "npc":
        picture, name = objective.get("picture"), str(objective.get("name") or "").casefold()
        match = next(
            (
                g
                for g in goals
                if g.kind == "talk"
                and (
                    g.key == f"talk_{objective['slot']}"
                    if objective.get("slot") is not None
                    else (picture is not None and g.picture == picture)
                    or (name and name in g.name.casefold())
                )
            ),
            None,
        )
    elif kind == "tile" and objective.get("x") is not None:
        tile = (int(objective["x"]), int(objective["y"]))
        start = (obs.x, obs.y)
        path = routes.onto(tile)
        match = _goal(
            "objective",
            "objective",
            f"walk to the objective tile ({objective.get('label') or 'target'})",
            path,
            extra=[],
            fallback=routes.step(_straight(tile[0] - start[0], tile[1] - start[1])),
            distance=_manhattan(start, tile),
            partial=None
            if path is not None
            else (guided_path(obs, routes, [tile]) or routes.closest(tile)),
        )
        goals.append(match)
    elif kind == "face" and objective.get("x") is not None:
        from nuzlocke.agents.gym_preparation import leader_position, needs_top_up

        prepare_first = needs_top_up(obs) and (
            objective["x"],
            objective.get("y"),
        ) == leader_position(obs.map_id, obs.badges)
        # Stand on a tile, turn, and press A: the nurse is answered across her counter.
        tile = (int(objective["x"]), int(objective["y"]))
        path = routes.onto(tile)
        match = _goal(
            "objective",
            "objective",
            f"stand at ({tile[0]},{tile[1]}), face {objective.get('dir')}, press A",
            path,
            extra=[] if prepare_first else [str(objective.get("dir") or "up")],
            fallback=None,
            distance=_manhattan((obs.x, obs.y), tile),
            finish=None if prepare_first else GameAction.PRESS_A,
            partial=None if path is not None else routes.closest(tile),
        )
        goals.append(match)
    elif kind in ("wait", "explore"):
        match = next((g for g in goals if g.key == kind), None) or next(
            g for g in goals if g.key == "wait"
        )
    if match is not None:
        mark(match, objective_text)


def mark(goal: Goal, objective_text: str | None) -> None:
    """This option is the objective: flagged first in its facts."""
    goal.objective = True
    goal.facts.insert(0, f"CURRENT OBJECTIVE: {objective_text or 'this'}")


def pick(
    goals: list[Goal], choice: str, probabilities: dict[str, float], fails: dict[str, int]
) -> Goal | None:
    """Jev's goal, or the runner-up when that goal already failed here twice."""
    by_key = {goal.key: goal for goal in goals}
    chosen = by_key.get(choice)
    if chosen is None:
        return None
    if fails.get(choice, 0) < _FAILS_BEFORE_RUNNER_UP:
        return chosen
    ranked = sorted(probabilities.items(), key=lambda item: item[1], reverse=True)
    for key, _p in ranked:
        if key != choice and key in by_key and fails.get(key, 0) < _FAILS_BEFORE_RUNNER_UP:
            return by_key[key]
    return chosen


def goal_questions(goals: list[Goal], *, judged: bool = True) -> dict[str, Any]:
    questions: dict[str, Any] = {
        "action": {
            "type": "choice",
            "instructions": (
                "Pick the goal to pursue now. The option marked CURRENT OBJECTIVE is what the "
                "story needs next; take it when its path is open. Code walks the path for you. "
                "Pick another option only when the objective's path is blocked, it keeps failing, "
                "or `text` shows something to handle first. Avoid options that already failed."
            ),
            "criteria": {goal.key: goal.criterion() for goal in goals},
        }
    }
    if judged:
        questions["objective_done"] = {
            "type": "noul",
            "instructions": "The current objective is already complete.",
            "criteria": {
                "true": "The objective has been achieved",
                "false": "The objective is still ahead",
            },
        }
    return questions


class ObjectTrust:
    """Whether each map's WRAM objects have matched where the map really changed.

    A map change after a walk from a tile that is not on or next to a listed
    warp is a strike. After ``strikes`` of them the map's warps, signs, and
    NPCs are withheld: they come from the same tables. Two corroborating warp
    transitions restore trust; edge connections, battles, and scripts are excluded.
    """

    def __init__(self, strikes: int = 2) -> None:
        self._strikes = max(1, int(strikes))
        self._counts: dict[Any, int] = {}
        self._confirmed: dict[Any, int] = {}

    def trusted(self, obs: PlayerObservation) -> bool:
        return self._counts.get(map_key(obs), 0) < self._strikes

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
        if not before.warps or map_key(before) == map_key(after):
            return False
        # Connections and scripts change maps without using the warp table.
        if before.cutscene or after.cutscene or before.in_battle or after.in_battle:
            return False
        width, height = (before.map_size or {}).get("w"), (before.map_size or {}).get("h")
        for step in walks or []:
            if step.get("map_id") == before.map_id:
                continue
            side = str(step.get("action", "")).removeprefix("walk_")
            x, y = step.get("x0"), step.get("y0")
            boundary = {
                "up": y == 0,
                "down": height is not None and y == height - 1,
                "left": x == 0,
                "right": width is not None and x == width - 1,
            }
            if side in before.connections and boundary.get(side):
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
            key = map_key(before)
            self._confirmed[key] = self._confirmed.get(key, 0) + 1
            if self._confirmed[key] >= 2:
                self._counts[key] = 0
            return False
        was = self.trusted(before)
        key = map_key(before)
        self._confirmed[key] = 0
        self._counts[key] = self._counts.get(key, 0) + 1
        return was and not self.trusted(before)
