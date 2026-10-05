import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from nuzlocke.agents.goals import RoomMap
from nuzlocke.agents.inventory import cut_bag_actions, tm_party_choices
from nuzlocke.agents.policy import decision
from nuzlocke.agents.system1 import _special_page, system1_turn
from nuzlocke.environment.screen_text import parse_screen
from nuzlocke.llm.jev import JevAnswers
from nuzlocke.orchestration.loop import RunLoop
from nuzlocke.state.models import GameAction as A
from nuzlocke.state.models import PlanCard, PlanScene, PlayerObservation


def observation(name):
    path = Path(__file__).parents[1] / "fixtures" / f"cut_{name}.json"
    return PlayerObservation(**json.loads(path.read_text()))


def actor(obs, decide):
    return system1_turn(
        obs=obs,
        screen=parse_screen(obs.screen_rows),
        text_box=True,
        mash_stalled=False,
        room=RoomMap(),
        objective=None,
        objective_text="Teach Raticate CUT with HM01",
        objective_from_code=False,
        heading=None,
        fails={},
        last_direction=None,
        low_confidence_streak=0,
        confidence_floor=0.55,
        stale_noul=0.7,
        journal=[],
        constraints=[],
        jev_decide=decide,
    )


def test_hm01_scrolls_from_real_top_of_bag_through_shared_policy():
    obs = observation("bag")
    assert not any("HM01" in row for row in obs.screen_rows)
    decide = Mock(side_effect=AssertionError("Scrolling needs no model"))
    assert actor(obs, decide).actions == [A.WALK_DOWN]
    assert decision(obs).validate([A.WALK_DOWN]) is None
    for action in (A.PRESS_A, A.PRESS_B):
        assert decision(obs).validate([action]) == "required:cut_bag"
    # HM01 becomes visible at absolute bag index 7; select only that row.
    obs.screen_rows[4] = "    │ S.S.TICKET    │"
    obs.screen_rows[6] = "    │ TM28         │"
    obs.screen_rows[8] = "    │▶HM01         │"
    obs.screen_rows[10] = "    │ CANCEL       │"
    assert cut_bag_actions(obs) == [A.PRESS_A]


def test_hm_scroll_does_not_override_healing_preparation_or_battle():
    obs = observation("bag")
    obs.party[0]["hp"] = 1
    assert cut_bag_actions(obs) is None
    obs.party[0]["hp"] = obs.party[0]["max_hp"]
    obs.policy["preparing"] = True
    assert cut_bag_actions(obs) is None
    obs.policy.clear()
    obs.in_battle = True
    assert cut_bag_actions(obs) is None
    assert decision(obs).validate([A.PRESS_A]) is not None
    obs.in_battle = False
    obs.party[0]["moves"].append({"id": 15, "name": "Cut", "pp": 30})
    assert cut_bag_actions(obs) is None


def test_real_compatibility_menu_excludes_raticate_and_dead_or_fainted_members():
    obs = observation("party")
    screen = parse_screen(obs.screen_rows)
    assert screen.menu_title == "TM_COMPATIBILITY" and screen.cursor_row == 0
    assert set(tm_party_choices(obs)) == {"choose_2", "choose_4"}
    requests = []

    def choose(state, questions):
        requests.append((state, questions))
        return JevAnswers("choose_2", 1, 0, 0, "probe", {"choose_2": 1})

    actions = actor(obs, choose).actions
    assert actions == [A.WALK_DOWN, A.WALK_DOWN, A.PRESS_A]
    assert set(requests[0][1]["action"]["criteria"]) == {"choose_2", "choose_4", "back"}
    assert requests[0][0]["goal"] == "Teach Raticate CUT with HM01"
    assert decision(obs).validate(actions) is None
    assert decision(obs).validate([A.WALK_DOWN, A.PRESS_A]) is not None
    obs.party[2]["dead"] = True
    assert decision(obs).validate(actions) is not None
    obs.party[4]["hp"] = 0
    assert tm_party_choices(obs) == {}
    assert decision(obs).validate([A.PRESS_B]) is None


@pytest.mark.parametrize("message", ["Booted up an HM!", "It contained CUT!"])
def test_hm_instruction_pages_use_a_and_leave_prompts_to_menu_handler(message):
    rows = observation("party").screen_rows
    rows[:12] = [" " * 20] * 12
    rows[14], rows[16] = f"│{message:<18}│", "│                  │"
    assert _special_page(rows).actions == [A.PRESS_A]
    # A real YES/NO over the description must not be blindly confirmed.
    rows[6:11] = ["          ┌─────┐", "          │▶YES │", "          │     │", "          │ NO  │", "          └─────┘"]
    assert _special_page(rows) is None


def test_menu_plan_keeps_its_intent_without_a_map_target(monkeypatch):
    monkeypatch.setattr("nuzlocke.knowledge.encounters.encounter_objective", lambda *args: None)
    monkeypatch.setattr("nuzlocke.knowledge.items.item_objective", lambda *args: None)
    loop = RunLoop.__new__(RunLoop)
    loop._beat_locked = False
    loop.plan = PlanCard(scene=PlanScene.MENU, see="Bag", plan="Teach CUT; preserve Hyper Fang")
    assert loop._objective(observation("bag")) == (None, loop.plan.plan, False)


def test_move_replacement_receives_the_directors_field_objective():
    from nuzlocke.agents.move_learning import MoveLearner

    obs = observation("party")
    obs.learning_party_slot, obs.learning_move_id = 2, 15
    obs.screen_rows[14], obs.screen_rows[16] = "│BEEDRILL is trying│", "│to learn CUT!     │"
    goal = "Teach CUT to a compatible member; preserve Twineedle."

    def choose(state, questions, **kwargs):
        assert state["objective"] == goal
        assert state["new_move"]["name"] == "CUT"
        return JevAnswers("replace_2", 1, 0, 0, "probe", {"replace_2": 1})

    learner = MoveLearner()
    assert learner.turn(obs, decide=choose, goal=goal)[0] == [A.PRESS_A]
    assert learner.pending["replace_slot"] == 2
