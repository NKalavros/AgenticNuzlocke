from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from nuzlocke.agents.goals import RoomMap, build_goals
from nuzlocke.agents.gym_preparation import at_leader, needs_top_up
from nuzlocke.agents.policy import decision
from nuzlocke.agents.preparation import preparation_turn
from nuzlocke.environment import pa_serve
from nuzlocke.state.models import GameAction as A
from nuzlocke.state.models import PlayerObservation as O


def mon(level):
    return {
        "species": "Pidgeotto",
        "nickname": "PIDGEOTTO",
        "level": level,
        "hp": 50,
        "max_hp": 50,
        "status": "OK",
    }


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


@pytest.mark.parametrize("mid,badges,x,y,target", [(54, 0, 4, 2, 14), (65, 1, 4, 3, 21)])
def test_endpoint_allows_exact_healthy_leader_deficit_only(mid, badges, x, y, target):
    mem = bytearray(65536)
    mem[pa_serve.W_CUR_MAP], mem[0xD356] = mid, badges
    mem[pa_serve.W_X_COORD], mem[pa_serve.W_Y_COORD] = x, y
    emu = SimpleNamespace(
        _pyboy=SimpleNamespace(memory=mem),
        read_u8=lambda a: mem[a],
        read_range=lambda a, n: mem[a : a + n],
    )
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
    mem[0xD356] |= 1 if mid == 54 else 2
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
