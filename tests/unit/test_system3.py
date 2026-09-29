"""System 3: run when about to faint, heal below half, and a wipe ends the run."""

from __future__ import annotations

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
