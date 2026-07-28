"""Game environment protocol."""

from __future__ import annotations

from typing import Protocol

from nuzlocke.state.models import ControlState, GameAction, PlayerObservation


class ActionResult:
    def __init__(
        self,
        *,
        executed: list[GameAction],
        stopped_early_because: str | None,
        observation: PlayerObservation,
    ) -> None:
        self.executed = executed
        self.stopped_early_because = stopped_early_because
        self.observation = observation


class GameEnvironment(Protocol):
    def observe(self) -> PlayerObservation: ...
    def screenshot(self, path: str | None = None) -> bytes: ...
    def execute(self, actions: list[GameAction]) -> ActionResult: ...
    def get_control(self) -> ControlState: ...
    def set_control(self, state: ControlState) -> None: ...
    def push_event(self, kind: str, text: str) -> None: ...
    def set_objectives(self, objectives: list[dict]) -> None: ...
    def close(self) -> None: ...
