"""Single action writer — only process allowed to send inputs."""

from __future__ import annotations

import uuid

from nuzlocke.environment.base import GameEnvironment
from nuzlocke.state.models import ActionProposal, AgentRole, ArbiterResult, GameAction
from nuzlocke.state.store import EventStore


class ActionArbiter:
    def __init__(
        self,
        env: GameEnvironment,
        store: EventStore,
        *,
        active_owner: AgentRole | None = None,
        max_actions: int = 8,
    ) -> None:
        self.env = env
        self.store = store
        self.active_owner = active_owner
        self.max_actions = max_actions

    def set_owner(self, owner: AgentRole) -> None:
        self.active_owner = owner
        self.store.append("owner_changed", {"owner": owner.value})

    def validate(self, proposal: ActionProposal) -> str | None:
        if self.active_owner is None:
            return "no_active_owner"
        if proposal.agent != self.active_owner:
            return f"agent {proposal.agent.value} is not owner {self.active_owner.value}"
        if not proposal.actions:
            return "empty_actions"
        if len(proposal.actions) > self.max_actions:
            return f"too_many_actions>{self.max_actions}"
        for action in proposal.actions:
            if not isinstance(action, GameAction):
                return f"invalid_action:{action}"
        return None

    def apply(self, proposal: ActionProposal) -> ArbiterResult:
        proposal_id = f"proposal-{uuid.uuid4().hex[:8]}"
        rejection = self.validate(proposal)
        self.store.append(
            "proposal", {"proposal_id": proposal_id, **proposal.model_dump(mode="json")}
        )
        if rejection:
            result = ArbiterResult(
                proposal_id=proposal_id, status="rejected", rejection_reason=rejection
            )
        else:
            action_result = self.env.execute(proposal.actions)
            state_ref = self.store.append(
                "observation", action_result.observation.model_dump(mode="json")
            )
            result = ArbiterResult(
                proposal_id=proposal_id,
                status="partial" if action_result.stopped_early_because else "approved",
                executed_actions=action_result.executed,
                stopped_early_because=action_result.stopped_early_because,
                result_state_ref=state_ref,
                walks=list(action_result.walks),
            )
        self.store.append("arbiter", result.model_dump(mode="json"))
        return result
