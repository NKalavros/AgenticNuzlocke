"""TypeSafe Jev client — System One decisions, not chat completions.

``POST /v1/systemone`` takes text state plus typed questions and returns a
choice, probabilities, and confidence. Jev does not see images and does not
write text. The API key is read from the environment and never logged.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx


class JevDecisionError(RuntimeError):
    """The decisions endpoint refused the call or returned an unusable answer."""


@dataclass(frozen=True)
class JevAnswers:
    action: str
    confidence: float
    plan_stale: float
    objective_done: float
    model: str


class JevClient:
    """One decisions call per prompt cycle. Retries 429 and 529 with backoff."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.typesafe.ai",
        model: str = "jev-latest",
        timeout_s: float = 8.0,
        max_retries: int = 3,
        sleep: Callable[[float], None] | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not api_key:
            raise JevDecisionError("Jev API key is empty")
        self.model = model
        self.max_retries = max(1, int(max_retries))
        self._sleep = sleep or time.sleep
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=timeout_s,
            headers={"Authorization": f"Bearer {api_key}"},
            transport=transport,
        )

    def decide(
        self,
        *,
        state: dict[str, Any] | str | list[Any],
        questions: dict[str, Any],
        allowed: set[str] | None = None,
    ) -> JevAnswers:
        body = {"model": self.model, "state": state, "questions": questions}
        response: httpx.Response | None = None
        delay = 0.25
        for attempt in range(self.max_retries):
            response = self._client.post("/v1/systemone", json=body)
            if response.status_code in (429, 529) and attempt + 1 < self.max_retries:
                retry_after = response.headers.get("retry-after")
                try:
                    wait = float(retry_after) if retry_after else delay
                except ValueError:
                    wait = delay
                self._sleep(min(max(wait, 0.0), 8.0))
                delay = min(delay * 2, 4.0)
                continue
            break
        if response is None:
            raise JevDecisionError("jev request was not sent")
        if response.status_code >= 400:
            raise JevDecisionError(f"jev HTTP {response.status_code}")
        try:
            payload = response.json()
        except ValueError as err:
            raise JevDecisionError("jev response was not JSON") from err
        return parse_answers(payload, allowed=allowed)

    def close(self) -> None:
        self._client.close()


def parse_answers(
    payload: dict[str, Any],
    *,
    allowed: set[str] | None = None,
) -> JevAnswers:
    """Pull the action choice and the two noul gates out of a systemone body."""
    if not isinstance(payload, dict):
        raise JevDecisionError("jev response was not an object")
    answers = payload.get("answers")
    if not isinstance(answers, dict):
        raise JevDecisionError("jev response missing answers")
    action = answers.get("action")
    if not isinstance(action, dict) or not action.get("choice"):
        raise JevDecisionError("jev response missing action choice")
    choice = str(action["choice"])
    if allowed is not None and choice not in allowed:
        raise JevDecisionError(f"jev chose an action outside the menu: {choice}")
    try:
        confidence = float(action.get("confidence") or 0.0)
    except (TypeError, ValueError) as err:
        raise JevDecisionError("jev action confidence was not a number") from err
    return JevAnswers(
        action=choice,
        confidence=confidence,
        plan_stale=_noul(answers.get("plan_stale"), name="plan_stale"),
        objective_done=_noul(answers.get("objective_done"), name="objective_done"),
        model=str(payload.get("model") or ""),
    )


def _noul(raw: Any, *, name: str) -> float:
    if not isinstance(raw, dict) or "noul" not in raw:
        raise JevDecisionError(f"jev response missing {name}")
    try:
        value = float(raw["noul"])
    except (TypeError, ValueError) as err:
        raise JevDecisionError(f"jev {name} was not a number") from err
    if value < 0.0 or value > 1.0:
        raise JevDecisionError(f"jev {name} out of range")
    return value
