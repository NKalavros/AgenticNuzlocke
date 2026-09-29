"""Director routing stays deterministic (no LLM on stuck/noop)."""

from __future__ import annotations

from pathlib import Path

import pytest

from nuzlocke.agents.roles import decide_director
from nuzlocke.llm.base import LLMProvider
from nuzlocke.orchestration.stuck import LOOP_RECOVERY, NOOP_RECOVERY, STUCK_RECOVERY
from nuzlocke.state.models import AgentRole, GameMode, LLMResponse, PlayerObservation


class CountingLLM(LLMProvider):
    name = "counting"

    def __init__(self) -> None:
        self.calls = 0

    def complete(
        self,
        *,
        role: AgentRole,
        system: str,
        user: str,
        schema_hint: dict | None = None,
        image_paths: list[Path] | None = None,
    ) -> LLMResponse:
        self.calls += 1
        return LLMResponse(role=role, raw_text="{}", parsed={}, model="fake", provider=self.name)


PALLET = {"map_name": "Pallet Town", "x": 5, "y": 6, "party": [{"name": "Bulbasaur"}]}
ROUTE_1 = {"map_name": "Route 1", "x": 10, "y": 2, "party": [{"name": "Squirtle"}]}


@pytest.mark.parametrize(
    ("where", "summary"),
    [
        (PALLET, {"stuck_score": STUCK_RECOVERY, "noop_streak": 0}),
        (PALLET, {"stuck_score": 1, "noop_streak": NOOP_RECOVERY}),
        (ROUTE_1, {"stuck_score": 1, "noop_streak": 0, "loop_streak": LOOP_RECOVERY}),
    ],
    ids=["stuck", "noop", "loop"],
)
def test_director_stuck_routes_recovery_without_llm(where, summary):
    llm = CountingLLM()
    obs = PlayerObservation(**where, raw_player={"name": "RED"})
    decision = decide_director(llm, summary=summary, obs=obs)
    assert decision.mode == GameMode.RECOVERY
    assert decision.owner == AgentRole.RECOVERY
    assert llm.calls == 0


def test_director_battle_without_llm():
    llm = CountingLLM()
    obs = PlayerObservation(in_battle=True, battle={"in_battle": True, "type": "wild"})
    decision = decide_director(llm, summary={"stuck_score": 0}, obs=obs)
    assert decision.mode == GameMode.BATTLE
    assert decision.owner == AgentRole.BATTLE
    assert llm.calls == 0


def test_director_overworld_without_llm():
    llm = CountingLLM()
    obs = PlayerObservation(**PALLET, raw_player={"name": "RED"})
    decision = decide_director(llm, summary={"stuck_score": 0, "noop_streak": 0}, obs=obs)
    assert decision.mode == GameMode.OVERWORLD
    assert decision.owner == AgentRole.OVERWORLD
    assert "Route 1" in decision.objective
    assert "Pewter" not in decision.objective
    assert llm.calls == 0


def test_director_pallet_without_a_party_goes_north_not_to_pewter():
    llm = CountingLLM()
    obs = PlayerObservation(map_name="Pallet Town", x=8, y=16, raw_player={"name": "RED"})
    decision = decide_director(llm, summary={"stuck_score": 0}, obs=obs, vision_only=True)
    assert "north" in decision.objective.lower()
    assert "water" in decision.objective.lower()
    assert "Pewter" not in decision.objective
    assert llm.calls == 0


def test_speech_on_screen_ignores_the_house_map():
    llm = CountingLLM()
    obs = PlayerObservation(map_name="Red's House 2F", x=3, y=6, raw_player={"name": "RED"})
    decision = decide_director(llm, summary={"stuck_score": 0}, obs=obs, speech=True)
    assert "speaking" in decision.objective
    assert "Pewter" not in decision.objective
    assert llm.calls == 0
