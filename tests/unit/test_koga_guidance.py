"""Koga prerequisites, Surf evidence gates, and final preparation contracts."""

from unittest.mock import Mock

import pytest

from nuzlocke.agents.gym_preparation import GymPreparation, gym_beat, leader_position
from nuzlocke.agents.policy import decision
from nuzlocke.agents.system3 import constraints, heal_beat, objective_window
from nuzlocke.environment.maps import map_id_for_name, map_name
from nuzlocke.knowledge.map_reference import atlas, shortest_path
from nuzlocke.knowledge.trainers import next_boss
from nuzlocke.knowledge.walkthrough import excerpt_for_context, koga_stage, progression_hint, surf_stage
from nuzlocke.orchestration.objectives import progression_objectives
from nuzlocke.state.models import GameAction as A
from nuzlocke.state.models import PlayerObservation as O

BADGES = ["Boulder", "Cascade", "Thunder", "Rainbow"]


def obs(**kwargs):
    return O(badges=BADGES.copy(), map_id=6, **kwargs)


def test_koga_prerequisites_follow_inventory_and_do_not_trust_reward_prose():
    o = obs()
    assert koga_stage(o) == "rocket_entry"
    assert "poster" in progression_objectives(o)["primary"]
    o.map_id = 202
    assert koga_stage(o) == "rocket_key"
    o.bag = [{"id": 74, "item": "Lift Key", "quantity": 0}]
    assert koga_stage(o) == "rocket_key"
    o.bag[0]["quantity"] = 1
    assert koga_stage(o) == "rocket_scope"
    assert "Giovanni" in progression_objectives(o)["primary"]
    o.bag += [{"id": 72, "item": "Silph Scope", "quantity": 1}]
    assert koga_stage(o) == "tower"
    o.map_id = 149
    assert "Mr. Fuji" in progression_objectives(o)["primary"]
    assert koga_stage(o) == "tower"  # House transfer alone does not prove receipt.
    o.bag += [{"item": "Poké Flute", "quantity": 1}]
    assert koga_stage(o) == "fuchsia_route"
    assert "Route 12" in progression_objectives(o)["primary"]
    o.map_id = 7
    assert koga_stage(o) == "fuchsia"
    o.map_id = 157
    assert koga_stage(o) == "gym"
    assert "(4,11)" in progression_objectives(o)["primary"]
    o.badges.append("Soul")
    assert koga_stage(o) is None
    assert progression_objectives(o) is None
    assert not progression_hint(o)
    assert "Koga —" not in excerpt_for_context(map_name="Fuchsia Gym", reason="find Koga", obs=o, max_chars=8000)


@pytest.mark.parametrize(
    "mid,stage", [(7, "fuchsia"), (154, "fuchsia"), (157, "gym"), (24, "fuchsia_route"), (184, "fuchsia_route")]
)
def test_observed_access_does_not_force_recollection_of_story_keys(mid, stage):
    o = obs()
    o.map_id = mid
    assert koga_stage(o) == stage
    o.in_battle = True
    assert progression_objectives(o) is None and not progression_hint(o)
    o.badges = BADGES[:-1]
    assert koga_stage(o) is None


def test_surf_requires_observed_hm_or_living_learned_move_and_soul_for_field_use():
    o = obs()
    o.map_id = 7
    assert surf_stage(o) is None and "Surf:" not in progression_hint(o)
    text = excerpt_for_context(map_name="Fuchsia City", reason="please use surf", memory="HM03 acquired", obs=o, max_chars=8000)
    assert "Surf:" not in text and "Koga" in text
    o.bag = [{"id": 198, "item": "HM03", "quantity": 0}]
    assert surf_stage(o) is None
    o.bag[0]["quantity"] = 1
    assert surf_stage(o) == "teach"
    assert "ABLE" in progression_hint(o) and "Koga" in progression_hint(o)
    o.bag = []
    o.party = [{"hp": 30, "moves": [{"id": 57, "name": "Surf"}]}]
    assert surf_stage(o) == "locked"
    assert "field permission still locked" in progression_hint(o)
    o.badges.append("Soul")
    assert surf_stage(o) == "field" and "face the water" in progression_hint(o)
    o.party[0]["dead"] = True
    assert surf_stage(o) is None and not progression_hint(o)
    o.party[0]["dead"], o.party[0]["hp"] = False, 0
    assert surf_stage(o) is None
    o.bag = [{"item": "HM_03", "quantity": 1}]
    assert surf_stage(o) == "teach"


def test_conditional_surf_guidance_keeps_earlier_chapter_and_never_adds_objectives():
    o = obs(bag=[{"id": 198, "quantity": 1}])
    o.badges = BADGES[:-1]
    assert "Post-Thunder" in progression_hint(o) and "Surf:" in progression_hint(o)
    assert "Erika" in progression_objectives(o)["tertiary"]


def test_route16_arrival_does_not_prove_the_snorlax_gate_is_passed():
    o = obs()
    o.map_id = 27
    assert koga_stage(o) == "rocket_entry"
    o.map_id = 28
    assert koga_stage(o) == "fuchsia_route"


def test_koga_preparation_persists_heal_candy_challenge_and_requires_observed_badge():
    o = obs(party=[{"hp": 90, "max_hp": 90, "status": "OK", "level": 30}], policy={"level_cap": 43})
    o.map_id, o.x, o.y = 157, 4, 11
    preparation, record = GymPreparation(), Mock()
    preparation.observe(o, cap=43, candy_enabled=True, record=record)
    assert preparation.pending["phase"] == "heal"
    assert "Heal" in objective_window(o)["primary"] and "43" in objective_window(o)["secondary"]
    assert decision(o).validate([A.PRESS_A]) is not None
    assert decision(o).validate([A.WALK_DOWN]) is None
    restored = GymPreparation()
    restored.restore(preparation.snapshot())
    o.map_id = 154
    restored.observe(o, cap=43, candy_enabled=True, record=record)
    assert heal_beat(o).id == "heal_nurse"
    assert restored.pending["phase"] == "heal"  # Full HP alone cannot skip the nurse.
    restored.pending["accepted"] = True
    restored.observe(o, cap=43, candy_enabled=True, record=record)
    assert restored.pending["phase"] == "prepare" and gym_beat(o).id == "prepare_gym"
    o.party[0]["level"] = 43
    restored.observe(o, cap=43, candy_enabled=True, record=record)
    assert restored.pending["phase"] == "challenge"
    o.map_id = 157
    restored.annotate(o)
    assert gym_beat(o).target == {"kind": "face", "x": 4, "y": 11, "dir": "up"}
    o.badges.append("Soul")
    restored.observe(o, cap=43, candy_enabled=True, record=record)
    assert restored.pending is None and leader_position(157, o.badges) is None


@pytest.mark.parametrize("mid", [7, 154, 157])
def test_koga_preparation_starts_before_the_high_level_maze_trainers(mid):
    o = obs(party=[{"hp": 90, "max_hp": 90, "status": "OK", "level": 30}])
    o.map_id, o.x, o.y = mid, 4, 16
    preparation = GymPreparation()
    preparation.observe(o, cap=43, candy_enabled=True, record=Mock())
    assert preparation.pending["phase"] == "heal" and preparation.pending["cap"] == 43
    assert "Heal" in objective_window(o)["primary"]
    preparation = GymPreparation()
    o.badges = BADGES[:-1]
    preparation.observe(o, cap=29, candy_enabled=True, record=Mock())
    assert preparation.pending is None


def test_koga_map_names_and_reference_maze_match_primary_data():
    for mid, name in [(142, "Pokemon Tower 1F"), (154, "Fuchsia Pokecenter"), (157, "Fuchsia Gym"), (202, "Rocket Hideout B4F")]:
        assert map_name(mid) == name and map_id_for_name(name) == mid
    o = obs()
    o.map_id, o.x, o.y = 157, 4, 16
    path = shortest_path(o, [(4, 11)], blocked={(4, 11, "up")})
    assert path and path[-1] == (4, 11)
    rows = atlas()["maps"]["157"]["rows"]
    assert all(rows[y][x] == "." for x, y in path)
    assert len(path) > 6  # Invisible walls prohibit the straight north path.
    assert "Weezing L43" in next_boss(4)


def test_center_recovery_briefing_reports_only_actual_living_hp_status_and_observed_pp():
    o = obs(party=[{"hp": 90, "max_hp": 90, "status": "OK", "moves": [{"pp": 20, "observed_max_pp": 20}]}])
    o.map_id = 133
    assert "Observed party recovery" in " ".join(constraints(o, 43, []))
    o.policy["gym_heal_pending"] = True
    assert "mandatory nurse-acceptance" in " ".join(constraints(o, 43, []))
    assert heal_beat(o).id == "heal_nurse"
    for delta in ({"hp": 89}, {"status": "PSN"}, {"moves": [{"pp": 19, "observed_max_pp": 20}]}):
        baseline = o.party[0].copy()
        o.party[0].update(delta)
        assert "Observed party recovery" not in " ".join(constraints(o, 43, []))
        o.party[0] = baseline
