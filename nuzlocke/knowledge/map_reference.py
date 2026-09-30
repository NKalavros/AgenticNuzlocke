"""Known vanilla map layouts and exit destinations, separate from live observations."""

import json
from collections import deque
from functools import lru_cache
from pathlib import Path

from nuzlocke.environment.maps import map_name

DIRS = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}


@lru_cache(maxsize=1)
def atlas():
    return json.loads(Path(__file__).with_name("maps_red.json").read_text())


def reference(obs):
    data = atlas()["maps"].get(str(obs.map_id))
    if not data or (obs.map_size and obs.map_size != data["size"]):
        return None
    return data


def exits(obs, direction):
    data = reference(obs)
    if not data or (obs.connections and direction not in obs.connections):
        return None
    return next((c for c in data["connections"] if c["dir"] == direction), None)


def ledge_jumps(obs, room=None):
    """Launch/direction -> landing, with live tile pairs overriding the reference.

    No reverse edge is implied. A jump never turns its intermediate ledge into floor.
    """
    from nuzlocke.environment.terrain import ledge_pair

    data = reference(obs) or {}
    candidates = {(x, y, d): ((0, a), (0, b)) for x, y, d, a, b in data.get("ledges", [])}
    key = obs.map_id if obs.map_id is not None else obs.map_name
    tiles = dict(room.terrain_tiles.get(key, {})) if room else {}
    if not obs.in_battle and not obs.cutscene:
        tiles.update({(t["x"], t["y"]): (t["tileset"], t["id"]) for t in obs.terrain_tiles})
    for (x, y), first in tiles.items():
        for d, (dx, dy) in DIRS.items():
            second = tiles.get((x + dx, y + dy))
            if second and ledge_pair(first, second, d):
                candidates[x, y, d] = first, second
    jumps = {}
    for (x, y, d), (first, second) in candidates.items():
        dx, dy = DIRS[d]
        if ledge_pair(tiles.get((x, y), first), tiles.get((x + dx, y + dy), second), d):
            jumps[x, y, d] = (x + 2 * dx, y + 2 * dy)
    return jumps


def route4_east(obs):
    # The eastern cave exit is x=24, behind the divider at x=22..23.
    # Using x>25 incorrectly routes its own exit apron back to the western entrance.
    exit_x = next((w["x"] for w in obs.warps if w.get("dest_map") == 60), 24)
    return obs.x is not None and obs.x >= exit_x


def desired_exit(obs, objective):
    if not objective:
        return None
    kind = objective.get("kind")
    if kind == "edge":
        connection = exits(obs, objective.get("dir"))
        if connection:
            return {
                **connection,
                "kind": "edge",
                "destination": map_name(connection["dest_map"]),
                "source": "vanilla map connection; checked against live directions",
            }
    if kind == "warp":
        data = reference(obs) or {}
        warps = obs.warps or data.get("warps", [])
        wanted = objective.get("dest_map")
        matches = [
            w
            for w in warps
            if w["dest_map"] == wanted
            and ("x" not in objective or (w["x"], w["y"]) == (objective["x"], objective["y"]))
        ]
        if matches:
            resolved = obs.return_map if wanted == 255 and obs.return_map is not None else wanted
            return {
                "kind": "warp",
                "dest_map": resolved,
                "destination": map_name(resolved),
                "tiles": [[w["x"], w["y"]] for w in matches],
                "source": "live warp table" if obs.warps else "vanilla warp table",
            }
    return None


def shortest_path(obs, targets, *, observed=None, blocked=(), crossed=(), terrain=None, jumps=None):
    """Advisory walking path on known geometry, overridden by current evidence.

    Excludes unrelated warps, tile-pair cliffs and observed blocked directions.
    Includes directed ledge jumps. Does not model trainer sight or story gates.
    """
    data = reference(obs)
    if not data or obs.x is None or obs.y is None:
        return []
    targets = {tuple(t) for t in targets}
    graph = {(x, y): c == "." for y, row in enumerate(data["rows"]) for x, c in enumerate(row)}
    graph.update(observed or {})
    jumps = ledge_jumps(obs) if jumps is None else jumps
    for x, y, direction in jumps:
        dx, dy = DIRS[direction]
        graph[x + dx, y + dy] = False
    for warp in [*data["warps"], *obs.warps]:
        graph[(warp["x"], warp["y"])] = False
    for tile in targets:
        # Door mats can read as wall; allow only the requested terminal warp.
        if any((w["x"], w["y"]) == tile for w in [*data["warps"], *obs.warps]):
            graph[tile] = True
    terrain = {tuple(e) for e in data["blocked_edges"]} if terrain is None else set(terrain)
    edges = (terrain - set(crossed)) | set(blocked)
    start = (obs.x, obs.y)
    parents = {start: None}
    queue = deque([start])
    while queue:
        here = queue.popleft()
        if here in targets:
            path = []
            while here is not None:
                path.append(here)
                here = parents[here]
            return path[::-1]
        for direction, (dx, dy) in DIRS.items():
            tile = jumps.get((*here, direction), (here[0] + dx, here[1] + dy))
            if tile in parents or not graph.get(tile) or (*here, direction) in edges:
                continue
            parents[tile] = here
            queue.append(tile)
    return []


def guided_path(obs, routes, targets):
    """Use a global reference route to choose an endpoint reachable on observed floor."""
    path = shortest_path(
        obs,
        targets,
        observed=routes.walkable,
        blocked=routes.blocked_edges,
        crossed=routes.crossed_edges,
        terrain=routes.terrain_edges,
        jumps=routes.jumps,
    )
    for tile in reversed(path[1:]):
        if tile in routes.paths:
            return routes.paths[tile]
    return None


def briefing(obs, objective, room):
    data = reference(obs)
    if not data:
        return {"available": False, "reason": "No matching vanilla map dimensions"}
    from nuzlocke.agents.goals import collision_map, map_key

    desired = desired_exit(obs, objective)
    path = (
        shortest_path(
            obs,
            (desired or {}).get("tiles", []),
            observed=collision_map(obs, room),
            blocked=room.blocked_edges(obs),
            crossed=room.crossed_edges.get(map_key(obs), set()),
            terrain=room.terrain_edges(obs),
            jumps=ledge_jumps(obs, room),
        )
        if desired
        else []
    )
    corners = [
        path[i]
        for i in range(len(path))
        if i in {0, len(path) - 1}
        or (path[i][0] - path[i - 1][0], path[i][1] - path[i - 1][1])
        != (path[i + 1][0] - path[i][0], path[i + 1][1] - path[i][1])
    ]
    return {
        "available": True,
        "source": atlas()["source"],
        "basis": "vanilla Red reference; live evidence overrides",
        "size": data["size"],
        "rows": data["rows"],
        "connections": [{**c, "destination": map_name(c["dest_map"])} for c in data["connections"]],
        "warps": [{**w, "destination": map_name(w["dest_map"])} for w in data["warps"]],
        "terrain_blocked_edges": [list(e) for e in sorted(room.terrain_edges(obs))],
        "ledge_jumps": [
            {"from": [x, y], "direction": d, "to": list(t)}
            for (x, y, d), t in ledge_jumps(obs, room).items()
        ],
        "grass": data.get("grass", []),
        "objective": objective,
        "desired_exit": desired,
        "suggested_route": {"steps": len(path) - 1, "waypoints": corners} if path else None,
        "limits": "Walking and directed ledge jumps; no trainer-risk or story-state model. Replan on live contradiction.",
    }
