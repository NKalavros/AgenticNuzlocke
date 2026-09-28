"""Dual mode uses Jev; the cursor provider still calls the overworld LLM."""

from __future__ import annotations

from types import SimpleNamespace

from nuzlocke.agents.roles import make_task, propose_plan
from nuzlocke.llm.base import LLMProvider
from nuzlocke.orchestration.loop import RunLoop
from nuzlocke.state.models import (
    ActionProposal,
    AgentRole,
    DirectorDecision,
    GameAction,
    GameMode,
    LLMResponse,
    PlanCard,
    PlanScene,
    PlayerObservation,
    RecoveryAdvice,
)


class _Planner(LLMProvider):
    name = "planner"

    def complete(self, *, role, system, user, schema_hint=None, image_paths=None):
        return LLMResponse(
            role=role,
            raw_text="{}",
            parsed={
                "scene": "dialog",
                "see": "Oak is talking",
                "plan": "advance the text, then leave the lab",
                "do_not": ["press A on Oak"],
                "objectives": {"primary": "Leave Oak's Lab"},
            },
            model="fake",
            provider=self.name,
        )


def _no_facts() -> dict:
    return {}


def _decision() -> DirectorDecision:
    return DirectorDecision(
        mode=GameMode.OVERWORLD,
        owner=AgentRole.OVERWORLD,
        objective="go north",
    )


def _obs() -> PlayerObservation:
    return PlayerObservation(
        map_name="Pallet Town",
        x=1,
        y=2,
        party=[{"name": "Bulbasaur"}],
        raw_player={"name": "RED"},
    )


def _proposal(reason: str) -> ActionProposal:
    return ActionProposal(
        task_id="t",
        agent=AgentRole.OVERWORLD,
        reason=reason,
        actions=[GameAction.WALK_UP],
    )


def test_propose_plan_reads_the_card():
    card = propose_plan(_Planner(), obs=_obs(), vision_only=True, objective="go north")
    assert card.scene == PlanScene.DIALOG
    assert card.see == "Oak is talking"
    assert "leave the lab" in card.plan
    assert card.do_not == ["press A on Oak"]
    assert card.objectives is not None
    assert card.objectives.primary == "Leave Oak's Lab"


def test_cursor_path_calls_overworld(monkeypatch):
    loop = RunLoop.__new__(RunLoop)
    loop.jev = None
    loop.llm = _Planner()
    loop.vision_only = True
    loop.objectives = {}
    loop.stuck = SimpleNamespace(loop_streak=0)
    loop._nuzlocke_state = _no_facts
    seen: dict[str, object] = {}

    def fake_overworld(llm, **kwargs):
        seen["llm"] = llm
        return _proposal("overworld")

    monkeypatch.setattr("nuzlocke.orchestration.loop.propose_overworld", fake_overworld)
    proposal, used, pause = loop._select_proposal(
        tier=0,
        decision=_decision(),
        task=make_task(_decision()),
        obs=_obs(),
        steps=1,
        memory_text=None,
        recent_ctx=[],
        walkthrough_hint=None,
        failed_approaches=None,
        no_progress_ctx=None,
    )
    assert seen["llm"] is loop.llm
    assert proposal is not None
    assert proposal.reason == "overworld"
    assert used is False
    assert pause is False


def test_dual_branch_calls_fast_actor_not_overworld(monkeypatch):
    loop = RunLoop.__new__(RunLoop)
    loop.jev = object()
    sentinel = _proposal("jev")

    def fake_fast(**kwargs):
        return sentinel

    def boom(*args, **kwargs):
        raise AssertionError("vision role should not run on the fast path")

    loop._fast_proposal = fake_fast  # type: ignore[method-assign]
    monkeypatch.setattr("nuzlocke.orchestration.loop.propose_overworld", boom)
    monkeypatch.setattr("nuzlocke.orchestration.loop.propose_battle", boom)
    proposal, used, pause = loop._select_proposal(
        tier=0,
        decision=_decision(),
        task=make_task(_decision()),
        obs=_obs(),
        steps=1,
        memory_text=None,
        recent_ctx=[],
        walkthrough_hint=None,
        failed_approaches=None,
        no_progress_ctx=None,
    )
    assert proposal is sentinel
    assert used is False
    assert pause is False


def test_disengage_drops_the_plan():
    loop = RunLoop.__new__(RunLoop)
    loop.jev = object()
    loop.plan = PlanCard(scene=PlanScene.OVERWORLD, see="stuck", plan="talk to oak")
    loop._last_recovery_step = -1
    loop.arbiter = SimpleNamespace(set_owner=lambda owner: None)
    loop._disengage_proposal = lambda task, tier: _proposal("disengage")  # type: ignore[method-assign]
    proposal, used, pause = loop._select_proposal(
        tier=2,
        decision=_decision(),
        task=make_task(_decision()),
        obs=_obs(),
        steps=4,
        memory_text=None,
        recent_ctx=[],
        walkthrough_hint=None,
        failed_approaches=None,
        no_progress_ctx=None,
    )
    assert loop.plan is None
    assert proposal is not None
    assert proposal.reason == "disengage"
    assert used is True
    assert pause is False


def test_recovery_advice_becomes_the_plan(monkeypatch):
    loop = RunLoop.__new__(RunLoop)
    loop.jev = object()
    loop.llm = object()
    loop.vision_only = True
    loop.objectives = {}
    loop.plan = None
    loop._low_confidence_streak = 4
    loop._prev_world = None
    loop._prev_dialog = None
    loop._last_recovery_step = -1
    loop._nuzlocke_state = _no_facts
    loop.stuck = SimpleNamespace(stuck_score=6, recent_positions=[], loop_streak=0)
    loop.env = SimpleNamespace(push_event=lambda *a, **k: None, set_control=lambda *a, **k: None)
    loop.store = SimpleNamespace(append=lambda *a, **k: None)
    loop.arbiter = SimpleNamespace(set_owner=lambda owner: None)

    def fake_recovery(llm, **kwargs):
        return RecoveryAdvice(
            diagnosis="Oak is repeating himself",
            reason="leave the lab north",
            proposed_actions=[GameAction.PRESS_B],
        )

    monkeypatch.setattr("nuzlocke.orchestration.loop.advise_recovery", fake_recovery)
    proposal, used, pause = loop._select_proposal(
        tier=3,
        decision=_decision(),
        task=make_task(_decision()),
        obs=_obs(),
        steps=3,
        memory_text=None,
        recent_ctx=[],
        walkthrough_hint=None,
        failed_approaches=None,
        no_progress_ctx=None,
    )
    assert used is True
    assert pause is False
    assert proposal is not None
    assert proposal.actions == [GameAction.PRESS_B]
    assert loop.plan is not None
    assert loop.plan.plan == "leave the lab north"
    assert loop._low_confidence_streak == 0
