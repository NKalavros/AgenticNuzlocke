"""Configuration compatibility and public CLI overrides."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from apps.orchestrator import main
from nuzlocke.llm.settings import preflight, provider_identity, resolve_agents_config
from nuzlocke.orchestration.journal import Journal
from nuzlocke.orchestration.loop import RunLoop


def test_legacy_dual_and_idempotent_resolution():
    old = {
        "provider": "dual",
        "cursor": {"model": "old", "params": {"effort": "low"}},
        "planner": {"model": "planner", "params": {"reasoning_effort": "high"}},
        "jev": {"model": "jev-custom"},
    }
    cfg = resolve_agents_config(old)
    assert cfg["system2"]["provider"] == "cursor"
    assert cfg["system2"]["model"] == "planner"
    assert cfg["system1"]["model"] == "jev-custom"
    assert resolve_agents_config(cfg) == cfg
    assert "system1" not in old


def test_provider_change_drops_foreign_models_and_params():
    cfg = resolve_agents_config(
        {
            "provider": "dual",
            "planner": {"model": "grok", "params": {"temperature": 0.2}},
            "system2": {"provider": "cursor", "model": "explicit"},
        },
        {"system2": {"provider": "codex"}},
    )
    assert cfg["system2"]["model"] is None
    assert cfg["system2"]["params"] == {}
    assert cfg["system2"]["binary"] == "codex"


def test_independent_api_actor_and_oauth_planner():
    cfg = resolve_agents_config(
        {
            "provider": "dual",
            "system1": {"provider": "openai", "model": "api-model"},
            "system2": {"provider": "claude_code", "model": "sonnet"},
        }
    )
    assert cfg["system1"]["base_url"] == "https://api.openai.com/v1"
    assert cfg["system2"]["api_key_env"] is None
    assert cfg["system2"]["model"] == "sonnet"


@pytest.mark.parametrize(
    "override",
    [
        {"system1": {"provider": "codex"}},
        {"system1": {"provider": "openai"}},
        {"system2": {"provider": "not-real"}},
        {"system2": {"provider": "codex", "params": {"effort": "high"}}},
        {"system2": {"provider": "gemini_cli", "timeout_s": -1}},
        {"system1": {"provider": "openai", "model": "test", "params": {"tools": []}}},
        {
            "system1": {
                "provider": "openai",
                "model": "test",
                "base_url": "https://key@example.com/v1",
            }
        },
        {"system2": {"provider": "codex", "binary": None}},
    ],
)
def test_invalid_settings_rejected(override):
    with pytest.raises(ValueError):
        resolve_agents_config({"provider": "dual", **override})


def test_validation_does_not_echo_secret():
    with pytest.raises(ValueError) as err:
        resolve_agents_config({"system2": {"provider": "codex", "api_key": "secret-sentinel"}})
    assert "secret-sentinel" not in str(err.value)


def test_preflight_missing_client_before_emulator(monkeypatch):
    monkeypatch.setattr("nuzlocke.llm.settings.shutil.which", lambda _: None)
    cfg = resolve_agents_config({"provider": "cursor", "system2": {"provider": "codex"}})
    with pytest.raises(RuntimeError, match="not found"):
        preflight(cfg)


def test_run_cli_routes_overrides_without_starting_real_game(monkeypatch, tmp_path):
    captured = {}

    class Loop:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.run_dir = tmp_path
            self.agents_cfg = resolve_agents_config({"provider": "dual"}, kwargs["agent_overrides"])
            self.run_cfg = {}
            self.vision_only = True
            self.memory = SimpleNamespace(enabled=False)

        def run(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(main, "RunLoop", Loop)
    result = CliRunner().invoke(
        main.app,
        [
            "run",
            "--system1-provider",
            "openai",
            "--system1-model",
            "small",
            "--system2-provider",
            "codex",
            "--system2-model",
            "vision",
            "--max-steps",
            "1",
            "--agents-config",
            "custom.yaml",
        ],
    )
    assert result.exit_code == 0, result.output
    assert captured["agent_overrides"]["system1"] == {"provider": "openai", "model": "small"}
    assert captured["agents_config"] == Path("custom.yaml")


def test_resume_invalidates_only_planner_state(tmp_path):
    loop = RunLoop.__new__(RunLoop)
    loop.agents_cfg = resolve_agents_config({"provider": "dual", "system2": {"provider": "codex"}})
    loop.plan = object()
    maps = {"one": {"grass": [[2, 3]]}}
    loop.navigator = SimpleNamespace(
        route={"old": True}, plan={"old": True}, last_plan={"old": True}, brief={}, maps=maps
    )
    loop.journal = Journal(tmp_path / "journal.jsonl")
    loop.journal.add(
        {"cycle": 1, "map": "Pallet", "x": 1, "y": 2, "actions": [], "outcome": "ready"}
    )
    loop.journal = Journal(loop.journal.path)
    events = []
    loop.store = SimpleNamespace(append=lambda *event: events.append(event))
    loop._restore_provider_context({"planner_provider": {"provider": "cursor"}})
    assert loop.plan is None and loop._force_planner_refresh
    assert loop.navigator.route == {} and loop.navigator.maps is maps
    assert len(loop.journal.since_last_look()) == 1
    assert events[0][0] == "provider_change"
    assert events[0][1]["current"] == provider_identity(loop.agents_cfg["system2"])


def test_doctor_never_returns_auth_fields(monkeypatch):
    from nuzlocke.llm.diagnostics import doctor

    monkeypatch.setattr("nuzlocke.llm.diagnostics.shutil.which", lambda _: "/bin/fake")
    monkeypatch.setattr(
        "nuzlocke.llm.diagnostics.subprocess.run",
        lambda *a, **k: SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {"loggedIn": True, "authMethod": "oauth_token", "accessToken": "secret-sentinel"}
            )
            if "auth" in a[0]
            else "2.1.283",
            stderr="",
        ),
    )
    cfg = resolve_agents_config({"provider": "cursor", "system2": {"provider": "claude_code"}})
    result = doctor(cfg)
    assert result["ready"]
    assert "secret-sentinel" not in json.dumps(result)


def test_run_closes_clients_and_private_server_after_interrupt():
    loop = RunLoop.__new__(RunLoop)
    closed = []

    def interrupted(**kwargs):
        raise KeyboardInterrupt

    loop._run = interrupted
    loop.llm = SimpleNamespace(close=lambda: closed.append("planner"))
    loop.jev = SimpleNamespace(close=lambda: closed.append("actor"))
    loop.env = SimpleNamespace(shutdown=lambda: closed.append("emulator"))
    loop.headless = True
    with pytest.raises(KeyboardInterrupt):
        loop.run(max_steps=1)
    assert closed == ["planner", "actor", "emulator"]
