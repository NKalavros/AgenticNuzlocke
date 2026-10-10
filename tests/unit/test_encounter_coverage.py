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
    room = RoomMap()
    room.known = {mid: {(1, 1): True, (2, 1): True} for mid in (51, 36)}
    return SimpleNamespace(
        referee=ref,
        _encounter_tables={},
        _encounter_search_counts={"51": 100},
        _grass_visits={},
        _cycle=102,
        navigator=Navigator(),
        room=room,
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


def test_grass_search_never_uses_door_exception_to_enter_an_item_or_wall():
    loop = fixture()
    at = obs(
        x=2,
        y=31,
        grass_tiles=[{"x": 1, "y": 31}, {"x": 2, "y": 30}],
        npcs=[{"slot": 7, "picture": 74, "x": 1, "y": 31, "on_screen": False, "hidden": False}],
    )
    loop.room.known[51] = {(2, 31): True, (1, 31): True, (2, 30): True}
    loop._grass_visits["51:2:30"] = 100
    target, _, _ = encounter_objective(loop, at, None)
    assert target == {"kind": "tile", "x": 2, "y": 30}
    at.npcs = []
    # Explicitly known walls must not become targets either.
    loop.room.known[51][1, 31] = False
    assert encounter_objective(loop, at, None)[0] == target


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


def test_blocked_known_grass_keeps_a_stable_destination_for_planner_access():
    loop = fixture()
    loop.room.known[19] = {(x, y): x != 3 for x in range(8) for y in range(3)}
    at = obs(
        map_id=19,
        map_name="Route 8",
        map_size={"w": 8, "h": 3},
        wild_species=["Vulpix"],
        grass_tiles=[{"x": 5, "y": 1}, {"x": 6, "y": 1}],
    )
    target, text, owned = encounter_objective(loop, at, None)
    assert target == {"kind": "tile", "x": 5, "y": 1} and owned
    assert at.policy["encounter_phase"] == "blocked" and "encounter" in text
    # Moving and seeing more grass must not reset the director's approach route.
    at.x = 2
    at.grass_tiles.append({"x": 4, "y": 1})
    assert encounter_objective(loop, at, None)[0] == target
    assert not loop.referee.encounter_ledger
    # A menu does not discard pending encounter work; an observed opening resumes walking.
    assert encounter_objective(loop, at.model_copy(update={"cutscene": True}), None) is None
    loop.room.known[19][3, 1] = True
    target, _, _ = encounter_objective(loop, at, None)
    assert target["kind"] == "tile" and at.policy["encounter_phase"] == "approach"
    loop.referee.encounter_ledger["19"] = {"outcome": "caught", "species": "Vulpix"}
    assert encounter_objective(loop, at, None) is None


def test_encounter_exploration_is_retained_when_no_patch_is_known():
    loop = fixture()
    at = obs(grass_tiles=[], map_size={"w": 8, "h": 3})
    assert encounter_objective(loop, at, None)[0] == {"kind": "explore"}


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


def test_post_cascade_travel_does_not_reenter_completed_encounter_circuit():
    loop = fixture()
    loop.referee.encounter_ledger.update({"35": {"outcome": "caught"}, "36": {"outcome": "caught"}})
    # The same tiles used to turn every northbound crossing straight back south.
    for mid in (3, 35, 36, 35, 3):
        at = obs(map_id=mid, badges=["Boulder", "Cascade"], grass_tiles=[])
        assert encounter_objective(loop, at, None) is None
    # The pre-Misty return to the gym is still intentional.
    assert encounter_objective(loop, obs(map_id=35), None)[0] == {"kind": "edge", "dir": "down"}
    # A real unresolved local encounter is still searched after Cascade.
    del loop.referee.encounter_ledger["36"]
    at = obs(map_id=36, badges=["Boulder", "Cascade"])
    assert encounter_objective(loop, at, None)[0] == {"kind": "tile", "x": 2, "y": 1}
    assert at.policy["encounter_search"]


def test_rock_tunnel_floors_share_a_slot_including_legacy_floor_keys():
    from nuzlocke.knowledge.encounters import area_key

    assert area_key(82) == area_key(232) == "82"
    assert resolved({"232": {"outcome": "forfeited"}}, 82)
    ref = fixture().referee
    ref.encounter_ledger["82"] = {"outcome": "caught", "species": "Machop"}
    ledger = LedgerTracker(ref)
    ledger.update(
        obs(map_id=232, in_battle=True, battle={"type": "wild", "enemy": {"species": "Onix"}}),
        step=1,
    )
    assert not ledger.first_encounter and "232" not in ref.encounter_ledger


def test_route5_side_lane_reenters_via_cerulean_without_consuming_encounter():
    from nuzlocke.knowledge.map_reference import atlas

    loop = fixture()
    for mid in (3, 16):
        data = atlas()["maps"][str(mid)]
        loop.room.known[mid] = {
            (x, y): c == "." for y, row in enumerate(data["rows"]) for x, c in enumerate(row)
        }
    grass = atlas()["maps"]["16"]["grass"]
    loop.navigator.maps["16"] = {"grass": grass}
    at = obs(
        map_id=16,
        map_name="Route 5",
        x=15,
        y=2,
        map_size={"w": 20, "h": 36},
        connections=["up", "down"],
        grass_tiles=[],
        wild_species=["Meowth"],
        badges=["Boulder", "Cascade"],
    )
    assert encounter_objective(loop, at, None)[0] == {"kind": "edge", "dir": "up"}
    at.map_id, at.map_name, at.x, at.y = 3, "Cerulean City", 25, 35
    at.map_size = {"w": 40, "h": 36}
    at.wild_species = []
    assert encounter_objective(loop, at, None)[0] == {"kind": "tile", "x": 23, "y": 35}
    at.x = 23
    assert encounter_objective(loop, at, None)[0] == {"kind": "edge", "dir": "down"}
    at.map_id, at.map_name, at.x, at.y = 16, "Route 5", 13, 0
    at.map_size = {"w": 20, "h": 36}
    at.wild_species = ["Meowth"]
    target = encounter_objective(loop, at, None)[0]
    assert target["kind"] == "tile" and [target["x"], target["y"]] in grass
    assert not loop.referee.encounter_ledger
    loop.referee.encounter_ledger["16"] = {"outcome": "caught", "species": "Meowth"}
    assert encounter_objective(loop, at, None) is None
    at.map_id, at.x, at.y = 3, 25, 35
    at.map_size = {"w": 40, "h": 36}
    at.wild_species = []
    assert encounter_objective(loop, at, None) is None
