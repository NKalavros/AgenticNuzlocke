"""Director routing stays deterministic (no LLM on stuck/noop)."""

from __future__ import annotations

from pathlib import Path

from nuzlocke.agents.roles import decide_director
from nuzlocke.llm.base import LLMProvider
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
        return LLMResponse(
            role=role,
            raw_text="{}",
            parsed={},
            model="fake",
            provider=self.name,
        )


def test_director_stuck_routes_recovery_without_llm():
    llm = CountingLLM()
    obs = PlayerObservation(
        map_name="Pallet Town",
        x=5,
        y=6,
        party=[{"name": "Bulbasaur"}],
        raw_player={"name": "RED"},
    )
    decision = decide_director(
        llm,
        summary={"stuck_score": 6, "noop_streak": 0},
        obs=obs,
    )
    assert decision.mode == GameMode.RECOVERY
    assert decision.owner == AgentRole.RECOVERY
    assert llm.calls == 0


def test_director_noop_routes_recovery_without_llm():
    llm = CountingLLM()
    obs = PlayerObservation(
        map_name="Pallet Town",
        x=5,
        y=6,
        party=[{"name": "Bulbasaur"}],
        raw_player={"name": "RED"},
    )
    decision = decide_director(
        llm,
        summary={"stuck_score": 1, "noop_streak": 2},
        obs=obs,
    )
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
    obs = PlayerObservation(
        map_name="Pallet Town",
        x=5,
        y=6,
        party=[{"name": "Bulbasaur"}],
        raw_player={"name": "RED"},
    )
    decision = decide_director(llm, summary={"stuck_score": 0, "noop_streak": 0}, obs=obs)
    assert decision.mode == GameMode.OVERWORLD
    assert decision.owner == AgentRole.OVERWORLD
    assert llm.calls == 0
