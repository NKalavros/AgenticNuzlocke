from types import SimpleNamespace

from nuzlocke.agents.goals import RoomMap, build_goals
from nuzlocke.agents.navigation import Navigator
from nuzlocke.knowledge.beats import current_beat
from nuzlocke.knowledge.encounters import eligible, encounter_objective, resolved
from nuzlocke.orchestration.ledger import LedgerTracker
from nuzlocke.referee.rules import NuzlockeReferee
from nuzlocke.state.models import PlayerObservation as O


def fixture():
    ref = NuzlockeReferee({"clauses": {"duplicates_clause": True}})
    return SimpleNamespace(
        referee=ref,
        _encounter_tables={},
        _encounter_search_counts={"51": 100},
        _grass_visits={},
        _cycle=102,
        navigator=Navigator(),
        room=RoomMap(),
    )


def obs(**kwargs):
    base = {
        "map_id": 51,
        "map_name": "Viridian Forest",
        "x": 1,
        "y": 1,
        "flags": {"has_pokedex": True},
        "bag": [{"item": "Poke Ball", "quantity": 8}],
        "raw_player": {"name": "RED"},
        "party": [{"species": "Bulbasaur", "level": 18}],
        "badges": ["Boulder"],
        "grass_tiles": [{"x": 2, "y": 1}],
    }
    base.update(kwargs)
    return O(**base)


def test_search_continues_past_old_budget_without_consuming_slot():
    loop = fixture()
    target, _text, owned = encounter_objective(loop, obs(), None)
    assert target == {"kind": "tile", "x": 2, "y": 1}
    assert owned and loop._encounter_search_counts["51"] == 101
    assert loop.referee.encounter_ledger == {}


def test_missed_route22_routes_back_from_pewter():
    loop = fixture()
    loop.referee.encounter_ledger.update({"12": {"outcome": "caught"}, "13": {"outcome": "caught"}})
    target, text, _ = encounter_objective(loop, obs(map_id=2, grass_tiles=[]), None)
    assert target == {"kind": "edge", "dir": "down"} and "Route 22" in text


def test_duplicate_only_table_does_not_consume_encounter():
    loop = fixture()
    loop._encounter_tables["51"] = ["Weedle", "Kakuna"]
    loop.referee.owned_families.add("WEEDLE")
    assert not eligible(loop, 51)
    loop._encounter_tables["51"].append("Pikachu")
    assert eligible(loop, 51)
    assert not loop.referee.encounter_ledger


def test_all_mt_moon_floors_share_one_encounter_including_legacy_keys():
    ref = fixture().referee
    ref.encounter_ledger["59"] = {"outcome": "caught", "species": "Zubat"}
    ledger = LedgerTracker(ref)
    ledger.update(
        obs(map_id=60, in_battle=True, battle={"type": "wild", "enemy": {"species": "Geodude"}}),
        step=1,
    )
    assert not ledger.first_encounter and "60" not in ref.encounter_ledger
    assert resolved({"61": {"outcome": "forfeited"}}, 59)


def test_healing_outranks_encounter_and_route4_waits_for_east_side():
    loop = fixture()
    assert encounter_objective(loop, obs(), SimpleNamespace(id="heal_forest")) is None
    assert encounter_objective(loop, obs(map_id=15, x=8, grass_tiles=[]), None) is None


def test_brock_continuation_and_distinct_moon_ladders():
    assert current_beat(obs(map_id=2)).target == {"kind": "edge", "dir": "right"}
    assert current_beat(obs(map_id=60, x=5, y=5)).target["dest_map"] == 61
    assert current_beat(obs(map_id=60, x=23, y=3)).target["dest_map"] == 255
    room = RoomMap()
    at = obs(
        map_id=59, warps=[{"x": 5, "y": 5, "dest_map": 60}, {"x": 17, "y": 11, "dest_map": 60}]
    )
    goals = build_goals(at, room, objective={"kind": "warp", "dest_map": 60, "x": 17, "y": 11})
    selected = [g for g in goals if g.objective]
    assert len(selected) == 1 and (17, 11) in selected[0].warp_tiles


def test_evolution_guard_rejects_recovery_b_presses():
    from nuzlocke.agents.policy import decision
    from nuzlocke.state.models import GameAction as A

    state = obs(screen_rows=["│What? BULBASAUR│", "│is evolving!│"])
    assert decision(state).validate([A.PRESS_B]) == "required:evolution"
    assert decision(state).validate([A.WAIT_60, A.WAIT_60]) is None


def test_candy_grants_follow_observed_badge_cap():
    import pytest

    from nuzlocke.environment.pa_serve import W_CUR_MAP, prepare_items

    mem = bytearray(65536)
    mem[W_CUR_MAP] = 58
    emu = SimpleNamespace(
        _pyboy=SimpleNamespace(memory=mem),
        read_u8=lambda a: mem[a],
        read_range=lambda a, n: mem[a : a + n],
    )
    reader = SimpleNamespace(
        emu=emu,
        read_party=lambda: [
            {"species": "Bulbasaur", "level": 16, "hp": 42, "max_hp": 42, "status": "OK"}
        ],
    )
    with pytest.raises(ValueError):
        prepare_items(reader, {"target": 18})
    mem[0xD356] = 1
    assert prepare_items(reader, {"target": 18})["granted"] == 2
    with pytest.raises(ValueError):
        prepare_items(reader, {"target": 22})


def test_model_failure_pauses_without_b_or_walks():
    from unittest.mock import MagicMock

    from nuzlocke.orchestration.loop import RunLoop
    from nuzlocke.state.models import AgentRole, ControlState
    from nuzlocke.state.models import GameAction as A

    loop = RunLoop.__new__(RunLoop)
    loop.jev = object()
    loop.store = MagicMock()
    loop.env = MagicMock()
    loop.arbiter = MagicMock()
    task = SimpleNamespace(task_id="t", owner=AgentRole.BATTLE)
    proposal = loop._fallback_proposal(task, RuntimeError("planner disconnected"))
    loop.env.set_control.assert_called_once_with(ControlState.PAUSED)
    assert proposal.actions == [A.WAIT_60]
