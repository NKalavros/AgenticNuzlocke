from copy import deepcopy
from types import SimpleNamespace as NS
from unittest.mock import Mock
import json

import pytest

from nuzlocke.agents.system4 import System4, team_signature, team_beat
from nuzlocke.agents.storage import StorageController
from nuzlocke.agents.calculations import damage, projected, comparisons
from nuzlocke.agents.lead_rotation import LeadRotationError
from nuzlocke.agents.level_buffer import switch_target, switch_order
from nuzlocke.agents.policy import decision
from nuzlocke.assets import data
from nuzlocke.llm.settings import resolve_agents_config, configured_roles
from nuzlocke.referee.rules import NuzlockeReferee
from nuzlocke.state.models import PlayerObservation as O, TeamPlan, GameAction as A


def mon(identity="capture-0001", species="Drowzee", level=20, **kw):
    return dict(
        capture_id=identity,
        species=species,
        nickname=species.upper(),
        level=level,
        hp=60,
        max_hp=60,
        status="OK",
        stats=dict(attack=30, defense=30, speed=30, special=40),
        types=["Psychic"],
        moves=[dict(id=93, name="CONFUSION", pp=25)],
        ot_id=17,
        dvs=[1, 2, 3, 4],
        **kw,
    )


def obs():
    return O(
        map_id=133,
        x=13,
        y=4,
        facing="up",
        party=[mon(), mon("capture-0002", "Pidgey")],
        storage=dict(complete=True, active_box=1, boxes=[dict(box=1, members=[mon("capture-0003", "Geodude", box=1, slot=0)])]),
        policy=dict(level_cap=43),
        battle_style="SET",
    )


def plan(o):
    return TeamPlan(
        party=[m["capture_id"] for m in o.party],
        lead=o.party[0]["capture_id"],
        levels={m["capture_id"]: m["level"] for m in o.party},
        reasoning="Preserve the team.",
        lines=[dict(enemy="*", active=m["capture_id"], strategy=dict(moves=["CONFUSION"])) for m in o.party],
    )


def loop():
    ref = NuzlockeReferee({"level_caps": {"brock": 43}})
    return NS(
        referee=ref,
        store=Mock(),
        env=Mock(),
        agents_cfg=resolve_agents_config({"provider": "dual", "system2": {"provider": "codex"}}),
    )


def job(s, o):
    s.state["job"] = dict(
        id="Soul",
        name="Koga",
        badge="Soul",
        phase="ready",
        plan=plan(o).model_dump(mode="json"),
        consumed={},
        signature=team_signature(o),
    )


def test_system4_configuration_inherits_resolved_override_and_can_disable():
    cfg = resolve_agents_config({"provider": "dual", "system2": {"provider": "codex"}}, {"system2": {"model": "test-model"}})
    assert cfg["system4"]["model"] == "test-model"
    assert "system4" in configured_roles(cfg)
    cfg = resolve_agents_config({"provider": "dual", "system2": {"provider": "codex"}, "system4": {"enabled": False}})
    assert "system4" not in configured_roles(cfg)
    cfg = resolve_agents_config({"provider": "dual", "system2": {"provider": "codex"}, "system4": {"model": "specialist"}})
    assert cfg["system4"]["model"] == "specialist"
    assert cfg["system2"]["model"] is None


def test_death_triggers_once_and_rebuilds_after_battle_then_survives_resume():
    s = System4()
    o = obs()
    r = loop()
    o.in_battle = True
    o.party[0]["dead"] = True
    o.party[0]["hp"] = 0
    r.referee.note_faint(o.party[0], {})
    s.observe(o, r)
    assert s.state["job"]["reason"] == "recorded death"
    s.state["job"]["reason"] = "battle line unavailable"
    s.observe(o, r)
    assert r.store.append.call_count == 1
    saved = json.loads(json.dumps(s.snapshot()))
    t = System4()
    t.restore(saved)
    o.in_battle = False
    t.observe(o, r)
    assert t.state["job"]["reason"] == "post-battle replacement"
    assert t.state["job"]["plan"] is None
    assert saved["job"]["reason"] == "battle line unavailable"


def test_readiness_is_separate_from_route_card_and_openers_use_pp_evidence():
    s = System4()
    o = obs()
    r = loop()
    job(s, o)
    o.in_battle = True
    o.active_party_slot = 0
    o.battle = {"type": "trainer", "enemy": {"species": "Koffing", "hp": 40, "level": 37, "status": "OK"}}
    p = s.state["job"]["plan"]["lines"][0]["strategy"]
    p["opening_moves"] = ["CONFUSION"]
    s.observe(o, r)
    assert s.battle_plan(o)["opening_moves"] == ["CONFUSION"]
    s.observe(o, r)
    assert s.battle_plan(o)["opening_moves"] == ["CONFUSION"]
    o.party[0]["moves"][0]["pp"] -= 1
    s.observe(o, r)
    assert s.battle_plan(o)["opening_moves"] == []
    t = System4()
    t.restore(json.loads(json.dumps(s.snapshot())))
    assert t.battle_plan(o)["opening_moves"] == []
    o.active_party_slot = 1
    t.observe(o, r)
    o.active_party_slot = 0
    t.observe(o, r)
    assert t.battle_plan(o)["opening_moves"] == []
    o.battle["enemy"]["hp"] = 0
    t.observe(o, r)
    o.battle["enemy"]["hp"] = 40
    t.observe(o, r)
    assert t.battle_plan(o)["opening_moves"] == ["CONFUSION"]


def test_dead_active_uses_survivor_line_and_no_box_access_midbattle():
    s = System4()
    o = obs()
    job(s, o)
    o.in_battle = True
    o.battle = {"type": "trainer"}
    o.active_party_slot = 0
    o.party[0]["hp"] = 0
    o.party[0]["dead"] = True
    s.state["job"]["plan"]["lead"] = "capture-0002"
    assert s.battle_plan(o)["switch_to"] == "capture-0002"
    assert StorageController().turn(o, [], Mock()) == ([], "")


def test_legality_and_field_moves_are_checked_before_accepting_plan():
    o = obs()
    p = plan(o)
    System4.validate(p, o, 43)
    p.party.append("capture-0003")
    o.storage["boxes"][0]["members"][0]["dead"] = True
    with pytest.raises(LeadRotationError, match="ineligible"):
        System4.validate(p, o, 43)
    p = plan(o)
    p.levels["capture-0001"] = 44
    with pytest.raises(LeadRotationError, match="cap"):
        System4.validate(p, o, 43)
    o.party[1]["moves"] = [dict(id=15, name="CUT", pp=30)]
    p = plan(o)
    p.party = p.party[:1]
    p.levels = {"capture-0001": 20}
    with pytest.raises(LeadRotationError, match="field"):
        System4.validate(p, o, 43)


def test_unknown_move_and_malformed_conditions_are_rejected():
    o = obs()
    p = plan(o)
    p.learn = {"capture-0001": {85: 93}}
    with pytest.raises(LeadRotationError, match="unavailable"):
        System4.validate(p, o, 43)
    raw = plan(o).model_dump()
    raw["lines"][0]["enemy_status"] = ["confused"]
    with pytest.raises(ValueError):
        TeamPlan.model_validate(raw)


def test_owned_identity_survives_storage_reorder_evolution_and_legacy_upgrade():
    o = obs()
    r = NuzlockeReferee({"level_caps": {"brock": 43}})
    r.identify(o)
    first = o.party[0]["capture_id"]
    dead = o.party[1]["capture_id"]
    r.note_faint(o.party[1], {})
    m = o.party.pop(0)
    o.storage["boxes"][0]["members"].append(m)
    r.identify(o)
    assert m["capture_id"] == first
    m["species"] = "Hypno"
    o.storage["boxes"][0]["members"].remove(m)
    o.party.insert(0, m)
    r.identify(o)
    assert o.party[0]["capture_id"] == first
    assert o.party[1]["capture_id"] == dead and o.party[1]["dead"]
    saved = r.snapshot()
    saved["roster"][first].pop("dvs")
    t = NuzlockeReferee({"level_caps": {"brock": 43}})
    t.restore(saved)
    t.identify(o)
    assert o.party[0]["capture_id"] == first and t.roster[first]["dvs"] == m["dvs"]
    assert t.encounter_ledger == {}  # discovery does not create catches


def test_planned_switch_outranks_xp_preference_but_dead_target_is_excluded():
    o = obs()
    o.in_battle = True
    o.active_party_slot = 0
    o.policy.update(level_cap=21, level_cap_buffer=1, strategic_battle=True)
    assert switch_target(o) is None
    assert switch_order(o, "capture-0002")[0][0] == 1
    o.party[1]["dead"] = True
    assert switch_order(o, "capture-0002") == []


def test_teaching_table_keeps_actual_tm_numbering():
    tm = data("walkthrough/teaching_red.json")
    assert len(tm) == 55 and tm["229"] == 94 and tm["250"] == 164 and tm["196"] == 15


def test_calculations_label_unknown_and_respect_type_split_immunity_and_explosion():
    a = projected(dict(species="Drowzee", level=43))
    b = projected(dict(species="Koffing", level=37))
    assert damage(a, b, {"id": 93})["damage"][1] > 0
    assert damage(a, b, {"id": 117}).get("unknown")  # Bide is not a harmless status move
    assert damage(a, b, {"id": 69}).get("unknown")
    ground = projected(dict(species="Geodude", level=43))
    electric = projected(dict(species="Pikachu", level=43))
    assert damage(electric, ground, {"id": 85})["damage"] == [0, 0]
    assert damage(b, a, {"id": 120})["damage"][1] > damage(b, a, {"id": 33})["damage"][1]
    assert damage(a, b, {"id": 93}, critical=True)["damage"][1] > damage(a, b, {"id": 93})["damage"][1]
    o = obs()
    c = comparisons(o.party, [dict(species="Koffing", level=37)], 43)
    assert c[0]["incoming"].startswith("unknown")


def test_pc_transfer_is_verified_and_restored_before_another_transfer():
    o = obs()
    pc = StorageController()
    desired = ["capture-0002", "capture-0003"]
    actions, _ = pc.turn(o, desired, Mock())
    assert actions == [A.PRESS_A]
    saved = pc.snapshot()
    pc = StorageController()
    pc.restore(saved)
    removed = o.party.pop(0)
    removed["box"] = 1
    o.storage["boxes"][0]["members"].append(removed)
    pc.turn(o, desired, Mock())
    assert pc.pending["operation"] == "withdraw" and pc.pending["target"] == "capture-0003"
    assert saved["pending"]["operation"] == "deposit"
    # Unexpected withdrawal is not accepted as successful.
    o.party.append(mon("capture-unexpected", "Vulpix"))
    with pytest.raises(LeadRotationError, match="unexpected"):
        pc.turn(o, desired, Mock())


def test_full_box_changes_before_deposit_and_leaves_a_usable_party_member():
    o = obs()
    o.storage["boxes"][0]["members"] = [mon(f"boxed-{i}", "Geodude", box=1, slot=i) for i in range(20)]
    o.storage["boxes"].append(dict(box=2, members=[]))
    pc = StorageController()
    pc.turn(o, ["capture-0002"], Mock())
    assert pc.pending["operation"] == "box" and pc.pending["box"] == 2
    o = obs()
    o.party = o.party[:1]
    pc = StorageController()
    pc.turn(o, ["capture-0003"], Mock())
    assert pc.pending["operation"] == "withdraw"


def test_pc_arbiter_requires_owned_transaction_and_blocks_stale_input():
    o = obs()
    o.policy["storage_actions"] = ["walk_down"]
    assert decision(o).validate([A.WALK_DOWN]) is None
    assert decision(o).validate([A.PRESS_A]) is not None


def test_team_preparation_retains_mandatory_parent():
    o = obs()
    s = System4()
    job(s, o)
    s.state["job"]["phase"] = "roster"
    s.state["job"]["plan"]["party"] = ["capture-0002", "capture-0003"]
    s.annotate(o)
    b = team_beat(o)
    assert b.id == "prepare_team" and b.target == dict(kind="face", x=13, y=4, dir="up")
    assert json.loads(json.dumps(team_signature(o))) == team_signature(o)


def test_gen1_damage_matches_independent_calculator_fixtures():
    from pathlib import Path

    fixtures = json.loads((Path(__file__).parents[1] / "fixtures/system4_damage.json").read_text())
    for case in fixtures["cases"]:
        a = projected(dict(species=case["attacker"], level=case["level"], status=case["status"].upper() or "OK"))
        b = projected(dict(species=case["defender"], level=case["enemy_level"]))
        assert damage(a, b, {"id": case["move"]}, critical=case["critical"])["damage"] == case["expected"], case


def test_ordinary_wild_catch_does_not_call_or_override_system4():
    s = System4()
    o = obs()
    job(s, o)
    o.in_battle = True
    o.battle = {"type": "wild"}
    s.annotate(o)
    assert not o.policy["strategic_battle"] and s.battle_plan(o) is None
    assert s.turn(NS(referee=NS(wiped=False), agents_cfg=loop().agents_cfg), o) == ([], "")


def test_battle_line_filters_failed_conditions_and_can_switch_at_full_hp():
    s = System4()
    o = obs()
    job(s, o)
    o.in_battle = True
    o.battle = {"type": "trainer", "enemy": {"species": "Koffing", "status": "OK"}}
    p = s.state["job"]["plan"]["lines"][0]["strategy"]
    p.update(switch_to="capture-0002", switch_below=1.0)
    assert s.battle_plan(o)["switch_below"] > 1
    p.update(switch_to=None, switch_below=0, avoid_moves=["CONFUSION"])
    assert s.battle_plan(o) is None


def test_candy_completion_releases_latch_before_team_healing():
    from nuzlocke.agents.preparation import preparation_turn

    s = System4()
    o = obs()
    job(s, o)
    s.state["job"]["phase"] = "levels"
    s.annotate(o)
    r = loop()
    r.system4 = s
    r._preparing_target = 20
    r._closing_preparation = False
    r.storage = StorageController()
    r.run_cfg = {"rare_candy": {"enabled": True}}
    r.gym_preparation = NS(pending=None)
    o.party[0]["hp"] -= 1
    assert s.turn(r, o) == ([], "")
    s.annotate(o)
    actions, _ = preparation_turn(r, o)
    assert actions == [A.PRESS_B] and r._preparing_target is None and r._closing_preparation


def test_duplicate_dvs_in_same_family_pause_instead_of_reassigning_death():
    o = obs()
    o.party[1] = deepcopy(o.party[0])
    r = NuzlockeReferee({})
    with pytest.raises(RuntimeError, match="Ambiguous"):
        r.identify(o)


def test_review_uses_separate_provider_and_fills_omitted_level_targets(tmp_path, monkeypatch):
    s = System4()
    o = obs()
    r = loop()
    r.run_dir = tmp_path
    job(s, o)
    s.state["job"]["phase"] = "review"
    value = plan(o).model_dump(mode="json")
    value["levels"] = {}
    provider = Mock()
    provider.complete.return_value = NS(parsed=value, usage={}, raw_text="")
    factory = Mock(return_value=provider)
    monkeypatch.setattr("nuzlocke.agents.system4.create_provider", factory)
    s.review(r, o, "major challenge")
    assert factory.call_args.kwargs["role"] == "system4"
    assert factory.call_args.args[1] == tmp_path / "system4_workspace"
    assert s.state["job"]["plan"]["levels"] == {"capture-0001": 20, "capture-0002": 20}
    assert s.state["job"]["phase"] == "roster"
    s.review(r, o, "preparation verified")
    assert s.state["job"]["phase"] == "ready" and factory.call_count == 1


def test_box_memory_reader_uses_wram_for_active_box_and_banked_sram_for_others(monkeypatch):
    from nuzlocke.environment.storage import read_storage

    monkeypatch.setattr("nuzlocke.environment.storage.supported_rom", lambda _: True)
    raw = bytearray(1122)
    raw[0] = 1
    raw[1] = raw[22] = 48
    raw[2] = 255
    raw[25] = 12
    raw[27] = raw[28] = 24
    raw[30] = 93
    raw[34:36] = (17).to_bytes(2, "big")
    raw[49:51] = bytes([0x12, 0x34])
    raw[51] = 25
    raw[902:910] = bytes([0x83, 0x91, 0x8E, 0x96, 0x99, 0x84, 0x84, 0x50])

    class Memory:
        def __getitem__(self, index):
            bank, span = index
            return raw if bank == 3 and span.start == 0xA000 else bytes(1122)

    e = NS(
        rom_path="verified",
        read_u8=lambda _: 0x80,
        read_range=lambda a, n: raw if a == 0xDA80 else bytes(n),
        _pyboy=NS(memory=Memory()),
    )
    result = read_storage(e, [])
    assert result["complete"] and result["active_box"] == 1
    assert result["boxes"][0]["members"][0]["nickname"] == "DROWZEE"
    assert result["boxes"][6]["members"][0]["dvs"] == [1, 2, 3, 4]
    e.read_u8 = lambda _: 0  # Before the game's first box change, SRAM boxes are uninitialized.
    assert not read_storage(e, [])["boxes"][6]["members"]
    raw[0] = 21
    assert not read_storage(e, [])["complete"]


def test_verified_pc_labels_save_prompt_and_checkpointed_consent():
    from pathlib import Path

    rows = json.loads((Path(__file__).parents[1] / "fixtures/system4_pc.json").read_text())
    o = obs()
    pc = StorageController()
    pc.pending = dict(operation="deposit", box=1, target="capture-0001", before=[m["capture_id"] for m in o.party], selected=False)
    o.screen_rows = rows["pc_3"]
    assert pc.actions(o) == [A.PRESS_B]  # narration over old BILL PC cursor
    o.screen_rows = rows["pc_6"]
    assert pc.actions(o) == [A.WALK_DOWN]  # DEPOSIT PM ligature
    pc.pending["operation"] = "box"
    pc.pending["box"] = 2
    o.screen_rows = rows["box_13"]
    assert pc.actions(o) == [A.PRESS_B]  # no observed save request
    o.screen_rows = rows["box_11"]
    pc.actions(o)
    t = StorageController()
    t.restore(json.loads(json.dumps(pc.snapshot())))
    o.screen_rows = rows["box_13"]
    assert t.actions(o) == [A.PRESS_A]
    o.screen_rows = rows["box_15"]
    assert t.actions(o) == [A.WALK_DOWN]
    o.screen_rows = rows["box_16"]
    assert t.actions(o) == [A.PRESS_A]


def test_strategic_switch_cannot_target_itself_or_cycle_into_injured_recipient():
    o = obs()
    p = plan(o)
    p.lines[0].strategy.switch_to = p.lines[0].active
    with pytest.raises(LeadRotationError, match="unavailable"):
        System4.validate(p, o, 43)
    s = System4()
    job(s, o)
    o.in_battle = True
    o.battle = {"type": "trainer"}
    l = s.state["job"]["plan"]["lines"][0]
    l["strategy"].update(switch_to="capture-0002", switch_below=1.0)
    o.party[1]["hp"] = 10
    assert s.battle_plan(o) is None


def test_unknown_structured_battle_conditions_are_not_silently_ignored():
    value = plan(obs()).model_dump()
    value["lines"][0]["strategy"]["switch_if"] = "recipient is healthy"
    with pytest.raises(ValueError):
        TeamPlan.model_validate(value)


def test_system4_battle_entry_exception_does_not_authorize_training_over_cap():
    o = obs()
    o.party[0]["level"] = 44
    o.in_battle = True
    System4.validate(plan(o), o, 43)
    o.in_battle = False
    with pytest.raises(LeadRotationError, match="cap"):
        System4.validate(plan(o), o, 43)


def test_battle_review_preserves_preparation_intent_for_postbattle_review():
    s = System4()
    o = obs()
    job(s, o)
    r = loop()
    intended = deepcopy(s.state["job"]["plan"])
    intended["levels"]["capture-0001"] = 43
    s.state["job"].update(preparation_plan=intended, review_after_battle=True)
    s.state["in_battle"] = True
    s.observe(o, r)
    assert s.state["job"]["phase"] == "review"
    assert s.state["job"]["plan"]["levels"]["capture-0001"] == 43


def test_dead_storage_finishes_verification_when_no_dead_member_remains():
    from nuzlocke.agents.preparation import preparation_turn

    o = obs()
    o.party[0]["dead"] = True
    r = loop()
    r.storage = StorageController()
    r._closing_preparation = False
    r.storage.turn(o, ["capture-0002"], Mock())
    removed = o.party.pop(0)
    removed["box"] = 1
    o.storage["boxes"][0]["members"].append(removed)
    o.screen_rows = [" " * 20] * 12 + [
        "┌──────────────────┐",
        "│                  │",
        "│Stored in BOX 1.  │",
        "│                  │",
        "│                  │",
        "└──────────────────┘",
    ]
    assert preparation_turn(r, o)[0] == [A.PRESS_B]
    assert r.storage.pending is None and r.storage.closing


def test_each_selected_member_needs_a_structured_battle_line():
    o = obs()
    p = plan(o)
    p.lines = p.lines[:1]
    with pytest.raises(LeadRotationError, match="omitted battle lines"):
        System4.validate(p, o, 43)
