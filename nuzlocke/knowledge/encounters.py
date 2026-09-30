"""Persistent encounter work: a search timeout never consumes or abandons a slot."""

from nuzlocke.agents.goals import Routes, collision_map
from nuzlocke.environment.maps import map_name
from nuzlocke.referee.families import family


def area_key(map_id, fallback=None):
    # All three floors are the same named area, not three catches.
    return str(59 if map_id in {59, 60, 61} else map_id) if map_id is not None else fallback


def resolved(ledger, map_id):
    keys = {"59", "60", "61"} if map_id in {59, 60, 61} else {area_key(map_id)}
    return any(k in ledger for k in keys)


def eligible(loop, map_id):
    if resolved(loop.referee.encounter_ledger, map_id):
        return False
    table = getattr(loop, "_encounter_tables", {}).get(str(map_id), [])
    clauses = loop.referee.rules.get("clauses", {})
    dupes = clauses.get("duplicates_clause") or clauses.get("species_clause")
    return (
        not table or not dupes or any(family(s) not in loop.referee.owned_families for s in table)
    )


def coverage(loop):
    """Expose pending work separately from real caught/forfeited ledger outcomes."""
    ids = {12, 13, 33, 51, 14, 15, 59, 35, 36}
    ids.update(int(k) for k in getattr(loop, "_encounter_tables", {}) if k.isdigit())
    rows = []
    for mid in sorted(ids):
        if mid in {60, 61}:
            continue
        entry = loop.referee.encounter_ledger.get(area_key(mid), {})
        rows.append(
            {
                "area": map_name(mid),
                "map_id": mid,
                "status": entry.get("outcome")
                or ("pending" if eligible(loop, mid) else "duplicates only"),
                "species": entry.get("species"),
                "search_cycles": getattr(loop, "_encounter_search_counts", {}).get(str(mid), 0),
            }
        )
    return rows


def _warp(dest):
    return {"kind": "warp", "dest_map": dest}


def _edge(direction):
    return {"kind": "edge", "dir": direction}


def _backtrack(obs, target):
    """Reach skipped early encounters before taking Pewter's east exit."""
    mid = obs.map_id
    if mid in {40, 41, 42, 54, 56, 58}:
        return _warp(255)
    if mid == 2:
        return _edge("down")
    if mid == 13:
        if (obs.y or 0) < 12:
            return _warp(47)
        return _warp(50) if target == 51 else _edge("down")
    if mid == 47:
        return _warp(51)
    if mid == 51:
        return _warp(50)
    if mid == 50:
        return _warp(51) if target == 51 else _warp(255)
    if mid == 1:
        return _edge("down" if target == 12 else "left" if target == 33 else "up")
    if mid == 33:
        return _edge("right")
    if mid == 12:
        return _edge("up")
    return None


def encounter_objective(loop, obs, beat):
    from nuzlocke.agents.system3 import has_balls
    from nuzlocke.knowledge.map_reference import ledge_jumps, reference, route4_east, shortest_path

    obs.policy["encounter_search"] = False
    obs.policy["encounter_phase"] = None
    if obs.in_battle or not obs.flags.get("has_pokedex") or not has_balls(obs):
        return None
    if beat and beat.id.startswith(("heal", "box_dead", "prepare", "buy_balls")):
        return None
    # Known grass is remembered across screens. Cave floors have land encounters everywhere.
    # Western Route 4 has no reachable grass; resolve it on the eastern side after Mt. Moon.
    deferred = obs.map_id == 15 and not route4_east(obs)
    if (
        not deferred
        and eligible(loop, obs.map_id)
        and (obs.wild_species or obs.map_id in {12, 13, 33, 51, 14, 15, 59, 60, 61, 35, 36})
    ):
        from nuzlocke.environment.screen_text import find_boxes

        if obs.cutscene or find_boxes(obs.screen_rows):
            return None
        loop.navigator.observe(obs, loop.room)
        grid = collision_map(obs, loop.room) or {}
        routes = Routes(
            (obs.x, obs.y),
            grid,
            blocked_edges=loop.room.blocked_edges(obs),
            jumps=ledge_jumps(obs, loop.room),
        )
        grass = loop.navigator.maps.get(str(obs.map_id), {}).get("grass", [])
        tiles = [tuple(t) for t in grass]
        if obs.map_id in {59, 60, 61}:
            tiles = [t for t, walkable in grid.items() if walkable]
        visits = loop._grass_visits
        candidates = [(t, routes.onto(t)) for t in tiles if t != (obs.x, obs.y)]
        candidates = [(t, path) for t, path in candidates if path]
        obs.policy["encounter_search"] = True
        obs.policy["encounter_phase"] = "approach"
        if candidates:
            if (obs.x, obs.y) in tiles:
                obs.policy["encounter_phase"] = "pacing"
            tile, _ = min(
                candidates,
                key=lambda p: (visits.get(f"{obs.map_id}:{p[0][0]}:{p[0][1]}", 0), len(p[1])),
            )
            if getattr(loop, "_last_search_cycle", None) != loop._cycle:
                area = str(obs.map_id)
                loop._encounter_search_counts[area] = loop._encounter_search_counts.get(area, 0) + 1
                key = f"{area}:{obs.x}:{obs.y}"
                visits[key] = visits.get(key, 0) + 1
                loop._last_search_cycle = loop._cycle
            return (
                {"kind": "tile", "x": tile[0], "y": tile[1]},
                f"Resolve {map_name(obs.map_id)}'s first legal encounter; reroll duplicates.",
                True,
            )
        # Approach a known patch even when it lies beyond the current screen or a ledge.
        # Generic exploration has no reason to prefer encounter terrain over visited dead ends.
        targets = tiles or [tuple(t) for t in (reference(obs) or {}).get("grass", [])]
        path = (
            shortest_path(
                obs,
                targets,
                observed=grid,
                blocked=loop.room.blocked_edges(obs),
                crossed=loop.room.crossed_edges.get(obs.map_id, set()),
                terrain=loop.room.terrain_edges(obs),
                jumps=routes.jumps,
            )
            if targets
            else []
        )
        if path:
            x, y = path[-1]
            return (
                {"kind": "tile", "x": x, "y": y},
                f"Reach {map_name(obs.map_id)} encounter grass at ({x},{y}); follow allowed ledge drops, then resolve the catch.",
                True,
            )
        # Keep this work pending while finding grass; do not quietly take the story exit.
        return (
            {"kind": "explore"},
            f"Find reachable encounter terrain in {map_name(obs.map_id)}; this encounter is still pending.",
            True,
        )
    early = {1, 2, 12, 13, 33, 40, 41, 42, 47, 50, 51, 54, 56, 58}
    if obs.map_id in early:
        missing = [m for m in (12, 33, 13, 51) if eligible(loop, m)]
        if missing:
            target = missing[0]
            route = _backtrack(obs, target)
            if route:
                return (
                    route,
                    f"Return for the unresolved {map_name(target)} encounter before continuing east.",
                    True,
                )
    if obs.map_id in {3, 35, 36}:
        if obs.map_id == 3 and any(eligible(loop, m) for m in (35, 36)):
            return _edge("up"), "Resolve the Route 24 and Route 25 encounters before Misty.", True
        if obs.map_id == 35:
            return (
                _edge("right" if eligible(loop, 36) else "down"),
                "Continue the encounter circuit, then return to Cerulean.",
                True,
            )
        if obs.map_id == 36:
            return _edge("left"), "Return to Cerulean after resolving Route 25.", True
    return None
