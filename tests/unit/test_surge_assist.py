"""Surge assistance reads the current puzzle and keeps normal movement/safety."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from nuzlocke.agents.goals import RoomMap, build_goals
from nuzlocke.agents.navigation import Navigator
from nuzlocke.agents.system1 import system1_turn
from nuzlocke.environment import surge
from nuzlocke.environment.screen_text import parse_screen
from nuzlocke.knowledge.surge import switch_objective
from nuzlocke.knowledge.walkthrough import progression_hint
from nuzlocke.orchestration.loop import RunLoop
from nuzlocke.referee.rules import NuzlockeReferee
from nuzlocke.state.models import GameAction, PlanCard, PlanScene, PlayerObservation


def test_ram_phase_uses_fresh_second_index_including_nonadjacent_zero(monkeypatch):
    monkeypatch.setattr(surge, "supported_rom", lambda path: path == "verified.gb")
    memory = {0xD35E: 92, 0xD369: 5, 0xD368: 9, 0xD743: 14, 0xD744: 255, 0xD773: 0x18}
    emu = SimpleNamespace(rom_path="verified.gb", read_u8=lambda addr: memory.get(addr, 0))
    assert surge.read_surge_puzzle(emu) == {"phase": "first", "index": 14, "x": 9, "y": 11, "source": "RAM assist"}
    memory[0xD773], memory[0xD744] = 0x1A, 0
    assert surge.read_surge_puzzle(emu) == {"phase": "second", "index": 0, "x": 1, "y": 7, "source": "RAM assist"}
    memory[0xD773], memory[0xD743] = 0x18, 4  # Wrong choice resets and selects a new first can.
    assert surge.read_surge_puzzle(emu)["index"] == 4
    memory[0xD773] = 0x1B
    assert surge.read_surge_puzzle(emu)["phase"] == "open"
    memory[0xD773], memory[0xD743] = 0x18, 15
    assert surge.read_surge_puzzle(emu) is None
    memory[0xD743], memory[0xD35E] = 4, 5
    assert surge.read_surge_puzzle(emu) is None
    memory[0xD773] = 0x1B
    assert surge.read_surge_puzzle(emu) == {"phase": "open", "source": "RAM assist"}
    memory[0xD35E] = 89
    assert surge.read_surge_puzzle(emu) == {"phase": "open", "source": "RAM assist"}
    memory[0xD35E], emu.rom_path = 92, "unknown.gb"
    assert surge.read_surge_puzzle(emu) is None
    emu.rom_path, memory[0xD369] = "verified.gb", 6
    assert surge.read_surge_puzzle(emu) is None


def setup():
    loop = RunLoop.__new__(RunLoop)
    loop.referee = NuzlockeReferee({})
    loop.referee.advance(2)
    loop.run_cfg = {"milestones": [], "surge_puzzle_assist": True}
    loop._encounter_tables, loop._encounter_search_counts, loop._grass_visits = {}, {}, {}
    loop.navigator, loop.room = Navigator(), RoomMap()
    loop._beat_locked, loop._beat_id, loop.plan = False, None, None
    loop.env, loop.store = Mock(), Mock()
    loop._cycle = 1
    obs = PlayerObservation(
        map_id=92,
        map_name="Vermilion Gym",
        x=3,
        y=12,
        raw_player={"name": "RED"},
        badges=["Boulder", "Cascade"],
        flags={"has_pokedex": True},
        party=[{"species": "Beedrill", "hp": 60, "max_hp": 60, "status": "OK", "moves": [{"name": "Cut"}]}],
        surge_puzzle={"phase": "first", "index": 4, "x": 3, "y": 9, "source": "RAM assist"},
    )
    loop.room.known[92] = {(x, y): x % 2 == 0 or y % 2 == 0 for x in range(10) for y in range(6, 14)}
    return loop, obs


@pytest.mark.parametrize("reason", ["disabled", "healing", "battle", "beat", "badge", "other_map", "no_data"])
def test_assistance_is_narrow_and_defers_to_safety(reason):
    loop, obs = setup()
    beat = None
    if reason == "disabled":
        loop.run_cfg["surge_puzzle_assist"] = False
    elif reason == "healing":
        obs.party[0]["status"] = "PAR"
    elif reason == "battle":
        obs.in_battle = True
    elif reason == "beat":
        beat = SimpleNamespace(id="box_dead")
    elif reason == "badge":
        obs.badges.append("Thunder")
    elif reason == "other_map":
        obs.map_id = 5
    elif reason == "no_data":
        obs.surge_puzzle = None
    assert switch_objective(loop, obs, beat) is None
    assert not obs.policy["surge_switch_assist"]


def test_routes_execute_without_random_choices_and_retire_after_unlock():
    loop, obs = setup()
    loop.plan = PlanCard(scene=PlanScene.OVERWORLD, see="cans", plan="Search a random can")
    assert "RAM assist" in loop._sync_beats(obs, controllable=True)
    assert loop.plan is None and loop._beat_locked
    target, text, owned = loop._objective(obs)
    assert target["kind"] == "face" and owned
    goal = next(g for g in build_goals(obs, loop.room, objective=target) if g.objective)
    assert goal.path and goal.actions[-1] == GameAction.PRESS_A
    turn = system1_turn(
        obs=obs,
        screen=parse_screen([]),
        text_box=False,
        mash_stalled=False,
        room=loop.room,
        objective=target,
        objective_text=text,
        objective_from_code=owned,
        heading=None,
        fails={},
        last_direction=None,
        low_confidence_streak=0,
        confidence_floor=0.55,
        stale_noul=0.7,
        journal=[],
        constraints=[],
        jev_decide=Mock(side_effect=AssertionError("No random selection needed")),
        navigator=loop.navigator,
    )
    assert turn.actions and not turn.trigger
    obs.surge_puzzle = {"phase": "second", "index": 0, "x": 1, "y": 7, "source": "RAM assist"}
    loop._sync_beats(obs, controllable=True)
    assert "second" in loop.objectives["primary"] and "(1,7)" in loop._objective(obs)[1]
    loop.plan = PlanCard(scene=PlanScene.OVERWORLD, see="cans", plan="Keep searching")
    obs.surge_puzzle = {"phase": "open", "source": "RAM assist"}
    loop._sync_beats(obs, controllable=True)
    assert not loop._beat_locked and loop.plan is None
    assert "Verify the passage" in loop.objectives["primary"]
    assert "Stop searching cans" in progression_hint(obs)
    assert "Thunder" not in obs.badges


def test_assistance_retires_for_mandatory_healing():
    loop, obs = setup()
    loop._sync_beats(obs, controllable=True)
    obs.party[0]["status"] = "PAR"
    loop._sync_beats(obs, controllable=True)
    assert loop._beat_id.startswith("heal") and "Heal" in loop.objectives["primary"]
    loop._objective(obs)
    assert not obs.policy["surge_switch_assist"]
