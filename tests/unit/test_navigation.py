"""Navigation contracts: reuse, evidence, waypoint validation, and risk-sensitive paths."""

import json

from nuzlocke.agents.goals import Goal, RoomMap, Routes, _edge_goal
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
    return Goal(key="exit_47", kind="exit", label="North gate", actions=[A.WALK_RIGHT] * 8, path=path, objective=True)


def test_safe_path_avoids_grass_but_shortest_takes_it():
    grid = {(x, y): True for x in range(5) for y in range(2)}
    direct = Routes((0, 0), grid).paths[(4, 0)]
    safe = Routes((0, 0), grid, costs={(x, 0): 5 for x in range(1, 4)}).paths[(4, 0)]
    assert len(direct) == 4
    assert len(safe) == 6 and safe[0] == "down"


def test_explicit_door_tile_uses_the_exit_instead_of_unreachable_floor():
    from nuzlocke.agents.goals import build_goals, collision_map

    obs, room = scene(x=11, y=2)
    obs.warps = [{"x": 11, "y": 1, "dest_map": 89}, {"x": 7, "y": 1, "dest_map": 163}]
    target = {"kind": "tile", "map_id": 51, "x": 11, "y": 1}
    assert collision_map(obs, room)[11, 1] is False  # Incidental paths still exclude doors.
    goals = build_goals(obs, room, objective=target)
    chosen = next(g for g in goals if g.objective)
    assert chosen.kind == "exit" and chosen.dest_map == 89 and chosen.complete
    assert chosen.path[0] == "up" and chosen.actions[0] == A.WALK_UP
    assert not next(g for g in goals if g.dest_map == 163).objective


def test_nurse_npc_goal_uses_counter_interaction_instead_of_adjacent_sprite():
    from nuzlocke.agents.goals import build_goals
    from nuzlocke.knowledge.objects import object_facts

    obs = PlayerObservation(map_id=89, x=0, y=3, facing="down", map_size={"w": 14, "h": 8})
    nurse = {"slot": 1, "picture": 41, "x": 3, "y": 1, "on_screen": True}
    obs.npcs = [nurse]
    room = RoomMap()
    room.known[89] = {(x, y): y >= 3 for x in range(14) for y in range(8)}
    goal = next(g for g in build_goals(obs, room, objective={"kind": "npc", "name": "nurse"}) if g.objective)
    assert goal.path == ["right", "right", "right", "up"]
    assert goal.actions == [A.WALK_RIGHT] * 3 + [A.WALK_UP, A.PRESS_A]
    assert "counter" in object_facts(obs, nurse)["interaction"]


def test_exit_search_does_not_return_to_visited_northern_dead_end():
    obs = PlayerObservation(x=2, y=3, map_size={"w": 7, "h": 5})
    # West pocket is closest to north, but already explored; east reveals new terrain.
    open_tiles = {(1, 1), (1, 2), (1, 3), (2, 3), (3, 3), (4, 3), (4, 2)}
    seen = {(1, 1), (1, 2), (1, 3), (2, 3)}
    grid = {t: True for t in open_tiles}
    grid.update({(0, 1): False, (1, 0): False, (2, 1): False})
    routes = Routes((2, 3), grid, seen=seen, size=(7, 5))
    goal = _edge_goal(obs, "up", routes)
    assert goal.path == ["right", "right", "up"]
    # A partial exploration route must not add an unverified north press.
    assert goal.actions == [A.WALK_RIGHT, A.WALK_RIGHT, A.WALK_UP]


def test_exit_search_uses_known_boundary_and_crosses_it():
    obs = PlayerObservation(x=2, y=2, map_size={"w": 5, "h": 5})
    grid = {(2, y): True for y in range(3)}
    routes = Routes((2, 2), grid, seen=set(grid), size=(5, 5))
    assert _edge_goal(obs, "up", routes).actions == [A.WALK_UP] * 3


def test_failed_direction_does_not_make_destination_tile_a_wall():
    obs, room = scene()
    room.record_walks(obs, [{"map_id": 51, "x0": 1, "y0": 1, "x1": 1, "y1": 1, "action": "walk_right", "blocked": True}])
    assert not room.blocked(obs)
    route = Routes((1, 1), room.known[51], blocked_edges=room.blocked_edges(obs))
    assert route.paths[(2, 1)] != ["right"]
    assert (2, 1) in route.paths
    room.cycle += 7
    assert not room.blocked_edges(obs)


def test_transition_or_turn_is_not_learned_as_a_wall():
    obs, room = scene()
    room.record_walks(obs, [{"map_id": 51, "x0": 1, "y0": 1, "x1": 1, "y1": 1, "action": "walk_up", "blocked": False}])
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


def test_changed_grass_destination_invalidates_same_named_objective_route():
    obs, room = scene()
    nav = Navigator()
    first = goal(["right"] * 4)
    first.target = (5, 1)
    nav.select(obs, room, [first], objective_text="Find encounter")
    changed = goal(["down"])
    changed.target = (1, 2)
    selected = nav.select(obs, room, [changed], objective_text="Find encounter")
    assert selected.actions == [A.WALK_DOWN]
    assert nav.reused == 0


def test_waypoint_must_be_reachable_and_match_objective():
    obs, room = scene()
    nav = Navigator()
    plan = {"map_id": 51, "objective_key": "exit_47", "waypoints": [[999, 999]]}
    selected = nav.select(obs, room, [goal()], objective_text="Go north", plan=plan)
    assert selected is None and not nav.route
    assert nav.reason == "Route waypoint rejected"
    assert nav.context(obs, room)["route"]["rejected_waypoint"] == [999, 999]
    assert nav.rejected_waypoints == 1
    nav2 = Navigator()
    assert nav2.select(obs, room, [goal()], objective_text="Go north", plan={**plan, "map_id": 13}) is None
    assert nav2.plan == {} and nav2.reason == "Route waypoint rejected"
    assert nav2.brief["map_id"] == 51 and nav2.brief["objective_key"] == "exit_47"


def test_rejected_waypoint_can_be_reconsidered_after_new_geometry():
    obs, room = scene()
    room.known[51] = {(1, 1): True}
    nav = Navigator()
    plan = {"map_id": 51, "objective_key": "exit_47", "waypoints": [[2, 1]]}
    assert nav.select(obs, room, [goal()], objective_text="Leave", plan=plan) is None
    room.known[51][2, 1] = True
    assert nav.select(obs, room, [goal()], objective_text="Leave", plan=plan).actions == [A.WALK_RIGHT]


def test_planner_context_omits_route_from_the_previous_map():
    obs, room = scene()
    nav = Navigator()
    nav.select(obs, room, [goal()], objective_text="Leave")
    assert nav.context(obs.model_copy(update={"map_id": 200}), room)["route"] == {}


def test_identical_waypoints_are_read_again_after_objective_changes():
    obs, room = scene()
    nav = Navigator()
    plan = {"map_id": 51, "objective_key": "exit_47", "waypoints": [[2, 1]]}
    nav.select(obs, room, [goal()], objective_text="Heal", plan=plan)
    other = goal()
    other.key = "exit_50"
    nav.select(obs, room, [other], objective_text="Other destination")
    selected = nav.select(obs, room, [goal()], objective_text="Heal", plan=plan)
    assert selected.actions == [A.WALK_RIGHT]
    assert nav.reason == "Following System 2 waypoint"


def test_unknown_probe_never_becomes_a_verified_cached_exit_route():
    from nuzlocke.agents.goals import build_goals

    obs, room = scene()
    room.known[51] = {(1, 1): True}
    obs.warps = [{"x": 3, "y": 1, "dest_map": 47}]
    goals = build_goals(obs, room, objective={"kind": "warp", "dest_map": 47})
    nav = Navigator()
    for _ in range(2):
        selected = nav.select(obs, room, goals, objective_text="Leave")
        assert selected.actions == [A.WALK_RIGHT]
        assert nav.reason != "Continuing verified route"
        nav.route["terminal"] = True  # Old checkpoints need current evidence for this exception too.
    assert not next(g for g in goals if g.objective).complete


def test_waypoint_completion_resumes_final_destination():
    obs, room = scene()
    nav = Navigator()
    plan = {"map_id": 51, "objective_key": "exit_47", "waypoints": [[2, 1]]}
    first = nav.select(obs, room, [goal()], objective_text="Go north", plan=plan)
    assert first.actions == [A.WALK_RIGHT]
    second = nav.select(obs.model_copy(update={"x": 2}), room, [goal(["right"] * 11)], objective_text="Go north", plan=plan)
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
    assert parse_route_plan({"map_id": 51, "objective_key": "exit_47", "preference": "teleport"}) == {}


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
        obs, room, [goal()], objective_text="Go north", plan={"map_id": 51, "objective_key": "exit_47", "waypoints": [[2, 1]]}
    )
    assert nav.rejected_waypoints == 1


def test_continuation_atlas_connects_tunnels_and_rock_tunnel_chambers():
    from nuzlocke.knowledge.map_reference import atlas, shortest_path

    for mid, start, end in [
        (119, (5, 4), (2, 41)),
        (121, (47, 2), (2, 5)),
        (82, (15, 3), (37, 3)),
        (232, (33, 25), (27, 3)),
        (82, (5, 3), (17, 11)),
        (232, (23, 11), (3, 3)),
        (82, (37, 17), (15, 33)),
    ]:
        at = PlayerObservation(map_id=mid, x=start[0], y=start[1])
        path = shortest_path(at, [end])
        assert path and path[-1] == end
    # Header declares two extra rows with no source blocks: never invent floor.
    assert atlas()["maps"]["119"]["rows"][-2:] == ["?" * 8] * 2


def test_enclosed_exit_never_offers_known_floor_as_exit_progress():
    obs = PlayerObservation(x=2, y=2, map_size={"w": 7, "h": 7})
    grid = {(x, y): 1 <= x <= 5 and 1 <= y <= 5 for x in range(7) for y in range(7)}
    for seen in (set(), set(grid)):
        routes = Routes((2, 2), grid, seen=seen, size=(7, 7))
        for side in ("up", "down", "left", "right"):
            goal = _edge_goal(obs, side, routes)
            assert not goal.actions and not goal.path and not goal.complete


def test_exit_unknown_approach_is_partial_and_adjacent_probe_is_one_step():
    obs = PlayerObservation(x=2, y=3, map_size={"w": 7, "h": 7})
    grid = {(x, y): False for x in range(7) for y in range(7)}
    grid.update({(2, 3): True, (3, 3): True})
    del grid[4, 3]
    goal = _edge_goal(obs, "right", Routes((2, 3), grid, size=(7, 7)))
    assert goal.actions == [A.WALK_RIGHT] and not goal.complete
    assert "no full path yet" in goal.facts[0]
    obs.x = 3
    goal = _edge_goal(obs, "right", Routes((3, 3), grid, size=(7, 7)))
    assert goal.actions == [A.WALK_RIGHT] and not goal.complete
    grid[4, 3] = False
    assert not _edge_goal(obs, "right", Routes((3, 3), grid, size=(7, 7))).actions
