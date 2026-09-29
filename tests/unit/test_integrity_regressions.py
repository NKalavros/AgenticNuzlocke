"""Regressions using the shapes of actual Red Star observations."""

import pytest

from nuzlocke.agents import battle
from nuzlocke.agents.goals import ObjectTrust, RoomMap, build_goals
from nuzlocke.agents.policy import decision
from nuzlocke.orchestration.checkpoint import IntegrityError, RunCheckpoint, savestate_path
from nuzlocke.orchestration.ledger import LedgerTracker
from nuzlocke.referee.rules import NuzlockeReferee
from nuzlocke.state.models import GameAction as A
from nuzlocke.state.models import PlayerObservation as O


def mon(species="Bulbasaur", hp=20, level=12):
    return {
        "species": species,
        "nickname": species.upper(),
        "hp": hp,
        "max_hp": 20,
        "level": level,
        "ot_id": 3902,
        "status": "OK",
        "moves": [{"id": 33, "name": "Tackle", "pp": 0}, {"id": 45, "name": "Growl", "pp": 30}],
    }


def test_edge_crossings_preserve_door_trust():
    before = O(
        map_id=0,
        x=10,
        y=0,
        map_size={"w": 20, "h": 18},
        connections=["up"],
        warps=[{"x": 5, "y": 5, "dest_map": 37}],
    )
    after = O(map_id=12, x=10, y=35)
    trust = ObjectTrust()
    for _ in range(4):
        assert not trust.record(
            before,
            after,
            [{"action": "walk_up", "map_id": 12, "x0": 10, "y0": 0, "x1": 10, "y1": 35}],
        )
    assert trust.trusted(before)


def test_sentinel_door_matches_both_return_map_and_code_goal():
    obs = O(
        map_id=39,
        return_map=0,
        x=3,
        y=6,
        map_size={"w": 8, "h": 8},
        warps=[{"x": 2, "y": 7, "dest_map": 255}],
    )
    for dest in (0, 255):
        goals = build_goals(obs, RoomMap(), objective={"kind": "warp", "dest_map": dest})
        assert any(g.objective and g.kind == "exit" for g in goals)


def test_pp_lookup_uses_real_title_case_and_active_slot():
    obs = O(in_battle=True, active_party_slot=1, party=[mon("Pidgey"), mon()])
    assert battle._pp(obs) == {"TACKLE": 0, "GROWL": 30}
    screen = battle.BattleScreen("moves", ("TACKLE", "GROWL"), 0)
    assert battle.fallback(screen, obs) == "move_1"
    assert "move_0" not in battle.move_questions(obs, screen.options, {})["action"]["criteria"]
    assert battle.active_mon(obs)["species"] == "Bulbasaur"


def test_encounter_commits_once_and_duplicate_family_rerolls():
    ref = NuzlockeReferee({"clauses": {"duplicates_clause": True}})
    ledger = LedgerTracker(ref)

    def obs(enemy=None, party=None, bag=True):
        return O(
            map_id=12,
            map_name="Route 1",
            party=party or [mon()],
            bag=[{"item": "Poke Ball", "quantity": 3}] if bag else [],
            in_battle=bool(enemy),
            battle={"type": "wild", "enemy": {"species": enemy}} if enemy else None,
        )

    ledger.update(obs("Ivysaur"), step=0)
    assert not ledger.first_encounter and not ref.encounter_ledger
    ledger.update(obs(), step=1)
    ledger.update(obs("Pidgey"), step=2)
    assert ledger.first_encounter
    ledger.update(obs(party=[mon(), mon("Pidgey")]), step=3)
    ledger.update(obs("Rattata"), step=4)
    ledger.update(obs(), step=5)
    assert ref.encounter_ledger["12"]["outcome"] == "caught"
    ledger.update(
        O(
            map_id=13,
            map_name="Route 2",
            party=[mon()],
            bag=[],
            in_battle=True,
            battle={"type": "wild", "enemy": {"species": "Rattata"}},
        ),
        step=6,
    )
    assert ref.encounter_ledger["13"]["outcome"] == "engaged"  # balls once acquired


def test_death_survives_center_evolution_and_reordering():
    ref = NuzlockeReferee({})
    ledger = LedgerTracker(ref)
    first = O(party=[mon(), mon("Pidgey")])
    ledger.update(first, step=0)
    identity = first.party[0]["capture_id"]
    ledger.update(O(party=[mon(hp=0), mon("Pidgey")]), step=1)
    healed = O(party=[mon("Pidgey"), mon("Ivysaur")])
    ledger.update(healed, step=2)
    assert healed.party[1]["capture_id"] == identity
    assert healed.party[1]["dead"]
    assert any("dead" in v for v in ref.assert_party_legal(healed))


def test_cap_is_checked_at_entry_not_mid_battle():
    ref = NuzlockeReferee({"level_caps": {"brock": 14}})
    ledger = LedgerTracker(ref)
    battle_obs = O(party=[mon(level=14)], in_battle=True, battle={"type": "trainer"})
    ledger.update(battle_obs, step=0)
    up = battle_obs.model_copy(update={"party": [mon(level=15)]})
    ledger.update(up, step=1)
    assert ref.assert_party_legal(up) == []
    ended = O(party=[mon(level=15)])
    ledger.update(ended, step=2)
    assert ref.assert_party_legal(ended)


class SaveEnv:
    def __init__(self, path):
        self.path = path

    def save_checkpoint(self, name):
        p = savestate_path(self.path, name)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"frame")


def test_checkpoint_pairs_state_and_controller_and_rejects_ambiguous_replay(tmp_path):
    manager = RunCheckpoint(tmp_path, {"rom": "abc", "rules": "def"})
    manager.begin()
    manager.commit(SaveEnv(tmp_path), {"dead": ["capture-1"]})
    assert manager.load() == {"dead": ["capture-1"]}
    manager.begin()
    with pytest.raises(IntegrityError, match="in flight"):
        manager.load()
    manager.pending.unlink()
    savestate_path(tmp_path, "commit-00000001").write_bytes(b"altered")
    with pytest.raises(IntegrityError, match="checksum"):
        manager.load()


def test_checkpoint_rejects_legacy_and_changed_rules(tmp_path):
    manager = RunCheckpoint(tmp_path, {"rules": "a"})
    with pytest.raises(IntegrityError, match="Legacy"):
        manager.load()
    manager.commit(SaveEnv(tmp_path), {})
    other = RunCheckpoint(tmp_path, {"rules": "b"})
    with pytest.raises(IntegrityError, match="do not match"):
        other.load()


def test_heal_whole_party_before_preparing_new_capture():
    from nuzlocke.agents.system3 import heal_beat

    obs = O(map_id=41, party=[mon(hp=19), mon("Rattata", level=2)])
    assert heal_beat(obs).id == "heal_nurse"
    obs.party[0]["hp"] = 20
    assert heal_beat(obs) is None


def test_brock_preparation_heals_even_above_half_hp():
    from nuzlocke.agents.system3 import heal_beat

    assert heal_beat(O(map_id=2, party=[mon(hp=19, level=14)])).id == "heal_pewter"


def test_rule_event_chain_detects_tampering(tmp_path):
    from nuzlocke.state.store import EventStore

    store = EventStore(tmp_path)
    store.append("candy_grant", {"granted": 6})
    store.append("ledger_commit", {"dead": ["capture-1"]})
    head = store.integrity_head(verify=True)
    assert head
    data = store.events_path.read_text().replace('"granted": 6', '"granted": 7')
    store.events_path.write_text(data)
    with pytest.raises(IntegrityError, match="checksum"):
        store.integrity_head(verify=True)


def test_rule_event_chain_detects_truncated_tail(tmp_path):
    from nuzlocke.state.store import EventStore

    store = EventStore(tmp_path)
    store.append("ledger_commit", {"dead": ["capture-1"]})
    store.events_path.write_text("")
    with pytest.raises(IntegrityError, match="disagree"):
        store.integrity_head(verify=True)


def test_wipe_policy_blocks_every_menu():
    obs = O(policy={"wiped": True})
    assert decision(obs).validate([A.PRESS_A])


def test_encounter_waits_for_enemy_species_to_load():
    ref = NuzlockeReferee({})
    ledger = LedgerTracker(ref)
    obs = O(
        map_id=12,
        party=[mon()],
        bag=[{"item": "Poke Ball"}],
        in_battle=True,
        battle={"type": "wild", "enemy": {}},
    )
    ledger.update(obs, step=0)
    assert not ref.encounter_ledger
    obs.battle["enemy"] = {"species": "Pidgey"}
    ledger.update(obs, step=1)
    assert ledger.first_encounter
    assert ref.encounter_ledger["12"]["species"] == "Pidgey"


def test_unframed_party_menu_excludes_permanent_deaths():
    obs = O(
        in_battle=True,
        active_party_slot=0,
        party=[mon(), {**mon("Pidgey"), "dead": True}, mon("Rattata")],
        screen_rows=[
            "   BULBASAUR  12",
            "▶             20/ 20",
            "   PIDGEY 12",
            "              20/ 20",
            "   RATTATA 12",
            "              20/ 20",
        ],
    )
    assert battle.party_cursor(obs) == 0
    choices = decision(obs).legal_sequences
    assert "party_1" not in choices
    assert choices["party_2"] == [A.WALK_DOWN, A.WALK_DOWN, A.PRESS_A]
    assert decision(obs).validate([A.WALK_DOWN, A.PRESS_A])


def test_audited_grant_is_exact_and_restricted():
    from types import SimpleNamespace

    from nuzlocke.environment.pa_serve import W_CUR_MAP, W_IS_IN_BATTLE, prepare_items

    memory = bytearray(65536)
    emu = SimpleNamespace(
        _pyboy=SimpleNamespace(memory=memory),
        read_u8=lambda a: memory[a],
        read_range=lambda a, n: memory[a : a + n],
    )
    reader = SimpleNamespace(emu=emu, read_party=lambda: [mon(level=5)])
    memory[W_CUR_MAP] = 40
    assert prepare_items(reader, {"target": 8})["granted"] == 3
    assert prepare_items(reader, {"target": 8})["granted"] == 0
    with pytest.raises(ValueError, match="lab preparation"):
        prepare_items(reader, {"target": 14})
    memory[W_IS_IN_BATTLE] = 2
    with pytest.raises(ValueError, match="battle"):
        prepare_items(reader, {"target": 8})
    memory[W_IS_IN_BATTLE] = 0
    memory[W_CUR_MAP] = 12
    with pytest.raises(ValueError, match="Center"):
        prepare_items(reader, {"target": 8})


def test_battle_transition_settles_before_battle_flag_changes():
    from nuzlocke.environment.nous_red import busy

    rows = ["9" * 20, "9" * 20] + ["999               99"] * 14 + ["9" * 20] * 2
    assert busy({"screen": rows, "input": {"battle": 0, "walking": 0, "joy_ignore": 0}})


def test_adjacent_exit_mats_choose_reachable_entry():
    # Forest north gate: the nearer right mat is blocked below; the left mat is open.
    obs = O(
        map_id=51,
        x=2,
        y=2,
        map_size={"w": 4, "h": 4},
        warps=[{"x": 1, "y": 0, "dest_map": 47}, {"x": 2, "y": 0, "dest_map": 47}],
        npcs=[{"x": 2, "y": 1}],
    )
    room = RoomMap()
    room.known[51] = {(x, y): False for x in range(4) for y in range(4)}
    room.known[51].update({(2, 2): True, (1, 2): True, (1, 1): True})
    # A measured grid so unknown-screen fallback does not invent a way around the blocker.
    obs.collision_ascii = "   A B C D E F G H I J\n" + "\n".join(
        f"{r + 1:2d} "
        + " ".join("." if (c - 2, r - 2) in {(2, 2), (1, 2), (1, 1)} else "#" for c in range(10))
        for r in range(9)
    )
    goal = next(
        g for g in build_goals(obs, room, objective={"kind": "warp", "dest_map": 47}) if g.objective
    )
    assert goal.actions[:3] == [A.WALK_LEFT, A.WALK_UP, A.WALK_UP]
