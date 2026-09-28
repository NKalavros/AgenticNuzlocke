"""Fallback action proposals used when an LLM role call fails."""

from __future__ import annotations

from nuzlocke.state.models import ActionProposal, AgentRole, GameAction, TaskEnvelope


def is_bridge_down(err: BaseException) -> bool:
    text = str(err).lower()
    return (
        "connection refused" in text
        or "connecterror" in text
        or "bridge request failed" in text
    )


def bridge_down_proposal(task: TaskEnvelope) -> ActionProposal:
    """Cursor SDK bridge unreachable — wait rather than guess."""
    agent = (
        task.owner
        if task.owner in {AgentRole.OVERWORLD, AgentRole.BATTLE, AgentRole.RECOVERY}
        else AgentRole.OVERWORLD
    )
    return ActionProposal(
        task_id=task.task_id,
        agent=agent,
        reason="wait — Cursor bridge unavailable",
        actions=[GameAction.WAIT_60],
    )


def llm_error_fallback_proposal(task: TaskEnvelope) -> ActionProposal:
    """Generic LLM failure — safe macro so the run keeps going."""
    if task.owner == AgentRole.BATTLE:
        return ActionProposal(
            task_id=task.task_id,
            agent=AgentRole.BATTLE,
            reason="fallback after LLM failure",
            actions=[GameAction.PRESS_A],
        )
    # B-only: this macro runs blind, and an A while facing an NPC re-opens the
    # dialogue it just cleared. B advances Gen 1 text and starts nothing.
    return ActionProposal(
        task_id=task.task_id,
        agent=AgentRole.OVERWORLD,
        reason="fallback after LLM failure",
        actions=[
            GameAction.HOLD_B_120,
            GameAction.PRESS_B,
            GameAction.HOLD_B_120,
            GameAction.WAIT_60,
        ],
    )
