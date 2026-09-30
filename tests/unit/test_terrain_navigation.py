import json
from types import SimpleNamespace

from nuzlocke.agents.goals import Goal, RoomMap, Routes, build_goals, collision_map
from nuzlocke.agents.navigation import Navigator
from nuzlocke.environment.terrain import pair_blocked, terrain_tiles
from nuzlocke.knowledge.map_reference import atlas, shortest_path
from nuzlocke.state.models import GameAction as A
from nuzlocke.state.models import PlayerObservation


def moon():
    data = atlas()["maps"]["61"]
    obs = PlayerObservation(map_id=61, x=24, y=12, map_size=data["size"], warps=data["warps"])
    room = RoomMap()
    room.known[61] = {
        (x, y): c == "." for y, row in enumerate(data["rows"]) for x, c in enumerate(row)
    }
    return obs, room


def test_cliff_blocks_crossing_both_ways_without_blocking_either_floor_tile():
    assert pair_blocked((17, 0x05), (17, 0x2A))
    assert pair_blocked((17, 0x2A), (17, 0x05))
    assert not pair_blocked((17, 0x05), (17, 0x05))
    obs, room = moon()
    assert room.known[61][24, 11] and room.known[61][24, 12]
    assert (24, 12, "up") in room.blocked_edges(obs)
    assert (24, 11, "down") in room.blocked_edges(obs)
    room.cycle += 1000
    assert (24, 12, "up") in room.blocked_edges(obs)  # Terrain never expires like an NPC bump.


def test_healing_picks_reachable_ladder_in_same_connected_chamber():
    obs, room = moon()
    goals = build_goals(obs, room, objective={"kind": "warp", "dest_map": 60})
    target = next(g for g in goals if g.objective)
    assert target.warp_tiles == [(21, 17)]
    assert target.complete
    assert target.actions[:3] == [A.WALK_LEFT] * 3
    assert not next(g for g in goals if g.warp_tiles == [(25, 9)]).complete


def test_missing_grid_does_not_erase_known_walls():
    obs, room = moon()
    assert not room.known[61][23, 11]
    assert not collision_map(obs, room)[23, 11]


def test_live_tile_pairs_capture_red_star_boundary_missing_from_vanilla():
    obs = PlayerObservation(map_id=60, x=21, y=16, map_size={"w": 28, "h": 28})
    room = RoomMap()
    assert (21, 16, "right") not in room.terrain_edges(obs)
    raw = [[5] * 10 for _ in range(9)]
    raw[4][5] = 0x2A
    obs.terrain_tiles = terrain_tiles({"tileset": 17, "tile_ids": raw}, 21, 16)
    room.visit(obs)
    assert (21, 16, "right") in room.terrain_edges(obs)
    assert (22, 16, "left") in room.terrain_edges(obs)
    # Same tile IDs on a battle/menu screen must not overwrite terrain memory.
    obs.terrain_tiles = terrain_tiles(
        {"tileset": 17, "tile_ids": [[5] * 10 for _ in range(9)]}, 21, 16
    )
    obs.in_battle = True
    room.visit(obs)
    assert (21, 16, "right") in room.terrain_edges(obs)
    obs.in_battle = False
    room.visit(obs)
    assert (21, 16, "right") not in room.terrain_edges(obs)


def test_observed_crossing_overrides_reference_only_in_that_direction():
    obs, room = moon()
    room.record_walks(
        obs,
        [
            {
                "map_id": 61,
                "x0": 24,
                "y0": 12,
                "x1": 24,
                "y1": 11,
                "action": "walk_up",
                "blocked": False,
            }
        ],
    )
    assert (24, 12, "up") not in room.terrain_edges(obs)
    assert (24, 11, "down") in room.terrain_edges(obs)
    route = shortest_path(
        obs,
        [[24, 11]],
        observed=room.known[61],
        blocked=room.blocked_edges(obs),
        terrain=room.terrain_edges(obs),
    )
    assert route == [(24, 12), (24, 11)]


def test_cached_route_cannot_cross_a_terrain_boundary():
    obs, room = moon()
    nav = Navigator()
    stale = Goal("target", "objective", "Heal", [A.WALK_UP] * 2, path=["up"] * 2, objective=True)
    nav.select(obs, room, [stale], objective_text="Heal")
    legal = Goal("target", "objective", "Heal", [A.WALK_DOWN], path=["down"], objective=True)
    selected = nav.select(obs, room, [legal], objective_text="Heal")
    assert selected.actions == [A.WALK_DOWN]
    assert nav.reason != "Continuing verified route"


def test_jump_does_not_prove_intermediate_floor_is_walkable():
    obs, room = moon()
    room.record_walks(
        obs,
        [
            {
                "map_id": 61,
                "x0": 24,
                "y0": 12,
                "x1": 24,
                "y1": 10,
                "action": "walk_up",
                "blocked": False,
            }
        ],
    )
    assert (24, 12, "up") in room.terrain_edges(obs)
    assert (24, 11) not in room.seen(obs)


def test_onto_warp_cannot_bypass_a_terrain_restriction():
    routes = Routes((0, 1), {(0, 1): True}, blocked_edges={(0, 1, "up")})
    assert routes.onto((0, 0)) is None


def test_terrain_and_successful_crossings_survive_paired_controller_restore():
    from nuzlocke.agents.move_learning import MoveLearner
    from nuzlocke.orchestration.loop import RunLoop

    def controller():
        loop = RunLoop.__new__(RunLoop)
        loop.referee = SimpleNamespace(restore=lambda *_: None, snapshot=dict)
        loop.ledger = SimpleNamespace(restore=lambda *_: None, snapshot=dict)
        loop.store = SimpleNamespace(integrity_head=lambda: None)
        loop.move_learner = MoveLearner()
        loop.room = RoomMap()
        loop.navigator = Navigator()
        loop.grid_trust = SimpleNamespace()
        loop.object_trust = SimpleNamespace()
        return loop

    loop = controller()
    loop._restore_controller(
        {
            "referee": {},
            "ledger": {},
            "cycle": 10,
            "objectives": {},
            "move_types": {},
            "room": {"known": {}, "blocked": {}, "visited": {}, "cycle": 10},
            "grid_trust": {},
            "object_trust": {},
        }
    )
    loop.room.terrain_tiles[60] = {(21, 16): (17, 5), (22, 16): (17, 0x2A)}
    loop.room.crossed_edges[60] = {(22, 16, "left")}
    saved = json.loads(json.dumps(loop._controller_snapshot()))
    resumed = controller()
    resumed._restore_controller(saved)
    obs = PlayerObservation(map_id=60, x=21, y=16, map_size={"w": 28, "h": 28})
    assert (21, 16, "right") in resumed.room.terrain_edges(obs)
    assert (22, 16, "left") not in resumed.room.terrain_edges(obs)
