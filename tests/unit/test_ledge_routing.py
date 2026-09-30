from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from nuzlocke.agents.goals import Goal, RoomMap, Routes, build_goals, collision_map
from nuzlocke.agents.navigation import Navigator, path_tiles
from nuzlocke.agents.system3 import heal_beat
from nuzlocke.environment.nous_red import NousRedEnvironment
from nuzlocke.knowledge.beats import current_beat
from nuzlocke.knowledge.encounters import encounter_objective
from nuzlocke.knowledge.map_reference import atlas, ledge_jumps, shortest_path
from nuzlocke.referee.rules import NuzlockeReferee
from nuzlocke.state.models import GameAction as A
from nuzlocke.state.models import PlayerObservation as O


def route4(x=64, y=8):
    data = atlas()["maps"]["15"]
    return O(
        map_id=15,
        map_name="Route 4",
        x=x,
        y=y,
        map_size=data["size"],
        warps=data["warps"],
        raw_player={"name": "RED"},
        badges=["Boulder"],
        flags={"has_pokedex": True},
        party=[{"species": "Nidorino", "hp": 54, "max_hp": 54, "level": 18}],
        bag=[{"item": "Poke Ball", "quantity": 10}],
        terrain_tiles=[
            {"x": 64, "y": 8, "tileset": 0, "id": 0x2C},
            {"x": 64, "y": 9, "tileset": 0, "id": 0x37},
            {"x": 64, "y": 10, "tileset": 0, "id": 0x52},
        ],
    )


@pytest.mark.parametrize(
    "direction,landing,ledge",
    [("down", (1, 3), (1, 2)), ("left", (-1, 1), (0, 1)), ("right", (3, 1), (2, 1))],
)
def test_jump_is_one_directed_action_and_not_a_reverse_walk(direction, landing, ledge):
    floor = {(1, 1): True, ledge: False, landing: True}
    jumps = {(1, 1, direction): landing}
    route = Routes((1, 1), floor, jumps=jumps)
    assert route.paths[landing] == ["jump_" + direction]
    assert path_tiles((1, 1), route.paths[landing]) == [(1, 1), landing]
    assert (1, 1) not in Routes(landing, floor, jumps=jumps).paths
    assert (
        landing not in Routes((1, 1), floor, jumps=jumps, blocked_edges={(1, 1, direction)}).paths
    )
    assert landing not in Routes((1, 1), {**floor, landing: False}, jumps=jumps).paths


def test_reference_and_actor_agree_on_route4_drop_and_live_overrides():
    obs = route4()
    room = RoomMap()
    room.known[15] = {(64, 8): True, (64, 9): False, (64, 10): True}
    jumps = ledge_jumps(obs, room)
    assert jumps[64, 8, "down"] == (64, 10)
    path = shortest_path(obs, [[64, 10]], observed=room.known[15], jumps=jumps)
    assert path == [(64, 8), (64, 10)]
    goal = next(
        g
        for g in build_goals(obs, room, objective={"kind": "tile", "x": 64, "y": 10})
        if g.objective
    )
    assert goal.path == ["jump_down"] and goal.actions == [A.WALK_DOWN]
    obs.terrain_tiles[1]["id"] = 0x10  # Live wall contradicts the reference ledge.
    assert (64, 8, "down") not in ledge_jumps(obs, room)


def test_cached_jump_is_revalidated_before_reuse():
    obs = route4()
    room = RoomMap()
    room.known[15] = {(64, 8): True, (64, 9): False, (64, 10): True, (63, 8): True}
    nav = Navigator()

    def goal(path):
        return Goal(
            key="target",
            kind="objective",
            label="grass",
            path=path,
            actions=[A.WALK_DOWN],
            objective=True,
        )

    nav.select(obs, room, [goal(["jump_down"])], objective_text="grass")
    obs.terrain_tiles[1]["id"] = 0x10
    result = nav.select(obs, room, [goal(["left"])], objective_text="grass")
    assert result.actions == [A.WALK_LEFT]
    assert not nav.reused


def test_encounter_search_routes_to_grass_before_suppressing_recovery():
    obs = route4(53, 6)
    room = RoomMap()
    data = atlas()["maps"]["15"]
    room.known[15] = {
        (x, y): c == "." for y, row in enumerate(data["rows"]) for x, c in enumerate(row)
    }
    loop = SimpleNamespace(
        referee=NuzlockeReferee({"clauses": {"duplicates_clause": True}}),
        _encounter_tables={},
        _encounter_search_counts={},
        _grass_visits={},
        _cycle=1,
        room=room,
        navigator=Navigator(),
    )
    target, text, _ = encounter_objective(loop, obs, current_beat(obs))
    assert target["kind"] == "tile" and target["x"] >= 64
    assert obs.policy["encounter_phase"] == "approach"
    assert "ledge" in text
    obs.x, obs.y = 64, 10
    obs.grass_tiles = [{"x": 64, "y": 10}, {"x": 64, "y": 11}]
    encounter_objective(loop, obs, current_beat(obs))
    assert obs.policy["encounter_phase"] == "pacing"


def test_route4_exit_apron_does_not_flip_back_to_western_mt_moon():
    for x in (24, 25, 26):
        obs = route4(x, 6)
        assert current_beat(obs).target == {"kind": "edge", "dir": "right"}
        obs.party[0]["hp"] = 10
        assert heal_beat(obs).target == {"kind": "edge", "dir": "right"}
    assert current_beat(route4(18, 6)).target == {"kind": "warp", "dest_map": 59}


def test_emulator_jump_releases_input_checks_landing_and_stops_the_burst(tmp_path):
    obs = route4()
    after = obs.model_copy(update={"y": 10})
    env = NousRedEnvironment(base_url="http://unused", run_dir=tmp_path, auto_start=False)
    env.on_transition = lambda *_: None
    env.snapshot = MagicMock(side_effect=[obs, after])
    env.observe = MagicMock(return_value=after)
    env._frame_blocks_walk = MagicMock(return_value=False)
    env._menu_cursor_open = MagicMock(return_value=False)
    env._map_objects = MagicMock(return_value={})
    env._post_json = MagicMock()
    result = env.execute([A.WALK_DOWN, A.WALK_RIGHT])
    assert env._post_json.call_args.args[1]["actions"] == ["walk_down", "wait_60"]
    assert result.executed == [A.WALK_DOWN]
    assert result.stopped_early_because == "ledge_jump"
    room = RoomMap()
    room.record_walks(after, result.walks)
    assert (64, 8, "down") not in room.crossed_edges.get(15, set())
    assert not collision_map(after, room)[64, 9]
