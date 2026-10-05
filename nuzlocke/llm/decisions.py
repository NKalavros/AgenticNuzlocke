"""A common choice contract; ordinary model choices never invent probabilities."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Protocol


class DecisionError(RuntimeError):
    """A decision response is unusable."""


@dataclass(frozen=True)
class DecisionResult:
    action: str
    confidence: float
    plan_stale: float
    objective_done: float
    model: str
    probabilities: dict[str, float] = field(default_factory=dict)
    latency_s: float = 0.0
    provider: str = "jev"
    abstain: bool = False
    decision_mode: str = "probabilities"
    usage: dict[str, Any] | None = None


class DecisionProvider(Protocol):
    def decide(self, *, state: Any, questions: dict, allowed: set[str] | None = None) -> DecisionResult: ...
    def close(self) -> None: ...


class APIDecisionProvider:
    def __init__(self, client: Any):
        self.client = client
        self.model = client.model
        self.name = client.name

    def decide(self, *, state: Any, questions: dict, allowed: set[str] | None = None) -> DecisionResult:
        offered = set((questions.get("action") or {}).get("criteria") or {})
        choices = offered if allowed is None else offered & allowed
        if not choices:
            raise DecisionError("System 1 has no offered choices")
        properties: dict[str, Any] = {
            "action": {"type": ["string", "null"], "enum": [*sorted(choices), None]},
            "abstain": {"type": "boolean"},
        }
        for key in ("plan_stale", "objective_done"):
            if key in questions:
                properties[key] = {"type": "boolean"}
        schema = {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}
        started = time.monotonic()
        data, usage = self.client.structured(
            system="Choose exactly one offered action using its criteria and the supplied state. If unsure, return action=null and abstain=true. Otherwise abstain=false. Answer the other questions only when requested. Return only JSON.",
            user=json.dumps({"state": state, "questions": questions}, separators=(",", ":")),
            schema=schema,
        )
        if not isinstance(data, dict) or set(data) != set(properties):
            raise DecisionError("System 1 response has missing or unexpected fields")
        if type(data["abstain"]) is not bool:
            raise DecisionError("System 1 abstain must be boolean")
        action = data["action"]
        if (data["abstain"] and action is not None) or (
            not data["abstain"] and (not isinstance(action, str) or action not in choices)
        ):
            raise DecisionError("System 1 must choose an offered action or abstain")
        for key in properties.keys() - {"action", "abstain"}:
            if type(data[key]) is not bool:
                raise DecisionError(f"System 1 {key} must be boolean")
        return DecisionResult(
            action=action or "",
            confidence=0.0,
            plan_stale=float(data.get("plan_stale", False)),
            objective_done=float(data.get("objective_done", False)),
            model=self.model,
            provider=self.name,
            abstain=data["abstain"],
            decision_mode="choice",
            usage=usage,
            latency_s=round(time.monotonic() - started, 3),
        )

    def close(self) -> None:
        self.client.close()
