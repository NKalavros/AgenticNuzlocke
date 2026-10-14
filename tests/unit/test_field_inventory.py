"""Field bag choices share visible cursor evidence with the final policy."""

import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from nuzlocke.agents.goals import RoomMap
from nuzlocke.agents.inventory import field_bag_choices
from nuzlocke.agents.jev_policy import FrameSignals, classify_scene, reconcile_plan
from nuzlocke.agents.policy import decision
from nuzlocke.agents.roles import _obs_payload
from nuzlocke.agents.system1 import system1_turn
from nuzlocke.environment.base import ActionResult
from nuzlocke.environment.screen_text import is_naming_screen, parse_screen
from nuzlocke.llm.jev import JevAnswers
from nuzlocke.orchestration.arbiter import ActionArbiter
from nuzlocke.state.models import ActionProposal, AgentRole, PlanCard, PlanScene, PlayerObservation
from nuzlocke.state.models import GameAction as A

FIXTURE = json.loads((Path(__file__).parents[1] / "fixtures/route12_flute_bag.json").read_text())


def scene():
    return PlayerObservation(**FIXTURE)


def window(obs, start, selected):
    entries = [item["item"].upper().replace("POKE", "POKé") for item in obs.bag] + ["CANCEL"]
    for index, row in enumerate((4, 6, 8, 10), start):
        glyph = "▶" if index == selected else " "
        obs.screen_rows[row] = "    │" + (glyph + entries[index]).ljust(14) + "│"
        obs.screen_rows[row + 1] = "    │" + (f"×{obs.bag[index]['quantity']}" if index < len(obs.bag) else "").rjust(14) + "│"
    obs.menu_scroll, obs.menu_index = 99, 99


def turn(obs, choice):
    calls = []

    def choose(state, questions):
        calls.append((state, questions))
        assert choice in questions["action"]["criteria"]
        return JevAnswers(choice, 0.9, 0.0, 0.0, "test", {choice: 1.0})

    result = system1_turn(
        obs=obs,
        screen=parse_screen(obs.screen_rows),
        text_box=False,
        mash_stalled=False,
        room=RoomMap(),
        objective={"kind": "tile", "map_id": 23, "x": 7, "y": 100},
        objective_text="Resolve Route 12 encounter",
        objective_from_code=True,
        heading=None,
        fails={},
        last_direction=None,
        low_confidence_streak=0,
        confidence_floor=0.55,
        stale_noul=0.7,
        journal=[],
        constraints=["Use only permitted items"],
        jev_decide=choose,
        execution_plan="Scroll to Poké Flute and use it to wake Snorlax.",
    )
    return result, calls


def test_real_flute_bag_offers_scroll_to_actor_and_final_policy():
    obs = scene()
    result, calls = turn(obs, "scroll_down")
    assert result.actions == [A.WALK_DOWN]
    assert "POKEFLUTE" in calls[0][1]["action"]["criteria"]["scroll_down"]
    assert calls[0][0]["goal"] == "Resolve Route 12 encounter"
    assert "wake Snorlax" in calls[0][0]["plan"]
    assert decision(obs).validate(result.actions) is None
    assert decision(obs).validate([A.WALK_DOWN] * 4 + [A.PRESS_A]) is not None
    assert "scroll_up" not in field_bag_choices(obs)


@pytest.mark.parametrize(
    "start,selected,choice,action",
    [(16, 18, "scroll_down", A.WALK_DOWN), (17, 20, "scroll_up", A.WALK_UP), (16, 19, "choose_3", A.PRESS_A)],
)
def test_scroll_windows_cancel_and_flute_selection(start, selected, choice, action):
    obs = scene()
    window(obs, start, selected)
    assert turn(obs, choice)[0].actions == [action]
    assert decision(obs).validate([action]) is None
    if selected == 20:
        assert "scroll_down" not in field_bag_choices(obs)


@pytest.mark.parametrize(
    "item",
    [
        {"id": 20, "item": "Poke Flute", "quantity": 1},
        {"id": 73, "item": "Poke Flute", "quantity": 0},
        {"id": 20, "item": "Potion", "quantity": 1},
        {"id": 40, "item": "Rare Candy", "quantity": 2},
    ],
)
def test_scrolling_does_not_authorize_counterfeit_empty_or_forbidden_items(item):
    obs = scene()
    obs.bag[19] = item
    if item["id"] == 40:
        obs.bag[10] = {"id": 299, "item": "TM99", "quantity": 1}
    window(obs, 16, 19)
    assert "choose_3" not in field_bag_choices(obs)
    assert decision(obs).validate([A.PRESS_A]) is not None
    assert decision(obs).validate([A.WALK_UP]) is None


def submenu(obs):
    window(obs, 16, 19)
    obs.screen_rows = [row.replace("▶", "▷") for row in obs.screen_rows]
    obs.screen_rows[:4] = ["┌──────┐", "│▶USE  │", "│ TOSS │", "└──────┘"]


@pytest.mark.parametrize("allowed", [True, False])
def test_use_requires_verified_underlying_item_and_never_offers_toss(allowed):
    obs = scene()
    if not allowed:
        obs.bag[19] = {"id": 20, "item": "Potion", "quantity": 1}
    submenu(obs)
    choices = field_bag_choices(obs)
    assert ("choose_0" in choices) == allowed
    assert "choose_1" not in choices
    assert (decision(obs).validate([A.PRESS_A]) is None) == allowed
    assert decision(obs).validate([A.WALK_DOWN, A.PRESS_A]) is not None
    if allowed:
        assert turn(obs, "choose_0")[0].actions == [A.PRESS_A]


def test_fresh_arbiter_allows_scroll_but_replaces_forbidden_use():
    obs = scene()
    obs.bag[0] = {"id": 20, "item": "Potion", "quantity": 1}
    window(obs, 0, 0)
    env, store = Mock(), Mock()
    store.append.return_value = "evt-field-test"
    env.snapshot.return_value = obs
    env.execute.side_effect = lambda actions: ActionResult(executed=actions, observation=obs, stopped_early_because=None)
    arbiter = ActionArbiter(env, store, active_owner=AgentRole.OVERWORLD)
    arbiter.policy = decision
    proposal = ActionProposal(task_id="field", agent=AgentRole.OVERWORLD, actions=[A.WALK_DOWN], reason="scroll")
    assert arbiter.apply(proposal).executed_actions == [A.WALK_DOWN]
    assert arbiter.apply(proposal.model_copy(update={"actions": [A.PRESS_A]})).executed_actions == [A.WAIT_60]


def test_instant_text_bag_is_menu_and_keyboard_requires_visible_grid():
    obs = scene()
    signals = FrameSignals("world", "dialog", False, False)
    plan = PlanCard(scene=PlanScene.NAMING, see="Bag list", plan="Scroll the bag")
    assert obs.joy_ignore == 64 and not is_naming_screen(obs.screen_rows)
    assert classify_scene(obs, plan, signals) == "menu"
    assert reconcile_plan(plan, obs).scene == PlanScene.MENU
    assert "hard_signal" not in _obs_payload(obs, vision_only=True)
    obs.joy_ignore = 0
    obs.screen_rows = ["A B C D E F G H I", "J K L M N O P Q R"]
    assert classify_scene(obs, plan, signals) == "naming"
    assert reconcile_plan(plan, obs).scene == PlanScene.NAMING


def test_field_choices_do_not_own_battle_or_unrelated_menus():
    obs = scene()
    obs.in_battle = True
    assert field_bag_choices(obs) is None
    obs.in_battle = False
    obs.screen_rows = ["┌──────┐", "│▶YES  │", "│ NO   │", "└──────┘"]
    assert field_bag_choices(obs) is None


def test_real_overlapping_use_info_toss_box_keeps_verified_flute_identity():
    obs = scene()
    obs.screen_rows = json.loads((Path(__file__).parents[1] / "fixtures/route12_flute_use.json").read_text())
    assert parse_screen(obs.screen_rows).menu_rows == ["USE", "INFO", "TOSS"]
    assert turn(obs, "choose_0")[0].actions == [A.PRESS_A]
    assert decision(obs).validate([A.PRESS_A]) is None
    assert decision(obs).validate([A.WALK_DOWN, A.WALK_DOWN, A.PRESS_A]) is not None
    obs.bag[19]["id"] = 20
    assert decision(obs).validate([A.PRESS_A]) is not None


def test_cursor_progress_in_lower_screen_does_not_count_as_failed_walking():
    from nuzlocke.orchestration.stuck import Fingerprint, StuckTracker

    tracker = StuckTracker()
    tracker.immobile_streak = 12
    tracker.blocked_on_tile.add("walk_down")
    obs = scene()
    tracker.update_position(obs)
    assert tracker.immobile_streak == 0 and not tracker.blocked_on_tile
    before = Fingerprint("Route 12", 10, 61, "down", False, "frame0", "world", "dialog0")
    for n in range(25):
        after = before._replace(frame=f"frame{n + 1}", dialog=f"dialog{n + 1}")
        tracker.update_position(obs)
        tracker.record_result(before, after, executed=True, actions=["walk_down"], cursor_mode=True)
        assert tracker.escalation_tier() == 0
        assert tracker.immobile_streak == 0 and not tracker.blocked_on_tile
        before = after


def test_unchanged_cursor_menu_still_requests_recovery():
    from nuzlocke.orchestration.stuck import StuckTracker

    tracker = StuckTracker()
    obs = scene()
    fp = tracker.fingerprint(obs)
    for _ in range(13):
        tracker.update_position(obs)
        tracker.record_result(fp, fp, executed=True, actions=["walk_down"], cursor_mode=True)
    assert tracker.needs_recovery()
    assert tracker.immobile_streak == 0 and not tracker.blocked_on_tile
    assert not tracker.failed_approaches


def test_cursorless_quantity_picker_is_not_overworld_walking():
    from nuzlocke.environment.screen_text import is_cursor_screen
    from nuzlocke.orchestration.stuck import StuckTracker

    obs = scene()
    obs.screen_rows = json.loads((Path(__file__).parents[1] / "fixtures/mart_screens.json").read_text())["quantity"]
    assert parse_screen(obs.screen_rows).cursor_row is None
    assert is_cursor_screen(obs.screen_rows)
    tracker = StuckTracker()
    tracker.immobile_streak = 12
    tracker.blocked_on_tile.add("walk_up")
    tracker.update_position(obs)
    assert tracker.immobile_streak == 0 and not tracker.blocked_on_tile


@pytest.mark.parametrize("tier", [2, 4])
def test_frozen_menu_requests_screen_aware_system2_recovery(monkeypatch, tier):
    from types import SimpleNamespace
    from nuzlocke.orchestration.loop import RunLoop
    from nuzlocke.agents.roles import make_task
    from nuzlocke.state.models import DirectorDecision, GameMode, RecoveryAdvice

    loop = RunLoop.__new__(RunLoop)
    loop.jev = object()
    loop.llm = object()
    loop.stuck = SimpleNamespace(stuck_score=6, recent_positions=[], loop_streak=0)
    loop.env = SimpleNamespace(vision_frame=lambda obs: obs, push_event=lambda *a: None)
    loop.store = SimpleNamespace(append=lambda *a: None)
    loop.arbiter = SimpleNamespace(set_owner=lambda *a: None)
    loop._adopt_recovery_plan = lambda *a: None
    seen = []

    def advise(provider, **kwargs):
        assert provider is loop.llm
        assert not kwargs["reframe"]
        seen.append(kwargs["obs"])
        return RecoveryAdvice(diagnosis="The bag is frozen", reason="Close the bag", proposed_actions=[A.PRESS_B])

    monkeypatch.setattr("nuzlocke.orchestration.loop.advise_recovery", advise)
    decision = DirectorDecision(mode=GameMode.RECOVERY, owner=AgentRole.RECOVERY, objective="Resolve the current menu")
    result, used, pause = loop._select_proposal(
        tier=tier,
        decision=decision,
        task=make_task(decision),
        obs=scene(),
        steps=1,
        context={"walkthrough_hint": "Read the menu", "memory": None},
    )
    assert len(seen) == 1 and used and not pause
    assert result.actions == [A.PRESS_B]
