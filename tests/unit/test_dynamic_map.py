"""Traversal evidence expires with geometry; exploration history does not."""

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from nuzlocke.agents.goals import RoomMap, Routes, build_goals, collision_map
from nuzlocke.agents.move_learning import MoveLearner
from nuzlocke.agents.navigation import Navigator
from nuzlocke.agents.system1 import system1_turn
from nuzlocke.environment.screen_text import ScreenText
from nuzlocke.llm.jev import JevAnswers
from nuzlocke.orchestration.loop import _COOLDOWN_TRIGGERS, RunLoop
from nuzlocke.state.models import GameAction as A
from nuzlocke.state.models import PlayerObservation


def scene(*, blocked=False, tile=17, map_id=999):
    rows = [["."] * 10 for _ in range(9)]
    rows[4][4] = "@"
    rows[3][4] = "#" if blocked else "."
    return PlayerObservation(
        map_id=map_id,
        map_name="Test room",
        raw_player={"name": "RED"},
        party=[{"species": "Beedrill", "hp": 60, "max_hp": 60, "moves": [{"name": "Cut"}]}],
        x=4,
        y=4,
        map_size={"w": 10, "h": 9},
        collision_ascii="   A B C D E F G H I J\n" + "\n".join(f" {i + 1} " + " ".join(row) for i, row in enumerate(rows)),
        terrain_tiles=[{"x": 4, "y": 3, "tileset": 7, "id": tile}],
    )


def cross_and_return(room, obs):
    room.record_walks(
        obs,
        [
            {"map_id": obs.map_id, "x0": 4, "y0": 4, "x1": 4, "y1": 3, "action": "walk_up"},
            {"map_id": obs.map_id, "x0": 4, "y0": 3, "x1": 4, "y1": 4, "action": "walk_down"},
        ],
    )


def controller():
    loop = RunLoop.__new__(RunLoop)
    loop.referee = SimpleNamespace(restore=lambda *_: None, snapshot=dict)
    loop.ledger = SimpleNamespace(restore=lambda *_: None, snapshot=dict)
    loop.store = SimpleNamespace(integrity_head=lambda: None)
    loop.move_learner = MoveLearner()
    loop.room, loop.navigator = RoomMap(), Navigator()
    loop.grid_trust, loop.object_trust = SimpleNamespace(), SimpleNamespace()
    loop._restore_controller(
        {
            "referee": {},
            "ledger": {},
            "cycle": 0,
            "objectives": {},
            "move_types": {},
            "room": {"known": {}, "blocked": {}, "visited": {}, "cycle": 0},
            "grid_trust": {},
            "object_trust": {},
        }
    )
    return loop


@pytest.mark.parametrize("change", ["terrain", "grid", "both"])
def test_changed_obstacle_invalidates_floor_and_both_crossing_directions(change):
    room = RoomMap()
    before = scene(blocked=change == "terrain")
    room.visit(before)
    cross_and_return(room, before)
    assert collision_map(before, room)[4, 3]
    after = scene(blocked=True, tile=80 if change != "grid" else 17)
    room.visit(after)
    assert not collision_map(after, room)[4, 3]
    assert (4, 3) in room.seen(after)  # Retain exploration history.
    assert not room.crossed_edges[999]
    assert Navigator().context(after, room)["rows"][3][4] == "#"
    room.cycle += 100
    assert not collision_map(after, room)[4, 3]  # No movement-bump expiry can reopen it.


def test_verified_walk_still_corrects_an_unchanged_rom_hack_grid():
    room = RoomMap()
    obs = scene(blocked=True)
    room.visit(obs)
    cross_and_return(room, obs)
    for _ in range(4):
        room.visit(obs)
    assert collision_map(obs, room)[4, 3]
    assert Navigator().context(obs, room)["rows"][3][4] == "."


def test_map_reentry_discards_old_crossings_even_when_tile_ids_match():
    room = RoomMap()
    obs = scene(blocked=True)
    room.visit(obs)
    cross_and_return(room, obs)
    room.known[999][8, 8] = False
    room.visit(scene(map_id=998))
    room.visit(obs)
    assert not collision_map(obs, room)[4, 3]
    assert (4, 3) in room.seen(obs)
    assert room.known[999][8, 8] is True  # Current observed floor also refreshes memory.
    assert not room.crossed_edges.get(999)


def test_unchanged_offscreen_map_knowledge_survives_reentry():
    room = RoomMap()
    obs = scene()
    room.visit(obs)
    room.known[999][20, 20] = False
    room.visit(scene(map_id=998))
    room.visit(obs)
    assert room.known[999][20, 20] is False


def test_cached_route_replans_around_changed_terrain_instead_of_old_footsteps():
    room, nav = RoomMap(), Navigator()
    before = scene()
    room.visit(before)
    cross_and_return(room, before)
    target = {"kind": "tile", "map_id": 999, "x": 4, "y": 1}
    goals = build_goals(before, room, objective=target)
    first = nav.select(before, room, goals, objective_text="Go north")
    assert first.path == ["up"] * 3
    after = scene(blocked=True, tile=80)
    goals = build_goals(after, room, objective=target)
    selected = nav.select(after, room, goals, objective_text="Go north")
    assert selected.path[0] != "up" and len(selected.path) == 5
    assert nav.reason != "Continuing verified route"


def test_old_exploration_cannot_authorize_a_blocked_waypoint():
    room, nav = RoomMap(), Navigator()
    obs = scene(blocked=True)
    room.visited[999] = {(4, 3)}
    goals = build_goals(obs, room, objective={"kind": "tile", "map_id": 999, "x": 4, "y": 1})
    nav.select(
        obs, room, goals, objective_text="Go north", plan={"map_id": 999, "objective_key": "objective", "waypoints": [[4, 3]]}
    )
    assert nav.rejected_waypoints == 1
    assert not collision_map(obs, room)[4, 3]


def test_changed_floor_clears_obsolete_movement_bumps_immediately():
    room = RoomMap()
    before = scene(blocked=True, tile=80)
    room.visit(before)
    room.record_walks(before, [{"x0": 4, "y0": 4, "x1": 4, "y1": 4, "action": "walk_up", "blocked": True}])
    assert (4, 4, "up") in room.blocked_edges(before)
    after = scene()
    assert collision_map(after, room)[4, 3]
    assert (4, 4, "up") not in room.blocked_edges(after)


@pytest.mark.parametrize("screen", ["battle", "cutscene", "menu"])
def test_non_overworld_screen_cannot_invalidate_geometry(screen):
    room = RoomMap()
    before = scene(blocked=True)
    room.visit(before)
    cross_and_return(room, before)
    after = scene(blocked=True, tile=80)
    if screen == "menu":
        after.screen_rows = ["┌──────────┐", "│▶POKéMON │", "└──────────┘"]
    else:
        setattr(after, "in_battle" if screen == "battle" else "cutscene", True)
    room.visit(after)
    assert room.terrain_tiles[999][4, 3] == (7, 17)
    assert (4, 3) in room.walked[999]
    assert room.crossed_edges[999] == {(4, 4, "up"), (4, 3, "down")}


def test_geometry_reads_do_not_age_temporary_bumps():
    room = RoomMap()
    obs = scene()
    room.visit(obs)
    room.record_walks(obs, [{"x0": 4, "y0": 4, "x1": 4, "y1": 4, "action": "walk_left", "blocked": True}])
    for _ in range(20):
        collision_map(obs, room)
        Navigator().context(obs, room)
    assert room.cycle == 1
    assert (4, 4, "left") in room.blocked_edges(obs)


def test_checkpoint_preserves_current_geometry_and_reentry_still_invalidates_it():
    loop = controller()
    obs = scene(blocked=True)
    loop.room.visit(obs)
    cross_and_return(loop.room, obs)
    resumed = controller()
    resumed._restore_controller(json.loads(json.dumps(loop._controller_snapshot())))
    assert collision_map(obs, resumed.room)[4, 3]
    resumed.room.visit(scene(map_id=998))
    assert not collision_map(obs, resumed.room)[4, 3]


def test_legacy_checkpoint_does_not_promote_old_exploration_to_current_floor():
    loop = controller()
    obs = scene(blocked=True, tile=80)
    loop.room.visit(obs)
    cross_and_return(loop.room, obs)
    saved = loop._controller_snapshot()
    saved["room"].pop("walked")
    saved["room"].pop("active_map")
    resumed = controller()
    resumed._restore_controller(json.loads(json.dumps(saved)))
    assert not collision_map(obs, resumed.room)[4, 3]
    assert (4, 3) in resumed.room.seen(obs)
    assert not resumed.room.crossed_edges.get(999)


def barrier_scene(*, unknown=False):
    obs = scene()
    obs.collision_ascii = obs.collision_ascii.replace(" 4 . . . . . . . . . .", " 4 # # # # # # # # # #")
    if unknown:
        obs.map_size["h"] = 12  # There is still unknown geometry south of the screen.
    return obs


def test_partial_path_does_not_inherit_an_interaction_from_the_final_destination():
    obs, room, nav = barrier_scene(unknown=True), RoomMap(), Navigator()
    goal = next(g for g in build_goals(obs, room, objective={"kind": "face", "x": 4, "y": 1, "dir": "up"}) if g.objective)
    assert goal.path and goal.finish is None
    assert A.PRESS_A not in goal.actions
    routed = nav.select(obs, room, [goal], objective_text="Reach the destination")
    assert routed.actions and A.PRESS_A not in routed.actions


def test_known_unvisited_floor_does_not_hide_a_blocked_destination():
    obs, room = barrier_scene(), RoomMap()
    grid = collision_map(obs, room)
    routes = Routes((obs.x, obs.y), grid, seen=room.seen(obs), size=(10, 9))
    assert len(routes.paths) > len(room.seen(obs))
    assert routes.closest((4, 1)) is None


def test_face_target_does_not_use_the_door_exception_to_walk_onto_an_obstacle():
    obs, room = scene(blocked=True), RoomMap()
    goal = next(g for g in build_goals(obs, room, objective={"kind": "face", "x": 4, "y": 3, "dir": "up"}) if g.objective)
    assert not goal.actions and goal.finish is None


def test_route_waypoint_approaches_a_blocker_without_changing_the_objective():
    obs, room, nav = barrier_scene(), RoomMap(), Navigator()
    objective = {"kind": "face", "x": 4, "y": 1, "dir": "up"}
    goals = build_goals(obs, room, objective=objective)
    assert not next(g for g in goals if g.objective).actions
    selected = nav.select(
        obs,
        room,
        goals,
        objective_text="Reach the destination",
        plan={"map_id": 999, "objective_key": "objective", "waypoints": [[5, 4]]},
    )
    assert selected.actions == [A.WALK_RIGHT]
    assert nav.brief["destination"] == "Reach the destination"
    arrived = obs.model_copy(update={"x": 5, "collision_ascii": None, "terrain_tiles": []})
    turn = system1_turn(
        obs=arrived,
        screen=ScreenText(),
        text_box=False,
        mash_stalled=False,
        room=room,
        objective=objective,
        objective_text="Reach the destination",
        objective_from_code=True,
        heading=None,
        fails={},
        last_direction=None,
        low_confidence_streak=0,
        confidence_floor=0.55,
        stale_noul=0.7,
        journal=[],
        constraints=[],
        navigator=nav,
        jev_decide=Mock(side_effect=AssertionError("Waypoint arrival must request the next interaction")),
    )
    assert turn.trigger == "route waypoint reached" and not turn.actions
    assert turn.trigger not in _COOLDOWN_TRIGGERS
    assert nav.brief["destination"] == "Reach the destination"


def test_changed_facing_invalidates_the_old_final_interaction():
    obs, room, nav = scene(), RoomMap(), Navigator()
    objective = {"kind": "face", "x": 4, "y": 4, "dir": "up"}
    goals = build_goals(obs, room, objective=objective)
    assert nav.select(obs, room, goals, objective_text="Interact").actions == [A.WALK_UP, A.PRESS_A]
    goals = build_goals(obs, room, objective={**objective, "dir": "left"})
    assert nav.select(obs, room, goals, objective_text="Interact").actions == [A.WALK_LEFT, A.PRESS_A]
    assert nav.reused == 0


def test_menu_receives_execution_intent_without_replacing_the_destination():
    obs = scene()
    objective = {"kind": "face", "x": 4, "y": 1, "dir": "up"}

    def decide(state, questions):
        assert state["goal"] == "Challenge the leader"
        assert state["plan"] == "Use the available field move, then verify the obstacle clears."
        assert state["constraints"] == ["Living field-move user: Beedrill knows Cut; verify field permission."]
        return JevAnswers("choose_0", 0.99, 0, 0, "test", {"choose_0": 1})

    turn = system1_turn(
        obs=obs,
        screen=ScreenText([], ["POKéMON", "ITEM", "EXIT"], 2, "START"),
        text_box=False,
        mash_stalled=False,
        room=RoomMap(),
        objective=objective,
        objective_text="Challenge the leader",
        objective_from_code=True,
        heading=None,
        fails={},
        last_direction=None,
        low_confidence_streak=0,
        confidence_floor=0.55,
        stale_noul=0.7,
        journal=[],
        constraints=["Living field-move user: Beedrill knows Cut; verify field permission."],
        jev_decide=decide,
        execution_plan="Use the available field move, then verify the obstacle clears.",
    )
    assert turn.actions == [A.WALK_UP, A.WALK_UP, A.PRESS_A]
    assert objective == {"kind": "face", "x": 4, "y": 1, "dir": "up"}


@pytest.mark.parametrize("color", [0, 255])
def test_fade_cannot_erase_current_terrain_or_traversal_proof(tmp_path, color):
    from PIL import Image

    room, before = RoomMap(), scene()
    room.visit(before)
    cross_and_return(room, before)
    path = tmp_path / "fade.png"
    Image.new("RGB", (160, 144), (color, color, color)).save(path)
    after = scene(blocked=True, tile=127)
    after.screenshot_path = str(path)
    room.visit(after)
    assert room.terrain_tiles[999][4, 3] == (7, 17)
    assert (4, 3) in room.walked[999]
    assert room.crossed_edges[999] == {(4, 4, "up"), (4, 3, "down")}


def test_changed_terrain_without_a_trusted_grid_revokes_old_floor_certainty():
    room, before = RoomMap(), scene()
    room.visit(before)
    cross_and_return(room, before)
    after = scene(tile=80)
    after.collision_ascii = None
    assert (4, 3) not in room.floor(after)
    assert (4, 3) in room.seen(after)
    assert not room.crossed_edges[999]
