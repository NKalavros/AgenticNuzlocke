"""A narrow, explicitly enabled shortcut through Surge's random switch puzzle."""

from nuzlocke.agents.goals import DIRS, OPPOSITE, Routes, collision_map
from nuzlocke.agents.system3 import needs_heal
from nuzlocke.environment.screen_text import find_boxes


def switch_objective(loop, obs, beat):
    obs.policy["surge_switch_assist"] = False
    puzzle = obs.surge_puzzle
    if (
        not getattr(loop, "run_cfg", {}).get("surge_puzzle_assist", False)
        or obs.map_id != 92
        or obs.in_battle
        or obs.cutscene
        or find_boxes(obs.screen_rows)
        or beat is not None
        or needs_heal(obs)
        or "Thunder" in obs.badges
        or not puzzle
        or puzzle.get("phase") not in {"first", "second"}
        or obs.x is None
        or obs.y is None
    ):
        return None
    x, y = puzzle["x"], puzzle["y"]
    routes = Routes((obs.x, obs.y), collision_map(obs, loop.room) or {}, blocked_edges=loop.room.blocked_edges(obs))
    approaches = [
        (len(routes.paths[tile]), tile, OPPOSITE[side])
        for side, (dx, dy) in DIRS.items()
        if (tile := (x + dx, y + dy)) in routes.paths
    ]
    if not approaches:
        return None  # Let the planner resolve unknown geometry; never blind-walk to a can.
    _, (sx, sy), direction = min(approaches)
    obs.policy["surge_switch_assist"] = True
    return (
        {"kind": "face", "x": sx, "y": sy, "dir": direction},
        f"RAM assist: press the {puzzle['phase']} gym switch in can {puzzle['index']} at ({x},{y}).",
        True,
    )
