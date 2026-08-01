from nuzlocke.referee.rules import NuzlockeReferee

RULES = {
    "level_caps": {
        "brock": 14,
        "misty": 21,
        "lt_surge": 24,
        "erika": 29,
        "koga": 43,
        "saber": 43,
        "blaine": 47,
        "giovanni": 50,
        "elite_four": 62,
    }
}


def test_starts_at_brock_cap():
    referee = NuzlockeReferee(RULES)
    assert referee.current_milestone == "brock"
    assert referee.current_cap == 14


def test_advance_moves_cap_forward_with_badges():
    referee = NuzlockeReferee(RULES)
    referee.advance(1)
    assert referee.current_milestone == "misty"
    assert referee.current_cap == 21
    referee.advance(4)
    assert referee.current_milestone == "koga"
    assert referee.current_cap == 43


def test_advance_clamps_at_elite_four_past_all_badges():
    referee = NuzlockeReferee(RULES)
    referee.advance(8)
    assert referee.current_milestone == "elite_four"
    assert referee.current_cap == 62
    referee.advance(99)
    assert referee.current_milestone == "elite_four"
    assert referee.current_cap == 62


def test_advance_does_not_falsely_flag_post_brock_levels():
    referee = NuzlockeReferee(RULES)
    referee.advance(3)  # 3 badges held -> cap should be Erika's (29), not Brock's
    assert referee.current_cap == 29


def test_freeze_encounter_first_only():
    referee = NuzlockeReferee(RULES)
    referee.freeze_encounter("Route 1", "Pidgey", "caught")
    referee.freeze_encounter("Route 1", "Rattata", "caught")
    assert referee.encounter_ledger["Route 1"]["species"] == "Pidgey"


def test_resolve_encounter_updates_outcome():
    referee = NuzlockeReferee(RULES)
    referee.freeze_encounter("Route 1", "Pidgey", "engaged")
    referee.resolve_encounter("Route 1", "caught")
    assert referee.encounter_ledger["Route 1"]["outcome"] == "caught"


def test_note_faint_is_idempotent_per_nickname():
    referee = NuzlockeReferee(RULES)
    mon = {"species": "Squirtle", "nickname": "SHELLY"}
    referee.note_faint(mon, context={"map": "Route 1"})
    referee.note_faint(mon, context={"map": "Route 1"})
    assert len(referee.death_ledger) == 1
