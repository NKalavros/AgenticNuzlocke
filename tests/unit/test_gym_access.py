"""Observed access prerequisites and planner targets for field obstacles."""

import pytest

from nuzlocke.agents.roles import parse_target
from nuzlocke.knowledge.walkthrough import progression_hint, surge_stage
from nuzlocke.orchestration.loop import RunLoop
from nuzlocke.orchestration.objectives import progression_objectives
from nuzlocke.state.models import PlanCard, PlanScene, PlayerObservation


def test_cut_access_is_separate_from_teaching_puzzle_and_badge():
    obs = PlayerObservation(map_id=5, badges=["Boulder", "Cascade"], bag=[{"id": 196, "quantity": 1}])
    assert surge_stage(obs) == "teach_cut"
    obs.party = [{"hp": 20, "moves": [{"name": "Cut"}]}]
    assert surge_stage(obs) == "gym_access"
    objectives = progression_objectives(obs)
    assert "(14,18)" in objectives["primary"] and "POKéMON" in objectives["primary"]
    assert "Verify" in objectives["secondary"]
    hint = progression_hint(obs)
    assert "buttons-only target" in hint and "Trees can return" in hint
    assert "search trash cans" not in hint.lower()
    obs.map_id = 92
    assert surge_stage(obs) == "gym"
    assert "switch locks" in progression_objectives(obs)["primary"]
    assert "wrong second choice resets both locks" in progression_hint(obs)
    obs.map_id = 5  # A past gym visit does not prove the current outdoor tree is clear.
    assert surge_stage(obs) == "gym_access"
    obs.party[0]["dead"] = True
    assert surge_stage(obs) == "teach_cut"
    obs.badges.append("Thunder")
    assert surge_stage(obs) is None
    assert "Erika" in progression_objectives(obs)["tertiary"]


@pytest.mark.parametrize("field,value", [("map_id", None), ("x", -1), ("y", 256), ("x", True), ("y", "18")])
def test_absolute_objectives_reject_malformed_coordinates(field, value):
    target = {"kind": "tile", "map_id": 5, "x": 14, "y": 18}
    target[field] = value
    assert parse_target(target) is None


def test_current_map_tile_is_executable_and_cannot_follow_player_to_another_map(monkeypatch):
    from nuzlocke.knowledge import encounters, items

    monkeypatch.setattr(encounters, "encounter_objective", lambda *args: None)
    monkeypatch.setattr(items, "item_objective", lambda *args: None)
    target = parse_target({"kind": "tile", "map_id": 5, "x": 14, "y": 18})
    assert target == {"kind": "tile", "map_id": 5, "x": 14, "y": 18}
    loop = RunLoop.__new__(RunLoop)
    loop._beat_locked = False
    loop.plan = PlanCard(scene=PlanScene.OVERWORLD, see="tree", plan="Approach the gym tree", goal_target=target)
    obs = PlayerObservation(map_id=5)
    assert loop._objective(obs) == (target, "Approach the gym tree", False)
    obs.map_id = 17
    assert loop._objective(obs) == (None, None, False)
    assert parse_target("G7") == {"kind": "cell", "cell": "G7"}
    assert parse_target({"kind": "cell", "value": "G7"}) == parse_target("G7")
    assert parse_target({"kind": "exit", "value": "Vermilion Gym"}) == {"kind": "warp", "dest_map": 92}
    assert parse_target({"kind": "exit", "value": "Vermilion Pokecenter"}) == {"kind": "warp", "dest_map": 89}


@pytest.mark.parametrize(
    "target,trigger",
    [({"kind": "tile", "map_id": 5, "x": 14, "y": 18}, "objective tile reached"), (None, "interaction needs next step")],
)
def test_arrival_requests_the_next_subgoal_instead_of_cooldown_exploration(target, trigger):
    from unittest.mock import Mock

    from nuzlocke.agents.goals import RoomMap
    from nuzlocke.agents.system1 import system1_turn
    from nuzlocke.environment.screen_text import parse_screen
    from nuzlocke.orchestration.loop import _COOLDOWN_TRIGGERS

    obs = PlayerObservation(map_id=5, map_name="Vermilion City", x=14, y=18, party=[{"hp": 20}], raw_player={"name": "RED"})
    turn = system1_turn(
        obs=obs,
        screen=parse_screen([]),
        text_box=False,
        mash_stalled=False,
        room=RoomMap(),
        objective=target,
        objective_text="Approach the tree",
        objective_from_code=False,
        heading=None,
        fails={},
        last_direction=None,
        low_confidence_streak=0,
        confidence_floor=0.55,
        stale_noul=0.7,
        journal=[],
        constraints=[],
        jev_decide=Mock(side_effect=AssertionError("Arrival is observed")),
    )
    assert not turn.actions and turn.trigger == trigger
    assert turn.trigger not in _COOLDOWN_TRIGGERS


def test_field_party_list_is_a_menu_and_nested_cut_menu_keeps_ownership():
    from nuzlocke.environment.screen_text import parse_screen

    rows = [
        "   NIDORINO   22",
        "              61/ 61",
        "   RATICATE   22",
        "              60/ 60",
        "   BEEDRILL   21",
        "▶             65/ 65",
        "   BUTTERFREE 21",
        "              57/ 57",
        "   IVYSAUR    23",
        "              63/ 63",
        "   PIDGEOTTO  23",
        "              67/ 67",
        "┌──────────────────┐",
        "│                  │",
        "│Choose a POKéMON. │",
        "│                  │",
        "│                  │",
        "└──────────────────┘",
    ]
    parsed = parse_screen(rows)
    assert parsed.menu_title == "PARTY" and parsed.cursor_row == 2
    assert "BEEDRILL" in parsed.menu_rows[2] and len(parsed.menu_rows) == 6
    rows[5] = rows[5].replace("▶", "▷")
    rows[8:] = [
        "   IVYSAUR ┌───────┐",
        "           │       │",
        "   PIDGEOTT│▶CUT   │",
        "           │       │",
        "┌──────────│ STATS │",
        "│          │       │",
        "│Choose a P│ SWITCH│",
        "│          │       │",
        "│          │ CANCEL│",
        "└──────────└───────┘",
    ]
    assert parse_screen(rows).menu_rows == ["CUT", "STATS", "SWITCH", "CANCEL"]
    rows[8:] = ["" for _ in range(10)]
    assert not parse_screen(rows).menu_rows  # Unframed numbers alone are not a party menu.
