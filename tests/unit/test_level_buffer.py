import json

from nuzlocke.agents.lead_rotation import LeadRotation
from nuzlocke.agents.level_buffer import preparation_limit, reserved, switch_target
from nuzlocke.agents.policy import decision
from nuzlocke.agents.system3 import forced_battle_choice
from nuzlocke.state.models import GameAction as A
from nuzlocke.state.models import PlayerObservation as O


def mon(species, level, identity, **updates):
    return {
        "species": species,
        "nickname": species.upper(),
        "level": level,
        "capture_id": identity,
        "hp": 50,
        "max_hp": 50,
        "status": "OK",
        "moves": [{"id": 33, "name": "Tackle", "pp": 35}],
        **updates,
    }


def battle():
    return O(
        in_battle=True,
        active_party_slot=0,
        battle={"type": "trainer", "enemy": {"species": "Rattata", "level": 15}},
        party=[mon("Ivysaur", 20, "one"), mon("Nidorino", 18, "two")],
        policy={"level_cap": 21, "level_cap_buffer": 1},
    )


def test_reserve_starts_one_level_below_cap_and_rotates_when_suitable():
    obs = battle()
    assert reserved(obs, obs.party[0])
    assert not reserved(obs, obs.party[1])
    assert switch_target(obs) == 1
    assert forced_battle_choice(obs) == "pkmn"
    assert preparation_limit(21) == 19
    assert preparation_limit(14) == 12


def test_buffer_allows_necessary_use_without_relaxing_hard_cap():
    obs = battle()
    obs.party[1]["hp"] = 5
    assert switch_target(obs) is None
    assert forced_battle_choice(obs) is None
    obs.party[0]["ineligible"] = True
    obs.party[0]["level"] = 22
    assert forced_battle_choice(obs) == "pkmn"  # Actual illegality still forces removal.


def test_switch_is_not_forced_into_bad_matchup_or_underlevelled_alternative():
    obs = battle()
    obs.battle["enemy"] = {"species": "Geodude", "level": 17}
    obs.party[1] = mon("Butterfree", 18, "two")
    assert switch_target(obs) is None
    obs.party[1] = mon("Nidorino", 4, "two")
    assert switch_target(obs) is None


def test_illegal_overworld_lead_is_replaced_even_when_legal_team_is_reserved():
    obs = battle().model_copy(update={"in_battle": False, "battle": None})
    obs.party[0].update(level=22, ineligible=True)
    obs.party[1]["level"] = 21
    assert switch_target(obs) == 1


def test_evolution_wait_has_a_finite_pause_instead_of_an_infinite_loop():
    import pytest

    from nuzlocke.orchestration.loop import RunLoop

    loop = RunLoop.__new__(RunLoop)
    loop._evolution_waits = 30
    obs = O(screen_rows=["What? BULBASAUR"])
    with pytest.raises(RuntimeError, match="Evolution screen did not finish"):
        loop._intervention(obs, None)


def test_catching_and_fleeing_take_priority_over_optional_buffer_switch():
    obs = battle()
    obs.battle["type"] = "wild"
    obs.bag = [{"item": "Poke Ball", "quantity": 10}]
    assert forced_battle_choice(obs, first_encounter=True) == "item"
    obs.policy["avoid_wild_grinding"] = True
    assert forced_battle_choice(obs) == "run"


def party_rows(party, cursor, question="Choose a POKéMON."):
    rows = [" " * 20 for _ in range(18)]
    for i, m in enumerate(party):
        rows[i * 2] = f" {m['nickname']}".ljust(20)
        rows[i * 2 + 1] = (("▶" if i == cursor else " ") + " 50/ 50").ljust(20)
    rows[12] = "┌" + "─" * 18 + "┐"
    for i in range(13, 17):
        rows[i] = "│" + " " * 18 + "│"
    rows[14] = "│" + question.ljust(18) + "│"
    rows[17] = "└" + "─" * 18 + "┘"
    return rows


def test_actor_arbiter_and_checkpoint_agree_during_overworld_lead_swap():
    obs = battle().model_copy(update={"in_battle": False, "screen_rows": [], "battle": None})
    rotation = LeadRotation()
    events = []
    record = lambda kind, payload: events.append((kind, dict(payload)))
    actions, _ = rotation.turn(obs, record)
    assert actions == [A.PRESS_START]
    saved = json.loads(json.dumps(rotation.snapshot()))
    rotation = LeadRotation()
    rotation.restore(saved)
    obs.screen_rows = party_rows(obs.party, 0)
    actions, _ = rotation.turn(obs, record)
    assert actions == [A.WALK_DOWN]
    obs.policy["rotation_actions"] = [a.value for a in actions]
    assert decision(obs).validate(actions) is None
    assert decision(obs).validate([A.PRESS_A]) is not None
    obs.screen_rows = party_rows(obs.party, 1, "Move POKéMON where?")
    assert rotation.turn(obs, record)[0] == [A.WALK_UP]
    obs.party.reverse()
    obs.screen_rows = party_rows(obs.party, 0)
    assert rotation.turn(obs, record)[0] == [A.PRESS_B, A.WAIT_60]
    obs.screen_rows = []
    assert rotation.turn(obs, record)[0] == []
    assert rotation.pending is None
    assert [kind for kind, _ in events].count("lead_rotated") == 1


def test_battle_party_policy_requires_the_buffer_replacement():
    obs = battle()
    obs.screen_rows = party_rows(obs.party, 0)
    policy = decision(obs)
    assert policy.required == "party_1"
    assert policy.validate([A.WALK_DOWN, A.PRESS_A]) is None
    assert policy.validate([A.PRESS_B]) is not None


def test_trainer_interrupt_discards_stale_overworld_rotation_target():
    obs = battle().model_copy(update={"in_battle": False, "screen_rows": [], "battle": None})
    rotation = LeadRotation()
    assert rotation.turn(obs)[0] == [A.PRESS_START]
    obs.in_battle = True
    rotation.observe(obs, lambda *_: None)
    assert rotation.pending is None
    obs.in_battle = False
    obs.party[1]["hp"] = 1
    assert rotation.turn(obs)[0] == []
