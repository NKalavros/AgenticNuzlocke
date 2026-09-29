from nuzlocke.orchestration.fallback import (
    bridge_down_proposal,
    is_bridge_down,
    llm_error_fallback_proposal,
)
from nuzlocke.state.models import AgentRole, GameAction, TaskEnvelope


def _task(owner: AgentRole) -> TaskEnvelope:
    return TaskEnvelope(task_id="t1", owner=owner, objective="go")


def test_is_bridge_down_detects_connection_refused():
    assert is_bridge_down(RuntimeError("Connection refused")) is True


def test_is_bridge_down_false_for_unrelated_error():
    assert is_bridge_down(RuntimeError("invalid schema")) is False


def test_bridge_down_proposal_waits_and_keeps_owner():
    proposal = bridge_down_proposal(_task(AgentRole.BATTLE))
    assert proposal.agent == AgentRole.BATTLE
    assert proposal.actions == [GameAction.WAIT_60]


def test_bridge_down_proposal_falls_back_to_overworld_for_unknown_owner():
    proposal = bridge_down_proposal(_task(AgentRole.DIRECTOR))
    assert proposal.agent == AgentRole.OVERWORLD


def test_llm_error_fallback_battle_presses_a():
    proposal = llm_error_fallback_proposal(_task(AgentRole.BATTLE))
    assert proposal.agent == AgentRole.BATTLE
    assert proposal.actions == [GameAction.PRESS_A]


def test_llm_error_fallback_overworld_mashes_dialog():
    proposal = llm_error_fallback_proposal(_task(AgentRole.OVERWORLD))
    assert proposal.agent == AgentRole.OVERWORLD
    assert GameAction.WAIT_60 in proposal.actions
    # B taps, each a new press. No A: it would re-open whoever the player faces.
    assert GameAction.PRESS_A not in proposal.actions
    assert GameAction.HOLD_B_120 not in proposal.actions
