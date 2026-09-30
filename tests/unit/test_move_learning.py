import json
from types import SimpleNamespace

import pytest

from nuzlocke.agents.move_learning import MoveLearner, learning_phase, legal_choices
from nuzlocke.agents.policy import decision
from nuzlocke.environment.screen_text import parse_screen
from nuzlocke.state.models import GameAction as A
from nuzlocke.state.models import PlayerObservation as O

OFFER = [
    "   IVYSAUR    18    ",
    "              52/ 52",
    "   PIDGEO┌─────────┐",
    "         │ ATTACK  │",
    "   BEEDRI│      16 │",
    "         │ DEFENSE │",
    "   BUTTER│      20 │",
    "         │ SPE┌────┐",
    "         │    │▶YES│",
    "         │ SPE│    │",
    "         │    │ NO │",
    "         └────└────┘",
    "┌──────────────────┐",
    "│                  │",
    "│move to make room │",
    "│                  │",
    "│for POISONPOWDER? │",
    "└──────────────────┘",
]
FORGET = OFFER[:7] + [
    "    ┌──────────────┐",
    "    │▶TACKLE       │",
    "    │ STRING SHOT  │",
    "    │ HARDEN       │",
    "    │ CONFUSION    │",
    "┌───└──────────────┘",
    "│                  │",
    "│Which move should │",
    "│                  │",
    "│be forgotten?     │",
    "└──────────────────┘",
]


def mon():
    return {
        "species": "Butterfree",
        "nickname": "BUTTERFREE",
        "capture_id": "capture-4",
        "moves": [
            {"id": i, "name": n, "pp": 10}
            for i, n in [(33, "Tackle"), (81, "String Shot"), (106, "Harden"), (93, "Confusion")]
        ],
    }


def obs(rows=OFFER, **kwargs):
    base = {
        "screen_rows": rows,
        "learning_party_slot": 3,
        "learning_move_id": 77,
        "party": [{"species": "Ivysaur"}, {"species": "Pidgeotto"}, {"species": "Beedrill"}, mon()],
    }
    base.update(kwargs)
    return O(**base)


def page(a, b=""):
    return [" " * 20] * 12 + [
        "┌" + "─" * 18 + "┐",
        "│" + " " * 18 + "│",
        f"│{a:<18}│",
        "│" + " " * 18 + "│",
        f"│{b:<18}│",
        "└" + "─" * 18 + "┘",
    ]


def test_actual_overlapping_forget_box_retains_both_speech_and_moves():
    text = parse_screen(FORGET)
    assert text.text_lines == ["Which move should", "be forgotten?"]
    assert text.menu_rows == ["TACKLE", "STRING SHOT", "HARDEN", "CONFUSION"]
    assert learning_phase(obs(FORGET)) == "forget"


@pytest.mark.parametrize("in_battle", [False, True])
def test_correct_learner_full_replacement_and_restart(in_battle):
    learner = MoveLearner()
    events = []
    record = lambda kind, data: events.append((kind, dict(data)))
    state = obs(in_battle=in_battle)
    actions, _ = learner.turn(state, record=record)
    assert actions == [A.PRESS_A] and learner.pending["species"] == "Butterfree"
    assert learner.pending["choice"] == "replace_2"
    saved = json.loads(json.dumps(learner.snapshot()))
    learner = MoveLearner()
    learner.restore(saved)
    state = obs(FORGET, in_battle=in_battle)
    for cursor in range(3):
        rows = [r.replace("▶", " ") for r in FORGET]
        rows[8 + cursor] = rows[8 + cursor][:5] + "▶" + rows[8 + cursor][6:]
        state.screen_rows = rows
        actions, _ = learner.turn(state, record=record)
        assert actions == [A.PRESS_A if cursor == 2 else A.WALK_DOWN]
        state.policy["learning_actions"] = [a.value for a in learner.actions(state)]
        assert decision(state).validate(actions) is None
        assert decision(state).validate([A.PRESS_A, A.WAIT_60]) == "required:learn_move"
    state.party[3]["moves"][2] = {"id": 77, "name": "Poisonpowder", "pp": 35}
    state.screen_rows = page("BUTTERFREE learned", "POISONPOWDER!")
    learner.turn(state, record=record)
    learner.turn(state, record=record)
    assert len([e for e in events if e[0] == "move_learned"]) == 1
    state.screen_rows = []
    assert learner.turn(state, record=record)[0] == []
    assert learner.pending is None


def test_decline_uses_no_at_offer_and_yes_at_stop_learning():
    learner = MoveLearner()
    calls = []

    def choose(**kw):
        calls.append(kw)
        return SimpleNamespace(action="keep", confidence=1, probabilities={"keep": 1}, latency_s=0)

    state = obs()
    assert learner.turn(state, decide=choose)[0] == [A.WALK_DOWN]
    stop = OFFER.copy()
    stop[14] = "│Stop learning     │"
    stop[16] = "│POISONPOWDER?     │"
    state.screen_rows = stop
    assert learner.turn(state, decide=choose)[0] == [A.PRESS_A]
    state.screen_rows = page("BUTTERFREE did not", "learn POISONPOWDER!")
    learner.turn(state, decide=choose)
    assert learner.pending["verified"] and len(calls) == 1


def test_hm_and_only_damage_move_cannot_be_replaced_by_status():
    pokemon = {
        "moves": [
            {"id": 15, "name": "Cut"},
            {"id": 106, "name": "Harden"},
            {"id": 81, "name": "String Shot"},
            {"id": 116, "name": "Focus Energy"},
        ]
    }
    assert "replace_0" not in legal_choices(pokemon, 77)
    pokemon["moves"][0] = {"id": 93, "name": "Confusion"}
    assert "replace_0" not in legal_choices(pokemon, 77)
    assert "replace_0" in legal_choices(pokemon, 94)  # Psychic can replace the attack.


def test_changed_prompt_cannot_apply_saved_choice():
    learner = MoveLearner()
    learner.turn(obs())
    with pytest.raises(RuntimeError, match="no longer matches"):
        learner.turn(obs(learning_move_id=79))


def test_ordinary_npc_learned_text_is_not_a_move_prompt():
    assert learning_phase(obs(page("I learned a lot", "about trainers!"))) is None


def test_failed_jev_call_can_retry_from_checkpoint():
    learner = MoveLearner()

    def fail(**_):
        raise RuntimeError("network")

    with pytest.raises(RuntimeError, match="network"):
        learner.turn(obs(), decide=fail)
    resumed = MoveLearner()
    resumed.restore(json.loads(json.dumps(learner.snapshot())))
    assert resumed.turn(obs())[0] == [A.PRESS_A]
    assert resumed.pending["choice"] == "replace_2"
