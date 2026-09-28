"""Jev client parses a decisions response and rejects menus it was not given."""

from __future__ import annotations

import json

import httpx
import pytest

from nuzlocke.llm.factory import create_jev
from nuzlocke.llm.jev import JevClient, JevDecisionError


def _body(choice: str = "press_b", *, confidence: float = 0.9, stale: float = 0.1, done: float = 0.2) -> dict:
    return {
        "model": "jev-1.13.0",
        "answers": {
            "action": {
                "type": "choice",
                "choice": choice,
                "confidence": confidence,
                "probabilities": {choice: 1.0},
            },
            "plan_stale": {"type": "noul", "noul": stale},
            "objective_done": {"type": "noul", "noul": done},
        },
    }


def _client(handler, **kwargs) -> JevClient:
    return JevClient(
        api_key="test-key",
        transport=httpx.MockTransport(handler),
        **kwargs,
    )


def test_decide_parses_choice_and_nouls():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/systemone"
        assert request.headers["Authorization"] == "Bearer test-key"
        body = json.loads(request.content)
        assert body["model"] == "jev-latest"
        assert body["state"]["scene"] == "overworld"
        assert "action" in body["questions"]
        return httpx.Response(200, json=_body())

    client = _client(handler)
    answers = client.decide(
        state={"scene": "overworld"},
        questions={"action": {"type": "choice"}},
        allowed={"press_b"},
    )
    assert answers.action == "press_b"
    assert answers.confidence == 0.9
    assert answers.plan_stale == 0.1
    assert answers.objective_done == 0.2
    assert answers.model == "jev-1.13.0"
    client.close()


def test_unknown_action_is_rejected():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_body(choice="walk_up"))

    client = _client(handler)
    with pytest.raises(JevDecisionError, match="outside the menu"):
        client.decide(state="x", questions={"action": {}}, allowed={"press_b"})
    client.close()


def test_retries_overloaded_then_succeeds():
    calls = {"n": 0}
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"retry-after": "0.01"}, json={"detail": "slow"})
        return httpx.Response(200, json=_body())

    client = _client(handler, sleep=sleeps.append, max_retries=3)
    answers = client.decide(state="x", questions={"action": {}}, allowed={"press_b"})
    assert answers.action == "press_b"
    assert calls["n"] == 2
    assert sleeps == [0.01]
    client.close()


def test_create_jev_only_for_dual(monkeypatch):
    monkeypatch.delenv("JEV_API_KEY", raising=False)
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    assert create_jev({"provider": "cursor"}) is None
    with pytest.raises(RuntimeError, match="JEV_API_KEY"):
        create_jev({"provider": "dual", "jev": {}})
    monkeypatch.setenv("JEV_API_KEY", "test-key")
    client = create_jev({"provider": "dual", "jev": {"model": "jev-latest"}})
    assert client is not None
    assert client.model == "jev-latest"
    client.close()
