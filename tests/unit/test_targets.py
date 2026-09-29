"""Targets from the planner cell and WRAM objects, written onto Jev's options."""

from __future__ import annotations

from nuzlocke.agents.jev_policy import (
    FrameSignals,
    action_menu,
    build_jev_questions,
    build_jev_state,
)
from nuzlocke.agents.targets import (
    ObjectTrust,
    build_targets,
    cell_to_tile,
    facing_target,
    tile_to_cell,
)
from nuzlocke.state.models import PlanCard, PlanScene, PlayerObservation

# Rows 1-9, columns A-J; the player at E5 is map tile (10, 10).
GRID = """\
   A B C D E F G H I J
 1 . . . . . . . . . .
 2 . . . . . . . . . .
 3 . . . . . . . . . .
 4 . . . . . . . . . .
 5 . . . . @ . . . . .
 6 . . . . # . . . . .
 7 . . . . . . . . . .
 8 . . . . . . . . . .
 9 . . . . # # . . . ."""


def _obs(**kwargs) -> PlayerObservation:
    base = {"map_name": "Pallet Town", "map_id": 0, "x": 10, "y": 10, "facing": "down"}
    return PlayerObservation(**{**base, "collision_ascii": GRID, **kwargs})


def test_cells_and_tiles_round_trip():
    obs = _obs()
    assert cell_to_tile("G7", obs) == (12, 12)
    assert tile_to_cell(12, 12, obs) == "G7"
    assert tile_to_cell(30, 30, obs) is None
    assert cell_to_tile("K1", obs) is None


def test_a_door_mat_that_reads_wall_is_still_the_path_goal():
    # The door (E9) reads #, like a real mat. The wall at E6 sends the path around.
    obs = _obs(warps=[{"x": 10, "y": 14, "dest_map": 255, "dest_warp": 0}])
    [door] = build_targets(obs)
    assert door.label.startswith("exit")
    assert door.cell == "E9"
    assert door.first_step in {"left", "right"}
    assert door.path_len == 6


def test_a_person_is_faced_not_entered():
    obs = _obs(npcs=[{"slot": 1, "picture": 3, "x": 10, "y": 8, "on_screen": True}])
    [oak] = build_targets(obs)
    assert oak.label == "Prof. Oak"
    assert oak.first_step == "up"
    assert oak.path_len == 2  # one walk to stand below him, one to face him
    facing_up = _obs(facing="up", npcs=obs.npcs)
    assert facing_target(facing_up, build_targets(facing_up)) is None
    beside = _obs(facing="up", y=9, npcs=obs.npcs)
    assert facing_target(beside, build_targets(beside)).label == "Prof. Oak"


def test_planner_target_leads_the_list():
    obs = _obs(npcs=[{"slot": 1, "picture": 3, "x": 10, "y": 9, "on_screen": True}])
    targets = build_targets(obs, plan_target={"x": 14, "y": 10, "label": "I5"})
    assert targets[0].label == "planner target: I5"
    assert targets[0].first_step == "right"


def test_options_carry_the_facts():
    obs = _obs(warps=[{"x": 14, "y": 10, "dest_map": 255, "dest_warp": 0}])
    targets = build_targets(obs)
    menu = action_menu(
        "overworld", obs=obs, targets=targets, press_counts={"walk_down": 2}, heading="right"
    )
    assert "first step toward exit" in menu["walk_right"]
    assert "the story heading" in menu["walk_right"]
    assert "grid shows a wall" in menu["walk_down"]
    assert "already pressed 2x" in menu["walk_down"]
    assert "nothing in front" in menu["press_a"]


def test_state_is_cut_to_the_scene():
    plan = PlanCard(scene=PlanScene.MENU, see="YES/NO", plan="press_a for YES")
    signals = FrameSignals("w", "d", False, False)
    recent = [{"actions": ["walk_up"], "outcome": "ok"} for _ in range(8)]
    state = build_jev_state(
        plan=plan,
        scene="menu",
        obs=_obs(),
        signals=signals,
        recent=recent,
        memory="long notes",
        nuzlocke={"cap": 12},
        failed_approaches=[["walk_up"]],
    )
    assert "memory" not in state and "nuzlocke" not in state and "where" not in state
    assert state["recent"] == ["walk_up -> ok"] * 2
    assert set(build_jev_questions(action_menu("menu"), "menu")) == {"action"}
    assert "plan_stale" in build_jev_questions(action_menu("overworld"), "overworld")


def test_object_trust_withholds_a_map_after_two_bad_warps():
    trust = ObjectTrust()
    before = _obs(warps=[{"x": 3, "y": 3, "dest_map": 1, "dest_warp": 0}])
    after = _obs(map_id=1, map_name="Route 1")
    assert trust.record(before, after) is False
    assert trust.trusted(before)
    assert trust.record(before, after) is True
    assert trust.view(before).warps == []
    # A map change from a door tile is the table being right.
    fresh = ObjectTrust()
    at_door = _obs(x=3, y=4, warps=before.warps)
    assert fresh.record(at_door, after) is False
    assert fresh.record(at_door, after) is False
    assert fresh.trusted(at_door)
