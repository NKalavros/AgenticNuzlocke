"""Fallback action proposals used when an LLM role call fails."""

from __future__ import annotations

from nuzlocke.state.models import ActionProposal, AgentRole, GameAction, TaskEnvelope


def is_bridge_down(err: BaseException) -> bool:
    text = str(err).lower()
    return any(s in text for s in ("connection refused", "connecterror", "bridge request failed"))


def bridge_down_proposal(task: TaskEnvelope) -> ActionProposal:
    """Cursor SDK bridge unreachable — wait rather than guess."""
    agent = AgentRole.OVERWORLD if task.owner == AgentRole.DIRECTOR else task.owner
    return ActionProposal(
        task_id=task.task_id,
        agent=agent,
        reason="wait — Cursor bridge unavailable",
        actions=[GameAction.WAIT_60],
    )


def llm_error_fallback_proposal(task: TaskEnvelope) -> ActionProposal:
    """Generic LLM failure — safe macro so the run keeps going."""
    if task.owner == AgentRole.BATTLE:
        agent, actions = AgentRole.BATTLE, [GameAction.PRESS_A]
    else:
        # B-only: this runs blind, and an A while facing an NPC re-opens the dialogue it just
        # cleared. Taps, not a hold: each press_b ends with released frames, so each is a new press.
        agent, actions = AgentRole.OVERWORLD, [GameAction.PRESS_B] * 3 + [GameAction.WAIT_60]
    return ActionProposal(
        task_id=task.task_id, agent=agent, reason="fallback after LLM failure", actions=actions
    )
