"""Official-client wire contracts without real accounts or inference."""

import base64
import json
from types import SimpleNamespace
from typing import ClassVar

import pytest

from nuzlocke.llm.base import ProviderError
from nuzlocke.llm.cli_providers import ClaudeCodeProvider, CodexProvider, GeminiCLIProvider
from nuzlocke.llm.settings import resolve_agents_config
from nuzlocke.state.models import AgentRole

ANSWER = {"scene": "overworld", "see": "A path", "plan": "Walk north"}
HINT = {"scene": "overworld", "see": "description", "plan": "objective"}


class FakeProcess:
    instances: ClassVar[list] = []

    def __init__(self, argv, **kwargs):
        self.argv = argv
        self.sent = []
        self.requests = []
        self.closed = False
        self.events = []
        self.process = SimpleNamespace(stdin=SimpleNamespace(close=lambda: None))
        self.instances.append(self)

    def send(self, value):
        self.sent.append(value)

    def request(self, method, params, on_event=None):
        self.requests.append((method, params))
        if method == "initialize":
            return {"agentCapabilities": {"promptCapabilities": {"image": True}}}
        if method == "account/read":
            return {"account": {"type": "chatgpt"}}
        if method == "model/list":
            return {
                "data": [
                    {
                        "id": "vision",
                        "model": "vision",
                        "isDefault": True,
                        "inputModalities": ["text", "image"],
                    }
                ]
            }
        if method == "config/read":
            return {"config": {"mcp_servers": {"external": {}}, "plugins": {"external@market": {}}}}
        if method == "thread/start":
            return {"thread": {"id": "thread-1"}}
        if method == "turn/start":
            self.events = [
                {
                    "method": "item/completed",
                    "params": {
                        "threadId": "thread-1",
                        "item": {
                            "id": "final",
                            "type": "agentMessage",
                            "phase": "final_answer",
                            "text": json.dumps(ANSWER),
                        },
                    },
                },
                {
                    "method": "turn/completed",
                    "params": {"threadId": "thread-1", "turn": {"status": "completed"}},
                },
            ]
            return {"turn": {"id": "turn-1"}}
        if method == "session/new":
            return {"sessionId": "gemini-session", "models": {"currentModelId": "gemini-test"}}
        if method == "session/prompt":
            on_event(
                {
                    "method": "session/update",
                    "params": {
                        "sessionId": "gemini-session",
                        "update": {
                            "sessionUpdate": "agent_message_chunk",
                            "content": {"type": "text", "text": json.dumps(ANSWER)},
                        },
                    },
                }
            )
            return {"stopReason": "end_turn"}
        return {}

    def receive(self, deadline):
        return self.events.pop(0)

    def dispatch(self, event, callback):
        callback(event)

    def close(self):
        self.closed = True


def options(name):
    return resolve_agents_config({"provider": "dual", "system2": {"provider": name}})["system2"]


def ask(provider, image):
    return provider.complete(
        role=AgentRole.DIRECTOR, system="play", user="state", schema_hint=HINT, image_paths=[image]
    )


@pytest.fixture
def frame(tmp_path):
    path = tmp_path / "frame.png"
    path.write_bytes(b"png-sentinel")
    return path


def test_codex_reuses_thread_and_attaches_actual_image(tmp_path, frame):
    provider = CodexProvider(
        config=options("codex"), workspace=tmp_path / "codex", process_factory=FakeProcess
    )
    assert ask(provider, frame).parsed == ANSWER
    rpc = provider.rpc
    ask(provider, frame)
    starts = [p for m, p in rpc.requests if m == "thread/start"]
    turns = [p for m, p in rpc.requests if m == "turn/start"]
    assert len(starts) == 1 and len(turns) == 2
    assert turns[0]["input"][1] == {"type": "localImage", "path": str(frame)}
    assert starts[0]["sandbox"] == "read-only"
    assert starts[0]["config"]["mcp_servers.external.enabled"] is False
    assert starts[0]["config"]["plugins.external@market.enabled"] is False
    provider.close()
    assert rpc.closed


def test_codex_actor_uses_choice_schema_and_no_image(tmp_path):
    from nuzlocke.llm.decisions import APIDecisionProvider

    class DecisionProcess(FakeProcess):
        def request(self, method, params, **kwargs):
            result = super().request(method, params, **kwargs)
            if method == "turn/start":
                self.events[0]["params"]["item"]["text"] = json.dumps(
                    {"action": "walk", "abstain": False}
                )
            return result

    client = CodexProvider(
        config=options("codex"), workspace=tmp_path, process_factory=DecisionProcess
    )
    actor = APIDecisionProvider(client)
    try:
        result = actor.decide(
            state={"location": "Route 2"}, questions={"action": {"criteria": {"walk": "Go north"}}}
        )
        assert result.action == "walk" and result.decision_mode == "choice"
        assert result.probabilities == {}
        args = next(p for m, p in client.rpc.requests if m == "turn/start")
        assert args["outputSchema"]["properties"]["action"]["enum"] == ["walk", None]
        assert [part["type"] for part in args["input"]] == ["text"]
    finally:
        actor.close()


def test_codex_rejects_api_auth_and_closes_process(tmp_path, frame):
    class APIAuth(FakeProcess):
        def request(self, method, params, **kwargs):
            return (
                {"account": {"type": "apiKey"}}
                if method == "account/read"
                else super().request(method, params, **kwargs)
            )

    provider = CodexProvider(
        config=options("codex"), workspace=tmp_path / "codex", process_factory=APIAuth
    )
    with pytest.raises(ProviderError, match="ChatGPT login"):
        ask(provider, frame)
    assert APIAuth.instances[-1].closed
    assert not any(m == "turn/start" for m, _ in APIAuth.instances[-1].requests)


def test_gemini_reuses_session_and_attaches_base64(tmp_path, frame):
    provider = GeminiCLIProvider(
        config=options("gemini_cli"), workspace=tmp_path / "gemini", process_factory=FakeProcess
    )
    assert ask(provider, frame).parsed == ANSWER
    rpc = provider.rpc
    ask(provider, frame)
    calls = [p for m, p in rpc.requests if m == "session/prompt"]
    assert len([m for m, _ in rpc.requests if m == "session/new"]) == 1
    assert base64.b64decode(calls[0]["prompt"][1]["data"]) == frame.read_bytes()
    assert "--admin-policy" in rpc.argv
    provider.close()


def test_gemini_no_vision_fails_before_session_creation(tmp_path, frame):
    class NoVision(FakeProcess):
        def request(self, method, params, **kwargs):
            return {} if method == "initialize" else super().request(method, params, **kwargs)

    provider = GeminiCLIProvider(
        config=options("gemini_cli"), workspace=tmp_path / "gemini", process_factory=NoVision
    )
    with pytest.raises(ProviderError, match="image support"):
        ask(provider, frame)
    assert NoVision.instances[-1].closed


def test_claude_resumes_explicit_session_and_disables_tools(monkeypatch, tmp_path, frame):
    monkeypatch.setattr(
        "nuzlocke.llm.cli_providers.subprocess.run",
        lambda *a, **k: SimpleNamespace(
            stdout=json.dumps({"loggedIn": True, "authMethod": "oauth_token"})
        ),
    )

    class ClaudeProcess(FakeProcess):
        def send(self, value):
            super().send(value)
            self.events = [
                {
                    "type": "system",
                    "subtype": "init",
                    "session_id": "claude-session",
                    "model": "claude-test",
                },
                {
                    "type": "result",
                    "subtype": "success",
                    "result": json.dumps(ANSWER),
                    "usage": {"input_tokens": 5},
                },
            ]

    provider = ClaudeCodeProvider(
        config=options("claude_code"), workspace=tmp_path / "claude", process_factory=ClaudeProcess
    )
    assert ask(provider, frame).parsed == ANSWER
    first = ClaudeProcess.instances[-1]
    assert first.closed
    assert first.argv[first.argv.index("--tools") + 1] == ""
    assert "--safe-mode" in first.argv and "--bare" not in first.argv
    assert (
        base64.b64decode(first.sent[0]["message"]["content"][1]["source"]["data"])
        == frame.read_bytes()
    )
    ask(provider, frame)
    second = ClaudeProcess.instances[-1]
    assert second.argv[second.argv.index("--resume") + 1] == "claude-session"
    provider.close()


def test_invalid_planner_output_closes_client(tmp_path, frame):
    class BadJSON(FakeProcess):
        def request(self, method, params, **kwargs):
            result = super().request(method, params, **kwargs)
            if method == "turn/start":
                self.events[0]["params"]["item"]["text"] = "{}"
            return result

    provider = CodexProvider(
        config=options("codex"), workspace=tmp_path / "codex", process_factory=BadJSON
    )
    with pytest.raises(ProviderError, match="scene"):
        ask(provider, frame)
    assert BadJSON.instances[-1].closed
