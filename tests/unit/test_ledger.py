from nuzlocke.orchestration.ledger import LedgerTracker
from nuzlocke.referee.rules import NuzlockeReferee
from nuzlocke.state.models import PlayerObservation

RULES = {"level_caps": {"brock": 14}}


def _obs(**kw):
    kw.setdefault("bag", [{"item": "Poke Ball", "quantity": 5}])
    return PlayerObservation(**kw)


def test_wild_battle_start_freezes_encounter():
    referee = NuzlockeReferee(RULES)
    tracker = LedgerTracker(referee)
    tracker.update(_obs(map_name="Route 1", in_battle=False, party=[]), step=0)
    tracker.update(
        _obs(
            map_name="Route 1",
            in_battle=True,
            battle={"in_battle": True, "type": "wild", "enemy": {"species": "Pidgey"}},
            party=[],
        ),
        step=1,
    )
    assert referee.encounter_ledger["Route 1"]["species"] == "Pidgey"
    assert referee.encounter_ledger["Route 1"]["outcome"] == "engaged"


def test_trainer_battle_does_not_freeze_encounter():
    referee = NuzlockeReferee(RULES)
    tracker = LedgerTracker(referee)
    tracker.update(_obs(map_name="Route 1", in_battle=False, party=[]), step=0)
    tracker.update(
        _obs(
            map_name="Route 1",
            in_battle=True,
            battle={"in_battle": True, "type": "trainer", "enemy": {"species": "Rattata"}},
            party=[],
        ),
        step=1,
    )
    assert referee.encounter_ledger == {}


def test_battle_end_resolves_caught_when_party_grows():
    referee = NuzlockeReferee(RULES)
    tracker = LedgerTracker(referee)
    tracker.update(
        _obs(map_name="Route 1", in_battle=False, party=[{"nickname": "SHELLY"}]), step=0
    )
    tracker.update(
        _obs(
            map_name="Route 1",
            in_battle=True,
            battle={"in_battle": True, "type": "wild", "enemy": {"species": "Pidgey"}},
            party=[{"nickname": "SHELLY"}],
        ),
        step=1,
    )
    tracker.update(
        _obs(
            map_name="Route 1",
            in_battle=False,
            party=[{"nickname": "SHELLY"}, {"nickname": "PIDGE"}],
        ),
        step=2,
    )
    assert referee.encounter_ledger["Route 1"]["outcome"] == "caught"


def test_second_wild_battle_on_same_map_does_not_overwrite_frozen_encounter():
    referee = NuzlockeReferee(RULES)
    tracker = LedgerTracker(referee)
    tracker.update(_obs(map_name="Route 1", in_battle=False, party=[]), step=0)
    tracker.update(
        _obs(
            map_name="Route 1",
            in_battle=True,
            battle={"in_battle": True, "type": "wild", "enemy": {"species": "Pidgey"}},
            party=[],
        ),
        step=1,
    )
    tracker.update(_obs(map_name="Route 1", in_battle=False, party=[]), step=2)
    tracker.update(
        _obs(
            map_name="Route 1",
            in_battle=True,
            battle={"in_battle": True, "type": "wild", "enemy": {"species": "Rattata"}},
            party=[],
        ),
        step=3,
    )
    assert referee.encounter_ledger["Route 1"]["species"] == "Pidgey"


def test_faint_transition_notes_death_once():
    referee = NuzlockeReferee(RULES)
    tracker = LedgerTracker(referee)
    alive = _obs(party=[{"nickname": "SHELLY", "species": "Squirtle", "status": "OK"}])
    fainted = _obs(party=[{"nickname": "SHELLY", "species": "Squirtle", "status": "Fainted"}])
    tracker.update(alive, step=0)
    tracker.update(fainted, step=1)
    tracker.update(fainted, step=2)
    assert len(referee.death_ledger) == 1
    assert referee.death_ledger[0]["nickname"] == "SHELLY"


def test_an_encounter_before_poke_balls_does_not_count():
    referee = NuzlockeReferee(RULES)
    tracker = LedgerTracker(referee)
    wild = {"in_battle": True, "type": "wild", "enemy": {"species": "Rattata"}}
    tracker.update(_obs(map_name="Route 1", in_battle=False, party=[], bag=[]), step=0)
    tracker.update(_obs(map_name="Route 1", in_battle=True, battle=wild, party=[], bag=[]), step=1)
    assert "Route 1" not in referee.encounter_ledger
    assert tracker.first_encounter is False
    tracker.update(_obs(map_name="Route 1", in_battle=False, party=[]), step=2)
    tracker.update(_obs(map_name="Route 1", in_battle=True, battle=wild, party=[]), step=3)
    assert tracker.first_encounter is True
