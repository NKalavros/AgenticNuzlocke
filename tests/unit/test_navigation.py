"""Navigation contracts: reuse, evidence, waypoint validation, and risk-sensitive paths."""

import json

from nuzlocke.agents.goals import Goal, RoomMap, Routes
from nuzlocke.agents.navigation import Navigator, parse_route_plan
from nuzlocke.state.models import GameAction as A
from nuzlocke.state.models import PlayerObservation


def scene(x=1, y=1):
    obs = PlayerObservation(
        map_id=51,
        map_name="Viridian Forest",
        x=x,
        y=y,
        map_size={"w": 20, "h": 4},
        party=[{"species": "Bulbasaur"}],
        raw_player={"name": "RED"},
    )
    room = RoomMap()
    room.known[51] = {(col, row): True for col in range(20) for row in range(4)}
    return obs, room


def goal(path=None):
    path = path or ["right"] * 12
    return Goal(
        key="exit_47",
        kind="exit",
        label="North gate",
        actions=[A.WALK_RIGHT] * 8,
        path=path,
        objective=True,
    )


def test_safe_path_avoids_grass_but_shortest_takes_it():
    grid = {(x, y): True for x in range(5) for y in range(2)}
    direct = Routes((0, 0), grid).paths[(4, 0)]
    safe = Routes((0, 0), grid, costs={(x, 0): 5 for x in range(1, 4)}).paths[(4, 0)]
    assert len(direct) == 4
    assert len(safe) == 6 and safe[0] == "down"


def test_failed_direction_does_not_make_destination_tile_a_wall():
    obs, room = scene()
    room.record_walks(
        obs,
        [
            {
                "map_id": 51,
                "x0": 1,
                "y0": 1,
                "x1": 1,
                "y1": 1,
                "action": "walk_right",
                "blocked": True,
            }
        ],
    )
    assert not room.blocked(obs)
    route = Routes((1, 1), room.known[51], blocked_edges=room.blocked_edges(obs))
    assert route.paths[(2, 1)] != ["right"]
    assert (2, 1) in route.paths
    room.cycle += 7
    assert not room.blocked_edges(obs)


def test_transition_or_turn_is_not_learned_as_a_wall():
    obs, room = scene()
    room.record_walks(
        obs,
        [{"map_id": 51, "x0": 1, "y0": 1, "x1": 1, "y1": 1, "action": "walk_up", "blocked": False}],
    )
    assert not room.blocked_edges(obs)


def test_route_survives_burst_and_checkpoint_with_remaining_distance():
    obs, room = scene()
    nav = Navigator()
    nav.select(obs, room, [goal()], objective_text="Go north")
    resumed = Navigator()
    resumed.restore(json.loads(json.dumps(nav.snapshot())))
    at = obs.model_copy(update={"x": 9})
    selected = resumed.select(at, room, [goal(["right"] * 4)], objective_text="Go north")
    assert selected.actions == [A.WALK_RIGHT] * 4
    assert resumed.brief["remaining_steps"] == 4
    assert resumed.reason == "Continuing verified route"


def test_long_interaction_route_keeps_final_confirm():
    obs, room = scene()
    nav = Navigator()
    g = goal()
    g.kind = "talk"
    g.finish = A.PRESS_A
    nav.select(obs, room, [g], objective_text="Talk")
    selected = nav.select(obs.model_copy(update={"x": 9}), room, [g], objective_text="Talk")
    assert selected.actions == [A.WALK_RIGHT] * 4 + [A.PRESS_A]


def test_new_obstacle_invalidates_cached_route():
    obs, room = scene()
    nav = Navigator()
    nav.select(obs, room, [goal()], objective_text="Go north")
    room.edge_blocks[51] = {(1, 1, "right"): room.cycle}
    selected = nav.select(obs, room, [goal(["up", "right", "down"])], objective_text="Go north")
    assert selected.actions[0] == A.WALK_UP
    assert nav.reused == 0


def test_waypoint_must_be_reachable_and_match_objective():
    obs, room = scene()
    nav = Navigator()
    plan = {"map_id": 51, "objective_key": "exit_47", "waypoints": [[999, 999]]}
    selected = nav.select(obs, room, [goal()], objective_text="Go north", plan=plan)
    assert selected.path == ["right"] * 12
    assert nav.rejected_waypoints == 1
    nav2 = Navigator()
    nav2.select(obs, room, [goal()], objective_text="Go north", plan={**plan, "map_id": 13})
    assert nav2.plan == {}


def test_waypoint_completion_resumes_final_destination():
    obs, room = scene()
    nav = Navigator()
    plan = {"map_id": 51, "objective_key": "exit_47", "waypoints": [[2, 1]]}
    first = nav.select(obs, room, [goal()], objective_text="Go north", plan=plan)
    assert first.actions == [A.WALK_RIGHT]
    second = nav.select(
        obs.model_copy(update={"x": 2}),
        room,
        [goal(["right"] * 11)],
        objective_text="Go north",
        plan=plan,
    )
    assert len(second.path) == 11
    assert not nav.plan["waypoints"]


def test_whole_map_marks_unknown_and_keeps_observed_grass():
    obs, room = scene()
    room.known[51] = {(1, 1): True}
    nav = Navigator()
    obs.grass_tiles = [{"x": 2, "y": 1}]
    nav.observe(obs, room)
    ctx = nav.context(obs, room)
    assert len(ctx["rows"]) == 4 and len(ctx["rows"][0]) == 20
    assert ctx["rows"][1][1] == "@" and ctx["rows"][1][2] == ","
    assert ctx["rows"][0][0] == "?"


def test_bad_route_plan_is_ignored():
    assert parse_route_plan({"map_id": "oops"}) == {}
    assert (
        parse_route_plan({"map_id": 51, "objective_key": "exit_47", "preference": "teleport"}) == {}
    )


def test_system1_reuses_route_without_asking_jev_again():
    from nuzlocke.agents.system1 import system1_turn
    from nuzlocke.environment.screen_text import ScreenText
    from nuzlocke.llm.jev import JevAnswers

    obs, room = scene()
    nav = Navigator()
    calls = []

    def decide(state, questions):
        calls.append(state)
        return JevAnswers("objective", 0.99, 0, 0, "jev", {"objective": 1})

    args = {
        "screen": ScreenText(),
        "text_box": False,
        "mash_stalled": False,
        "room": room,
        "objective": {"kind": "tile", "x": 13, "y": 1},
        "objective_text": "Reach tile",
        "objective_from_code": True,
        "heading": None,
        "fails": {},
        "last_direction": None,
        "low_confidence_streak": 0,
        "confidence_floor": 0.55,
        "stale_noul": 0.7,
        "journal": [],
        "constraints": [],
        "jev_decide": decide,
        "navigator": nav,
    }
    first = system1_turn(obs=obs, **args)
    assert first.actions
    second = system1_turn(obs=obs.model_copy(update={"x": 9}), **args)
    assert len(calls) == 1 and len(second.actions) == 4
    assert calls[0]["navigation"]["remaining_steps"] == 12


def test_type_decoder_corrects_bug_ghost_psychic_ice_without_changing_poison():
    from pokemon_agent.memory.red import TYPE_NAMES

    from nuzlocke.environment.pa_serve import correct_type_decoder

    correct_type_decoder()
    assert [TYPE_NAMES[7], TYPE_NAMES[3]] == ["Bug", "Poison"]
    assert TYPE_NAMES[8] == "Ghost"
    assert TYPE_NAMES[24] == "Psychic"
    assert TYPE_NAMES[25] == "Ice"


def test_unknown_waypoint_cannot_use_optimistic_collision_fallback():
    obs, room = scene()
    room.known[51] = {(1, 1): True}
    nav = Navigator()
    nav.select(
        obs,
        room,
        [goal()],
        objective_text="Go north",
        plan={"map_id": 51, "objective_key": "exit_47", "waypoints": [[2, 1]]},
    )
    assert nav.rejected_waypoints == 1
