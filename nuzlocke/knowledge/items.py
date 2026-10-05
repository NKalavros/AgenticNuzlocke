"""Opportunistic field pickups, ahead of story/search but behind party safety."""

from nuzlocke.agents.goals import Routes, collision_map
from nuzlocke.agents.system3 import needs_heal
from nuzlocke.environment.screen_text import find_boxes
from nuzlocke.knowledge.map_reference import ledge_jumps
from nuzlocke.knowledge.objects import field_item, interaction_sides, object_available


def bag_has_room(obs, npc):
    rows = [row for row in obs.bag if row.get("quantity", 0) > 0]
    matching = next(
        (row for row in rows if row.get("id") == npc["item_id"] or row.get("item", "").casefold() == npc["item_name"].casefold()),
        None,
    )
    return matching.get("quantity", 0) < 99 if matching else len(rows) < 20


def item_objective(loop, obs, beat):
    """Pick the nearest fully reachable, available item on the current map.

    Live hidden flags retire collected objects. Unknown/unreachable items wait for
    more map observations; a full bag waits for space rather than retrying A.
    """
    obs.policy["item_pickup"] = None
    if obs.in_battle or obs.cutscene or obs.x is None or obs.y is None or not obs.party or needs_heal(obs):
        return None
    if beat and beat.id.startswith(("heal", "box_dead", "prepare", "buy_balls")):
        return None
    if find_boxes(obs.screen_rows):
        return None
    items = [npc for npc in obs.npcs if field_item(npc) and object_available(obs, npc)]
    if not items:
        return None
    routes = Routes(
        (obs.x, obs.y),
        collision_map(obs, loop.room) or {},
        blocked_edges=loop.room.blocked_edges(obs),
        jumps=ledge_jumps(obs, loop.room),
    )
    choices = []
    for npc in items:
        if not bag_has_room(obs, npc):
            continue
        if getattr(loop, "_goal_fails", {}).get(f"talk_{npc['slot']}", 0) >= 3:
            continue  # Repeated failed interactions must not monopolize the run.
        path = routes.facing((npc["x"], npc["y"]), interaction_sides(npc))
        if path:
            choices.append((len(path), npc["slot"], npc))
    if not choices:
        return None
    _, _, npc = min(choices)
    obs.policy["item_pickup"] = npc["slot"]
    obs.policy["encounter_search"] = False
    obs.policy["encounter_phase"] = None
    return ({"kind": "npc", "slot": npc["slot"]}, f"Pick up {npc['item_name']} at ({npc['x']},{npc['y']}).", True)
