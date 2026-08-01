"""Cursor provider keeps a durable agent and compacts periodically."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from nuzlocke.llm.cursor_provider import CursorProvider
from nuzlocke.state.models import AgentRole


class _FakeRun:
    def __init__(self, text: str = '{"actions":["press_a"],"reason":"ok"}') -> None:
        self._text = text
        self.id = "run-1"
        self.status = "finished"
        self.result = text
        self.usage = None

    def stream(self):
        yield SimpleNamespace(
            type="assistant",
            message=SimpleNamespace(
                content=[SimpleNamespace(type="text", text=self._text)]
            ),
        )

    def wait(self):
        return self


def test_durable_agent_then_compact_recreates(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CURSOR_API_KEY", "test-key")
    agents: list[MagicMock] = []
    texts: list[str] = []

    def fake_create(*_a, **_k):
        agent = MagicMock()

        def send(message, *_opts):
            text = message if isinstance(message, str) else getattr(message, "text", "")
            texts.append(text)
            if "compacting the conversation" in text:
                return _FakeRun('{"summary":"at oak lab door"}')
            return _FakeRun()

        agent.send.side_effect = send
        agents.append(agent)
        return agent

    with patch("nuzlocke.llm.cursor_provider.Agent.create", side_effect=fake_create):
        provider = CursorProvider(
            workspace=tmp_path / "ws",
            model="gemini-3.6-flash",
            compact_every=2,
        )
        assert len(agents) == 1
        first = agents[0]
        provider.complete(
            role=AgentRole.OVERWORLD,
            system="sys",
            user='{"hello":1}',
        )
        assert len(agents) == 1
        assert first.close.call_count == 0
        provider.complete(
            role=AgentRole.OVERWORLD,
            system="sys",
            user='{"hello":2}',
        )
        # After 2 turns → compact send + recreate
        assert first.close.call_count == 1
        assert len(agents) == 2
        assert provider._session_summary == "at oak lab door"
        provider.complete(
            role=AgentRole.OVERWORLD,
            system="sys",
            user='{"hello":3}',
        )
        assert any("Session summary (compacted earlier)" in t for t in texts)
        assert any("at oak lab door" in t for t in texts)


def test_walkthrough_hint_forbids_skill_read(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CURSOR_API_KEY", "test-key")
    sent: list[str] = []

    def fake_create(*_a, **_k):
        agent = MagicMock()

        def send(message, *_opts):
            text = message if isinstance(message, str) else getattr(message, "text", "")
            sent.append(text)
            return _FakeRun()

        agent.send.side_effect = send
        return agent

    with patch("nuzlocke.llm.cursor_provider.Agent.create", side_effect=fake_create):
        provider = CursorProvider(workspace=tmp_path / "ws", compact_every=0)
        provider.complete(
            role=AgentRole.RECOVERY,
            system="sys",
            user='{"walkthrough_hint":"leave house via stairs"}',
        )
    assert sent
    assert "Do NOT Read skill files" in sent[0]
