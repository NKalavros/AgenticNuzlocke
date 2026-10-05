"""Google subscription transport and screenshot-only tool enforcement."""

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar

import pytest

from nuzlocke.llm.antigravity_gate import gate
from nuzlocke.llm.antigravity_provider import AntigravityProvider, available_models
from nuzlocke.llm.base import ProviderError
from nuzlocke.llm.diagnostics import doctor
from nuzlocke.llm.settings import resolve_agents_config
from nuzlocke.state.models import AgentRole

MODEL = "gemini-test"
ANSWER = {"scene": "overworld", "see": "The current frame", "plan": "Walk north"}


class FakeCLI:
    instances: ClassVar[list] = []
    attest = True
    status = "SUCCESS"
    reply_model = MODEL

    def __init__(self, argv, *, cwd, **kwargs):
        self.argv, self.cwd = argv, cwd
        self.sent, self.events = [], []
        self.closed = False
        self.instances.append(self)

    def send(self, message):
        if not self.sent:
            self.events.append(
                {
                    "event": "init",
                    "conversation_id": "one",
                    "init": {
                        "model": self.reply_model,
                        "agent": "nuzlocke-vision",
                        "permission_mode": "request-review",
                    },
                }
            )
        self.sent.append(message)
        manifest = json.loads((self.cwd / "turn.json").read_text())
        if self.attest:
            (self.cwd / "viewed.jsonl").write_text(
                "".join(
                    json.dumps({"turn": manifest["turn"], "image": image}) + "\n"
                    for image in manifest["images"]
                )
            )
        self.events.append(
            {
                "event": "result",
                "result": {
                    "conversation_id": "one",
                    "status": self.status,
                    "response": json.dumps(ANSWER),
                    "usage": {"input_tokens": 20},
                },
            }
        )

    def receive(self, deadline):
        return self.events.pop(0)

    def close(self):
        self.closed = True


@pytest.fixture
def setup(monkeypatch, tmp_path):
    monkeypatch.setattr("nuzlocke.llm.antigravity_provider.available_models", lambda _: [MODEL])
    cfg = resolve_agents_config(
        {"provider": "dual", "system2": {"provider": "antigravity", "model": MODEL}}
    )
    image = tmp_path / "source.png"
    image.write_bytes(b"real-image-bytes")
    return cfg, image


def ask(provider, image):
    return provider.complete(
        role=AgentRole.DIRECTOR, system="play", user="look", schema_hint=ANSWER, image_paths=[image]
    )


def test_persistent_session_copies_images_and_installs_hooks(setup, tmp_path):
    cfg, image = setup
    provider = AntigravityProvider(
        config=cfg["system2"], workspace=tmp_path / "workspace with spaces", process_factory=FakeCLI
    )
    try:
        assert ask(provider, image).parsed == ANSWER
        rpc = provider.rpc
        first = json.loads((provider.workspace / "turn.json").read_text())
        assert Path(first["images"][0]).read_bytes() == image.read_bytes()
        assert first["images"][0] in rpc.sent[0]["message"]["content"]
        assert ask(provider, image).provider == "antigravity"
        assert provider.rpc is rpc and len(rpc.sent) == 2
        assert first["turn"] != json.loads((provider.workspace / "turn.json").read_text())["turn"]
        hooks = json.loads((provider.workspace / ".agents/hooks.json").read_text())[
            "nuzlocke-screenshot-gate"
        ]
        assert set(hooks) == {"PreToolUse", "PostToolUse"}
        assert (
            "tools: [view_file]"
            in (provider.workspace / ".agents/agents/nuzlocke-vision/agent.md").read_text()
        )
        assert "--dangerously-skip-permissions" not in rpc.argv
    finally:
        provider.close()
    assert rpc.closed


@pytest.mark.parametrize(
    "attribute,value,error",
    [
        ("attest", False, "screenshot read was not verified"),
        ("status", "ERROR", "turn failed"),
        ("reply_model", "unexpected-model", "requested model"),
    ],
)
def test_failed_or_unverified_turn_closes_client(setup, tmp_path, attribute, value, error):
    cfg, image = setup
    client = type("BrokenCLI", (FakeCLI,), {attribute: value})
    provider = AntigravityProvider(
        config=cfg["system2"], workspace=tmp_path / "workspace", process_factory=client
    )
    with pytest.raises(ProviderError, match=error):
        ask(provider, image)
    assert client.instances[-1].closed


@pytest.mark.parametrize(
    "tool,args",
    [
        ("run_command", {"CommandLine": "echo harmless"}),
        ("write_to_file", {"TargetFile": "frame.png"}),
        ("send_message", {}),
        ("call_mcp_tool", {}),
        ("view_file", {"AbsolutePath": "/unrelated/file"}),
        ("view_file", {"AbsolutePath": "frame.png"}),
    ],
)
def test_gate_blocks_non_screenshot_operations(tmp_path, tool, args):
    result = gate(
        {"toolCall": {"name": tool, "args": args}}, {"images": [str(tmp_path / "frame.png")]}
    )
    assert result["decision"] == "deny"


def test_gate_rejects_symlink_substitution(tmp_path):
    link = tmp_path / "frame.png"
    link.symlink_to(tmp_path / "unrelated.txt")
    assert (
        gate(
            {"toolCall": {"name": "view_file", "args": {"AbsolutePath": str(link)}}},
            {"images": [str(link)]},
        )["decision"]
        == "deny"
    )


def test_actual_hook_only_attests_successful_reads(tmp_path):
    from nuzlocke.llm import antigravity_gate

    frame = tmp_path / "frame.png"
    frame.write_bytes(b"image")
    (tmp_path / "turn.json").write_text(json.dumps({"turn": "t", "images": [str(frame)]}))
    payload = {"toolCall": {"name": "view_file", "args": {"AbsolutePath": str(frame)}}}

    def invoke(mode, data):
        result = subprocess.run(
            [sys.executable, antigravity_gate.__file__, mode, str(tmp_path)],
            input=json.dumps(data),
            capture_output=True,
            text=True,
            check=True,
        )
        return json.loads(result.stdout)

    assert invoke("pre", payload)["decision"] == "allow"
    invoke("post", {**payload, "error": "could not open image"})
    assert not (tmp_path / "viewed.jsonl").exists()
    invoke("post", payload)
    assert json.loads((tmp_path / "viewed.jsonl").read_text()) == {"image": str(frame), "turn": "t"}


def test_model_listing_filters_output_and_errors(monkeypatch):
    monkeypatch.setattr(
        "nuzlocke.llm.antigravity_provider.subprocess.run",
        lambda *a, **k: SimpleNamespace(
            returncode=0, stdout="Fetching models...\ngemini-test\tGemini Test\n"
        ),
    )
    assert available_models("agy") == [MODEL]
    monkeypatch.setattr(
        "nuzlocke.llm.antigravity_provider.subprocess.run",
        lambda *a, **k: SimpleNamespace(returncode=1, stdout="secret-sentinel"),
    )
    with pytest.raises(ProviderError) as err:
        available_models("agy")
    assert "secret-sentinel" not in str(err.value)


def test_doctor_checks_selected_model_without_inference(setup, monkeypatch):
    cfg, _ = setup
    monkeypatch.setenv("JEV_API_KEY", "test")
    monkeypatch.setattr("nuzlocke.llm.diagnostics.shutil.which", lambda _: "/bin/agy")
    monkeypatch.setattr(
        "nuzlocke.llm.diagnostics.subprocess.run", lambda *a, **k: SimpleNamespace(stdout="1.2.11")
    )
    report = doctor(cfg)
    assert report["ready"]
    assert report["systems"]["system2"]["models"] == [MODEL]
