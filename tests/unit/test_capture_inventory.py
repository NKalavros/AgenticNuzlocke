"""Route 9's eleventh-entry bag: capture scroll and final policy share visible cursor evidence."""

import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from nuzlocke.agents.goals import RoomMap
from nuzlocke.agents.inventory import capture_ball_actions, is_capture_ball
from nuzlocke.agents.policy import decision
from nuzlocke.agents.system1 import system1_turn
from nuzlocke.agents.system3 import forced_battle_choice
from nuzlocke.environment.base import ActionResult
from nuzlocke.environment.screen_text import parse_screen
from nuzlocke.orchestration.arbiter import ActionArbiter
from nuzlocke.state.models import ActionProposal, AgentRole
from nuzlocke.state.models import GameAction as A
from nuzlocke.state.models import PlayerObservation

FIXTURE = json.loads((Path(__file__).parents[1] / "fixtures/route9_capture_bag.json").read_text())


def scene():
    obs = PlayerObservation(**FIXTURE)
    obs.policy.update(first_encounter=True, level_cap=29, avoid_wild_grinding=True)
    return obs


def turn(obs, *, first_encounter=True):
    return system1_turn(
        obs=obs,
        screen=parse_screen(obs.screen_rows),
        text_box=False,
        mash_stalled=False,
        room=RoomMap(),
        objective=None,
        objective_text=None,
        objective_from_code=False,
        heading=None,
        fails={},
        last_direction=None,
        low_confidence_streak=0,
        confidence_floor=0.55,
        stale_noul=0.7,
        journal=[],
        constraints=[],
        first_encounter=first_encounter,
        jev_decide=Mock(side_effect=AssertionError("The capture bag needs no model decision")),
    )


def window(obs, start, selected):
    entries = [item["item"].upper().replace("POKE", "POKé") for item in obs.bag] + ["CANCEL"]
    for index, row in enumerate((4, 6, 8, 10), start):
        label = entries[index] if index < len(entries) else ""
        glyph = "▶" if index == selected else " "
        obs.screen_rows[row] = "    │" + (glyph + label).ljust(14) + "│"
        obs.screen_rows[row + 1] = "    │" + (f"×{obs.bag[index]['quantity']}" if index < len(obs.bag) else "").rjust(14) + "│"
    obs.menu_scroll, obs.menu_index = 99, 99  # Scratch RAM must not override the visible row.


def test_real_hidden_balls_are_scrolled_without_model_calls_and_unsafe_fallbacks():
    obs = scene()
    assert all("BALL" not in row.upper() for row in obs.screen_rows)
    assert capture_ball_actions(obs, True) == [A.WALK_DOWN]
    assert turn(obs).actions == [A.WALK_DOWN]
    contract = decision(obs, first_encounter=True)
    assert contract.required == "capture_bag"
    assert contract.validate([A.WALK_DOWN]) is None
    assert contract.validate([A.PRESS_B]) is not None
    assert contract.validate([A.PRESS_A]) is not None  # TM34 must never be used.
    assert contract.validate([A.WALK_DOWN] * 9 + [A.PRESS_A]) is not None


@pytest.mark.parametrize(
    "start,selected,expected", [(7, 8, A.WALK_DOWN), (7, 9, A.PRESS_A), (8, 11, A.WALK_UP), (10, 10, A.WALK_UP)]
)
def test_scrolled_windows_and_cancel_use_full_bag_order(start, selected, expected):
    obs = scene()
    window(obs, start, selected)
    assert capture_ball_actions(obs, True) == [expected]
    assert turn(obs).actions == [expected]
    assert decision(obs, first_encounter=True).validate([expected]) is None
    if expected != A.PRESS_A:
        assert decision(obs, first_encounter=True).validate([A.PRESS_A]) is not None


@pytest.mark.parametrize("reason", ["trainer", "resolved", "duplicate", "low_hp", "dead", "ineligible", "empty", "false_ball"])
def test_bag_returns_to_required_survival_action_or_refuses_an_illegal_capture(reason):
    obs = scene()
    window(obs, 7, 9)
    first = reason != "resolved"
    if reason == "trainer":
        obs.battle["type"] = "trainer"
    elif reason == "duplicate":
        obs.policy["duplicate_encounter"] = True
    elif reason == "low_hp":
        obs.party[0]["hp"] = 1
    elif reason in {"dead", "ineligible"}:
        obs.party[0][reason] = True
    elif reason == "empty":
        obs.bag[9]["quantity"] = 0
    elif reason == "false_ball":
        obs.bag[9]["id"] = 20  # A label containing BALL does not authorize a Potion ID.
    assert forced_battle_choice(obs, first) != "item"
    assert capture_ball_actions(obs, first) == [A.PRESS_B]
    assert turn(obs, first_encounter=first).actions == [A.PRESS_B]
    assert decision(obs, first_encounter=first).validate([A.PRESS_A]) is not None
    assert decision(obs, first_encounter=first).validate([A.PRESS_B]) is None


@pytest.mark.parametrize("labels", [("YES", "NO"), ("USE", "TOSS"), ("FIGHT", "RUN"), ("BUTTERFREE", "NIDORINO")])
def test_other_menus_are_not_inventory_lists(labels):
    obs = scene()
    obs.screen_rows = ["┌─────────────┐", f"│▶{labels[0]:<12}│", f"│ {labels[1]:<12}│", "└─────────────┘"]
    assert capture_ball_actions(obs, True) is None


@pytest.mark.parametrize("name,identity", [("Master Ball", 1), ("Ultra Ball", 2), ("Great Ball", 3), ("Poké Ball", 4)])
def test_capture_ball_identity_and_quantity_are_required(name, identity):
    assert is_capture_ball({"item": name, "id": identity, "quantity": 1})
    assert is_capture_ball({"item": name, "quantity": 1})
    assert not is_capture_ball({"item": name, "id": identity, "quantity": 0})
    assert not is_capture_ball({"item": "Potion", "id": identity, "quantity": 1})
    assert not is_capture_ball({"item": name, "id": 20, "quantity": 1})


@pytest.mark.parametrize("low_hp,expected", [(False, A.WALK_DOWN), (True, A.PRESS_B)])
def test_final_arbiter_replaces_stale_throw_with_fresh_scroll_or_survival_exit(low_hp, expected):
    obs = scene()
    if low_hp:
        window(obs, 7, 9)
        obs.party[0]["hp"] = 1
    env, store = Mock(), Mock()
    store.append.return_value = "evt-capture-test"
    env.snapshot.return_value = obs
    env.execute.side_effect = lambda actions: ActionResult(executed=actions, observation=obs, stopped_early_because=None)
    arbiter = ActionArbiter(env, store, active_owner=AgentRole.BATTLE)
    arbiter.policy = lambda fresh: decision(fresh, first_encounter=True)
    result = arbiter.apply(ActionProposal(task_id="catch", agent=AgentRole.BATTLE, actions=[A.PRESS_A], reason="stale throw"))
    assert result.executed_actions == [expected]
    env.execute.assert_called_once_with([expected])
    assert any(call.args[0] == "policy_rejection" for call in store.append.call_args_list)
