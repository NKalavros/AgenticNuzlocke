"""System 3: run when about to faint, heal below half, and a wipe ends the run."""

from __future__ import annotations

import pytest

from nuzlocke.agents import system3
from nuzlocke.knowledge.beats import current_beat
from nuzlocke.orchestration.ledger import LedgerTracker
from nuzlocke.referee.rules import NuzlockeReferee
from nuzlocke.state.models import PlayerObservation


def _obs(hp: int, **kwargs) -> PlayerObservation:
    base = {
        "map_name": "Route 2",
        "map_id": 13,
        "x": 8,
        "y": 48,
        "raw_player": {"name": "RED", "rival_name": "BLUE"},
        "party": [{"species": "Charmander", "hp": hp, "max_hp": 29, "status": "OK"}],
        "flags": {"has_pokedex": True},
    }
    return PlayerObservation(**{**base, **kwargs})


def test_runs_from_a_wild_battle_about_to_faint():
    wild = {"type": "wild", "enemy": {"species": "Pidgey"}}
    assert system3.forced_battle_choice(_obs(1, in_battle=True, battle=wild)) == "run"
    assert system3.forced_battle_choice(_obs(20, in_battle=True, battle=wild)) is None
    trainer = {"type": "trainer", "enemy": {"species": "Geodude"}}
    assert system3.forced_battle_choice(_obs(1, in_battle=True, battle=trainer)) is None


def test_healing_outranks_the_story():
    assert current_beat(_obs(20)).id == "to_forest"
    heal = system3.current_beat(_obs(10))
    assert heal.id == "heal_route2" and heal.target == {"kind": "edge", "dir": "down"}
    center = system3.current_beat(_obs(10, map_name="Viridian Pokecenter", map_id=41))
    assert center.target["kind"] == "face"
    assert system3.current_beat(_obs(29)).id == "to_forest"


@pytest.mark.parametrize(
    "map_id,target",
    [
        (16, {"kind": "warp", "dest_map": 71}),
        (71, {"kind": "warp", "dest_map": 119}),
        (119, {"kind": "warp", "dest_map": 74}),
        (74, {"kind": "warp", "dest_map": 255}),
        (17, {"kind": "edge", "dir": "down"}),
        (5, {"kind": "warp", "dest_map": 89}),
    ],
)
def test_healing_route_through_underground_path(map_id, target):
    obs = _obs(10, map_id=map_id, badges=["Boulder", "Cascade"])
    assert system3.current_beat(obs).target == target
    assert system3.objective_window(obs)["primary"].startswith("Heal")


@pytest.mark.parametrize("map_id", [81, 89, 133, 141])
def test_later_centers_offer_nurse_without_enabling_candy_preparation(map_id):
    obs = _obs(10, map_id=map_id)
    assert system3.heal_beat(obs).id == "heal_nurse"
    obs.party[0]["hp"] = 28
    assert system3.heal_beat(obs) is None


@pytest.mark.parametrize("map_id", [None, 94, 232])
def test_unknown_healing_route_keeps_priority_until_party_recovers(map_id):
    obs = _obs(10, map_id=map_id, badges=["Boulder", "Cascade"])
    assert system3.current_beat(obs).id == "heal_route_unknown"
    assert system3.objective_window(obs)["primary"].startswith("Heal")
    obs.in_battle = True
    assert system3.heal_beat(obs) is None
    obs.in_battle = False
    obs.party[0]["hp"] = 29
    assert system3.heal_beat(obs) is None


def test_a_blackout_is_a_wipe_even_when_the_fainted_party_is_never_seen():
    referee = NuzlockeReferee({})
    ledger = LedgerTracker(referee)
    battle = {"type": "wild", "enemy": {"species": "Pidgey", "hp": 10, "max_hp": 14}}
    ledger.update(_obs(1, in_battle=True, battle=battle), step=1)
    # Next observation: home in Pallet, healed. That is Gen 1's blackout.
    ledger.update(_obs(29, map_name="Pallet Town", map_id=0, x=5, y=6), step=2)
    assert referee.wiped and "blacked out" in referee.wiped
    assert [entry["species"] for entry in referee.death_ledger] == ["Charmander"]


def test_hp_zero_is_a_faint_even_when_status_says_ok():
    referee = NuzlockeReferee({})
    ledger = LedgerTracker(referee)
    two = [
        {"species": "Charmander", "hp": 0, "max_hp": 29, "status": "OK"},
        {"species": "Pidgey", "hp": 12, "max_hp": 20, "status": "OK"},
    ]
    ledger.update(_obs(0, party=two), step=1)
    assert [entry["species"] for entry in referee.death_ledger] == ["Charmander"]
    assert referee.wiped is None


def guardian(**changes):
    obs = _obs(
        29,
        map_id=147,
        x=10,
        y=16,
        in_battle=True,
        battle={"type": "wild", "enemy": {"species": "Marowak", "level": 30}},
        bag=[{"id": 72, "item": "Silph Scope", "quantity": 1}],
        policy={"avoid_wild_grinding": True, "duplicate_encounter": True},
    )
    return obs.model_copy(update=changes)


def test_required_guardian_is_not_forced_to_escape_or_catch():
    assert system3.forced_battle_choice(guardian()) is None
    assert system3.forced_battle_choice(guardian(), first_encounter=True) is None
    obs = guardian()
    obs.party[0]["hp"] = 1
    assert system3.forced_battle_choice(obs) == "run"  # Survival still applies.


@pytest.mark.parametrize(
    "changes",
    [
        {"map_id": 146},
        {"x": 1},
        {"bag": []},
        {"bag": [{"id": 72, "item": "Silph Scope", "quantity": 0}]},
        {"battle": {"type": "wild", "enemy": {"species": "Gastly", "level": 30}}},
        {"battle": {"type": "wild", "enemy": {"species": "Marowak", "level": 29}}},
    ],
)
def test_required_guardian_match_does_not_relax_ordinary_wild_rules(changes):
    assert system3.forced_battle_choice(guardian(**changes)) == "run"


def test_guardian_does_not_spend_an_area_encounter_or_reset_its_outcome():
    referee = NuzlockeReferee({"level_caps": {"brock": 43}})
    ledger = LedgerTracker(referee)
    obs = guardian()
    obs.bag.append({"id": 4, "item": "Poké Ball", "quantity": 10})
    ledger.update(obs, step=0)
    assert not ledger.first_encounter and not ledger.duplicate_encounter
    assert not referee.encounter_ledger
    obs.in_battle = False
    ledger.update(obs, step=1)
    assert not referee.encounter_ledger


def test_constraints_supply_full_offscreen_inventory_evidence():
    obs = guardian(in_battle=False)
    obs.bag.insert(0, {"id": 234, "item": "TM34", "quantity": 1})
    briefing = "\n".join(system3.constraints(obs, 43, []))
    assert "Silph Scope" in briefing and "complete bag" in briefing and "do not open PACK" in briefing


def test_guardian_requests_a_plan_and_final_policy_allows_fighting():
    from nuzlocke.agents.policy import decision
    from nuzlocke.agents.system1 import _battle_turn
    from nuzlocke.state.models import GameAction

    obs = guardian()
    obs.screen_rows = ["┌───────┌──────────┐", "│       │▶FIGHT PM │", "│       │ ITEM  RUN│", "└───────└──────────┘"]

    def no_actor(*args):
        raise AssertionError("Required battle must ask System 2 for a plan first")

    turn = _battle_turn(obs, False, False, {}, [], [], 0.55, no_actor)
    assert turn.trigger == "mandatory story battle"
    policy = decision(obs, first_encounter=True)
    assert policy.required is None
    assert policy.validate([GameAction.PRESS_A]) is None
    assert "item" not in policy.legal_sequences


def test_guardian_preserves_existing_encounter_outcome_and_death_tracking():
    referee = NuzlockeReferee({"level_caps": {"brock": 43}})
    referee.freeze_encounter(area="147", species="Gastly", outcome="forfeited")
    ledger = LedgerTracker(referee)
    obs = guardian()
    ledger.update(obs, step=0)
    obs.party[0]["hp"] = 0
    ledger.update(obs, step=1)
    assert len(referee.death_ledger) == 1
    assert referee.encounter_ledger["147"]["outcome"] == "forfeited"
