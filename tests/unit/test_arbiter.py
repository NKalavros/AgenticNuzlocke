from nuzlocke.environment.base import ActionResult
from nuzlocke.orchestration.arbiter import ActionArbiter
from nuzlocke.state.models import (
    ActionProposal,
    AgentRole,
    ControlState,
    GameAction,
    PlayerObservation,
)
from nuzlocke.state.store import EventStore


class FakeEnv:
    def observe(self):
        return PlayerObservation(map_name="PALLET TOWN", x=5, y=5)

    def execute(self, actions):
        return ActionResult(
            executed=actions, stopped_early_because=None, observation=self.observe()
        )

    def get_control(self):
        return ControlState.RUNNING

    def set_control(self, state):
        return None

    def push_event(self, kind, text):
        return None

    def set_objectives(self, objectives):
        return None

    def screenshot(self, path=None):
        return b""

    def close(self):
        return None


def test_arbiter_rejects_non_owner(tmp_path):
    store = EventStore(tmp_path)
    arb = ActionArbiter(FakeEnv(), store, active_owner=AgentRole.OVERWORLD)
    proposal = ActionProposal(
        task_id="t1", agent=AgentRole.BATTLE, reason="nope", actions=[GameAction.PRESS_A]
    )
    result = arb.apply(proposal)
    assert result.status == "rejected"
    assert result.rejection_reason and "not owner" in result.rejection_reason


def test_arbiter_approves_owner(tmp_path):
    store = EventStore(tmp_path)
    arb = ActionArbiter(FakeEnv(), store, active_owner=AgentRole.OVERWORLD)
    proposal = ActionProposal(
        task_id="t1",
        agent=AgentRole.OVERWORLD,
        reason="go",
        actions=[GameAction.WALK_UP, GameAction.WALK_UP],
    )
    result = arb.apply(proposal)
    assert result.status == "approved"
    assert len(result.executed_actions) == 2
