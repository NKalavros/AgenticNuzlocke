"""Cursor provider keeps a durable agent and compacts by context size."""

from __future__ import annotations

import contextlib
from collections.abc import Callable, Iterator
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from nuzlocke.llm.cursor_provider import CursorProvider
from nuzlocke.state.models import AgentRole


class _FakeRun:
    def __init__(
        self, text: str = '{"actions":["press_a"],"reason":"ok"}', *, input_tokens: int = 1000
    ) -> None:
        self._text = text
        self.id = "run-1"
        self.status = "finished"
        self.result = text
        self.usage = SimpleNamespace(
            input_tokens=input_tokens, output_tokens=10, total_tokens=input_tokens + 10
        )

    def stream(self):
        yield SimpleNamespace(
            type="assistant",
            message=SimpleNamespace(content=[SimpleNamespace(type="text", text=self._text)]),
        )

    def wait(self):
        return self


def _text(message) -> str:
    return message if isinstance(message, str) else getattr(message, "text", "")


@contextlib.contextmanager
def _fake_agents(send: Callable) -> Iterator[list[MagicMock]]:
    agents: list[MagicMock] = []

    def fake_create(*_a, **_k):
        agent = MagicMock()
        agent.send.side_effect = send
        agents.append(agent)
        return agent

    with (
        patch("nuzlocke.llm.cursor_provider.Agent.create", side_effect=fake_create),
        patch.object(CursorProvider, "_ensure_client", return_value=None),
    ):
        yield agents


def test_compact_when_input_tokens_exceed_threshold(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CURSOR_API_KEY", "test-key")
    texts: list[str] = []
    token_seq = iter([10_000, 260_000, 5_000])

    def send(message, *_opts):
        texts.append(_text(message))
        if "compacting the conversation" in texts[-1]:
            return _FakeRun('{"summary":"at oak lab door"}', input_tokens=50)
        return _FakeRun(input_tokens=next(token_seq))

    with _fake_agents(send) as agents:
        provider = CursorProvider(
            workspace=tmp_path / "ws", model="gemini-3.6-flash", compact_at_tokens=250_000
        )
        first = agents[0]
        provider.complete(role=AgentRole.OVERWORLD, system="sys", user='{"hello":1}')
        assert first.close.call_count == 0
        provider.complete(role=AgentRole.OVERWORLD, system="sys", user='{"hello":2}')
        assert first.close.call_count == 1
        assert len(agents) == 2
        assert provider._session_summary == "at oak lab door"
        provider.complete(role=AgentRole.OVERWORLD, system="sys", user='{"hello":3}')
        assert any("Session summary (compacted earlier)" in t for t in texts)


def test_walkthrough_hint_forbids_skill_read(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CURSOR_API_KEY", "test-key")
    sent: list[str] = []

    def send(message, *_opts):
        sent.append(_text(message))
        return _FakeRun()

    with _fake_agents(send):
        provider = CursorProvider(workspace=tmp_path / "ws", compact_at_tokens=0)
        provider.complete(
            role=AgentRole.RECOVERY,
            system="sys",
            user='{"walkthrough_hint":"leave house via stairs"}',
        )
    assert sent
    assert "Do NOT Read skill files" in sent[0]


def test_bridge_auth_token_cannot_start_with_a_dash():
    import cursor_sdk._tool_callback as tool_cb

    from nuzlocke.llm.cursor_provider import install_bridge_token_guard

    tool_cb._new_auth_token = lambda: "-not-a-flag"
    install_bridge_token_guard()
    token = tool_cb._new_auth_token()
    assert token
    assert not token.startswith("-")


def test_lazy_planner_starts_only_when_called(tmp_path, monkeypatch):
    monkeypatch.setenv("CURSOR_API_KEY", "test-key")
    with _fake_agents(lambda *_a, **_k: _FakeRun()) as agents:
        provider = CursorProvider(workspace=tmp_path, lazy_start=True)
        assert agents == []
        provider.complete(role=AgentRole.OVERWORLD, system="test", user="test")
        assert len(agents) == 1
        provider.close()
