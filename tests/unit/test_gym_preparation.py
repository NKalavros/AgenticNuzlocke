from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from nuzlocke.agents.goals import RoomMap, build_goals
from nuzlocke.agents.gym_preparation import GymPreparation, at_leader, gym_beat, needs_top_up
from nuzlocke.agents.policy import decision
from nuzlocke.agents.preparation import preparation_turn
from nuzlocke.environment import pa_serve
from nuzlocke.state.models import GameAction as A
from nuzlocke.state.models import PlayerObservation as O


def mon(level):
    return {"species": "Pidgeotto", "nickname": "PIDGEOTTO", "level": level, "hp": 50, "max_hp": 50, "status": "OK"}


def obs():
    return O(
        map_id=65,
        x=4,
        y=3,
        badges=["Boulder"],
        battle_style="SET",
        party=[mon(19), mon(20), mon(21), {**mon(22), "ineligible": True}],
        policy={"level_cap": 21},
    )


def loop():
    return SimpleNamespace(
        run_cfg={"rare_candy": {"enabled": True}, "level_cap_buffer": 1},
        referee=SimpleNamespace(current_cap=21),
        _preparing_target=None,
        _closing_preparation=False,
        store=Mock(),
        env=Mock(),
    )


def test_final_top_up_bypasses_travel_buffer_for_every_underlevelled_member():
    o, runner = obs(), loop()
    assert at_leader(o) and needs_top_up(o)
    assert decision(o).validate([A.PRESS_A]) is not None
    actions, _ = preparation_turn(runner, o)
    assert actions == [A.PRESS_START, A.WAIT_60]
    runner.env._post_json.assert_called_once_with("/nuzlocke/prepare", {"target": 21})
    assert runner._preparing_target == 21
    assert decision(o).validate(actions) is None
    o.party[0]["level"] = 21
    assert needs_top_up(o)  # Second member still needs a candy.
    o.party[1]["level"] = 21
    assert not needs_top_up(o)
    assert preparation_turn(runner, o)[0] == [A.PRESS_B]
    assert runner._preparing_target is None
    assert o.party[-1]["ineligible"]  # Existing over-cap member is not made legal.


def test_no_final_grant_early_in_gym_or_to_unhealthy_party():
    o, runner = obs(), loop()
    o.y = 10
    assert not at_leader(o)
    preparation_turn(runner, o)
    runner.env._post_json.assert_not_called()
    o.y = 3
    o.party[0]["hp"] = 20
    preparation_turn(runner, o)
    runner.env._post_json.assert_not_called()
    o.party[0]["hp"] = 50
    runner.run_cfg["rare_candy"]["enabled"] = False
    with pytest.raises(RuntimeError, match="requires party at the cap"):
        preparation_turn(runner, o)


def test_leader_path_stops_before_interaction_until_team_is_ready():
    o = obs()
    o.y = 4
    room = RoomMap()
    room.visited[65] = {(4, 3), (4, 4)}
    target = {"kind": "face", "x": 4, "y": 3, "dir": "up"}
    goals = build_goals(o, room, objective=target)
    goal = next(g for g in goals if g.objective)
    assert A.PRESS_A not in goal.actions
    assert goal.finish is None
    for m in o.party:
        m["level"] = 21
    goal = next(g for g in build_goals(o, room, objective=target) if g.objective)
    assert goal.finish == A.PRESS_A


@pytest.mark.parametrize(
    "mid,badges,x,y,target", [(54, 0, 4, 2, 14), (65, 1, 4, 3, 21), (92, 3, 5, 2, 24), (134, 7, 4, 4, 29), (157, 15, 4, 11, 43)]
)
def test_endpoint_allows_exact_healthy_leader_deficit_only(mid, badges, x, y, target):
    mem = bytearray(65536)
    mem[pa_serve.W_CUR_MAP], mem[0xD356] = mid, badges
    mem[pa_serve.W_X_COORD], mem[pa_serve.W_Y_COORD] = x, y
    emu = SimpleNamespace(_pyboy=SimpleNamespace(memory=mem), read_u8=lambda a: mem[a], read_range=lambda a, n: mem[a : a + n])
    party = [mon(target - 2), mon(target - 1), mon(target)]
    reader = SimpleNamespace(emu=emu, read_party=lambda: party)
    assert pa_serve.prepare_items(reader, {"target": target})["granted"] == 3
    assert pa_serve.prepare_items(reader, {"target": target})["granted"] == 0
    with pytest.raises(ValueError):
        pa_serve.prepare_items(reader, {"target": target + 1})
    mem[pa_serve.W_Y_COORD] += 1
    with pytest.raises(ValueError):
        pa_serve.prepare_items(reader, {"target": target})
    mem[pa_serve.W_Y_COORD] = y
    mem[0xD356] |= {54: 1, 65: 2, 92: 4, 134: 8, 157: 16}[mid]
    with pytest.raises(ValueError):
        pa_serve.prepare_items(reader, {"target": target})


def test_leader_gate_allows_leaving_to_heal_and_never_applies_mid_battle():
    o = obs()
    o.party[0]["hp"] = 10
    assert decision(o).validate([A.WALK_DOWN] * 4) is None
    assert decision(o).validate([A.PRESS_A]) is not None
    o.in_battle = True
    assert not at_leader(o)
    assert not decision(o).forbidden_actions


def surge_obs(**kwargs):
    return O(
        **{
            "map_id": 89,
            "x": 3,
            "y": 3,
            "badges": ["Boulder", "Cascade"],
            "battle_style": "SET",
            "party": [mon(21), mon(23)],
            "surge_puzzle": {"phase": "open"},
            **kwargs,
        }
    )


def observe(preparation, o):
    preparation.observe(o, cap=24, candy_enabled=True, record=Mock())


def test_persistent_gym_stages_require_nurse_acceptance_and_observed_recovery():
    from nuzlocke.agents.system3 import current_beat, objective_window

    o, runner = surge_obs(), loop()
    runner.referee.current_cap = 24
    runner.gym_preparation = preparation = GymPreparation()
    observe(preparation, o)
    assert preparation.pending["phase"] == "heal"
    assert current_beat(o).id == "heal_nurse"
    assert "Heal" in objective_window(o)["primary"]
    observe(preparation, o)  # Full HP alone does not skip the required visit.
    assert preparation.pending["phase"] == "heal"
    preparation_turn(runner, o)
    runner.env._post_json.assert_not_called()
    o.screen_rows = ["┌────────┐", "│▶HEAL   │", "│ CANCEL │", "└────────┘"]
    assert preparation_turn(runner, o)[1] == "accept healing"
    assert preparation.pending["accepted"]
    observe(preparation, o)  # A menu still on screen does not prove recovery.
    assert preparation.pending["phase"] == "heal"
    o.screen_rows = []
    o.party[0].update(moves=[{"name": "Gust", "pp": 34, "observed_max_pp": 35}])
    observe(preparation, o)
    assert preparation.pending["phase"] == "heal"
    o.party[0]["moves"][0]["pp"] = 35
    observe(preparation, o)
    assert gym_beat(o).id == "prepare_gym"
    assert "24" in objective_window(o)["primary"]
    preparation_turn(runner, o)
    runner.env._post_json.assert_called_once_with("/nuzlocke/prepare", {"target": 24})
    saved = preparation.snapshot()
    restored = GymPreparation()
    restored.restore(saved)
    restored.pending["accepted"] = False
    assert preparation.pending == saved  # No mutable alias to checkpoint history.
    for m in o.party:
        m["level"] = 24
    observe(restored, o)
    assert restored.pending["phase"] == "challenge"
    assert gym_beat(o).target == {"kind": "warp", "dest_map": 5}
    o.map_id, o.x, o.y = 92, 5, 2
    o.policy["preparing"] = False  # A fresh post-menu observation clears the candy latch.
    observe(restored, o)
    assert gym_beat(o).target == {"kind": "face", "x": 5, "y": 2, "dir": "up"}
    assert "Rare Candies" not in " ".join(objective_window(o).values())
    o.party[0]["hp"] -= 1
    observe(restored, o)
    assert restored.pending["phase"] == "heal"
    assert decision(o).validate([A.PRESS_A]) is not None
    assert decision(o).validate([A.WALK_DOWN]) is None
    o.badges.append("Thunder")
    observe(restored, o)
    assert restored.pending is None


@pytest.mark.parametrize("phase", [None, "first", "second"])
def test_surges_pending_prerequisites_do_not_start_final_preparation(phase):
    o = surge_obs(surge_puzzle={"phase": phase} if phase else None)
    preparation = GymPreparation()
    observe(preparation, o)
    assert preparation.pending is None


@pytest.mark.parametrize(
    "mid,badges,x,y,cap",
    [
        (54, [], 4, 2, 14),
        (65, ["Boulder"], 4, 3, 21),
        (92, ["Boulder", "Cascade"], 5, 2, 24),
        (134, ["Boulder", "Cascade", "Thunder"], 4, 4, 29),
    ],
)
def test_final_leader_tile_inserts_healing_even_with_assistance_disabled(mid, badges, x, y, cap):
    from nuzlocke.agents.system3 import current_beat

    o = O(map_id=mid, badges=badges, x=x, y=y, party=[mon(cap)], policy={"level_cap": cap})
    preparation = GymPreparation()
    preparation.observe(o, cap=cap, candy_enabled=True, record=Mock())
    assert preparation.pending["phase"] == "heal"
    assert current_beat(o).target == {"kind": "warp", "dest_map": 255}
    assert decision(o).validate([A.PRESS_A]) is not None
    o.in_battle = True
    assert current_beat(o) is None


def test_candy_grants_at_surge_center_use_real_badge_cap_and_do_not_heal():
    mem = bytearray(65536)
    mem[pa_serve.W_CUR_MAP], mem[0xD356] = 89, 3
    emu = SimpleNamespace(_pyboy=SimpleNamespace(memory=mem), read_u8=lambda a: mem[a], read_range=lambda a, n: mem[a : a + n])
    party = [mon(21), mon(23), mon(21), mon(23), mon(23), mon(23)]
    reader = SimpleNamespace(emu=emu, read_party=lambda: party)
    party[0]["hp"] -= 1
    with pytest.raises(ValueError, match="heal the whole party"):
        pa_serve.prepare_items(reader, {"target": 24})
    party[0]["hp"] += 1
    assert pa_serve.prepare_items(reader, {"target": 24})["granted"] == 10
    assert [m["level"] for m in party] == [21, 23, 21, 23, 23, 23]
    assert pa_serve.prepare_items(reader, {"target": 24})["granted"] == 0
    with pytest.raises(ValueError):
        pa_serve.prepare_items(reader, {"target": 25})
    mem[pa_serve.W_IS_IN_BATTLE] = 1
    with pytest.raises(ValueError, match="forbidden in battle"):
        pa_serve.prepare_items(reader, {"target": 24})
