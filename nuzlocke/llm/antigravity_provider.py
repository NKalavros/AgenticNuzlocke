"""Google subscription vision via the unmodified Antigravity CLI."""

from __future__ import annotations

import json
import re
import shlex
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

from nuzlocke.llm.base import ProviderError
from nuzlocke.llm.cli_providers import CLIProvider, client_env


def available_models(binary: str) -> list[str]:
    """Ask the vendor client about account access without performing inference."""
    try:
        result = subprocess.run([binary, "models"], capture_output=True, text=True, env=client_env(), timeout=20, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise ProviderError("antigravity: cannot list models; run agy and sign in with Google") from None
    models = [line.split("\t")[0] for line in result.stdout.splitlines() if re.fullmatch(r"[a-z0-9][a-z0-9._-]+\t.+", line)]
    if result.returncode or not models:
        raise ProviderError("antigravity: model access unavailable; run agy and sign in with Google")
    return models


class AntigravityProvider(CLIProvider):
    name = "antigravity"

    def _start(self):
        if self.rpc:
            return
        models = available_models(self.config["binary"])
        if not self.model:
            self.model = next((model for model in models if model.startswith("gemini-")), None)
        if self.model not in models:
            raise ProviderError("antigravity: selected model is unavailable; check agy models")
        custom = self.workspace / ".agents"
        agent = custom / "agents" / "nuzlocke-vision" / "agent.md"
        agent.parent.mkdir(parents=True, exist_ok=True)
        agent.write_text(
            "---\nname: nuzlocke-vision\ndescription: Nuzlocke screenshot planner\n"
            "tools: [view_file]\nmainAgent: true\nsubagent: false\n"
            'commandExecutionPolicy: "off"\nskills: []\nplugins: []\nmcpServers: []\n---\n'
            "Read every screenshot named by the user with view_file. Use only supplied context. "
            "Return the requested JSON. Never use other tools, change files, or control the game.\n"
        )
        gate = Path(__file__).with_name("antigravity_gate.py").resolve()
        hooks = {}
        for event, mode in (("PreToolUse", "pre"), ("PostToolUse", "post")):
            hooks[event] = [
                {
                    "matcher": "*",
                    "hooks": [
                        {
                            "type": "command",
                            "timeout": 5,
                            "command": shlex.join([sys.executable, str(gate), mode, str(self.workspace)]),
                        }
                    ],
                }
            ]
        (custom / "hooks.json").write_text(json.dumps({"nuzlocke-screenshot-gate": hooks}))
        argv = [
            self.config["binary"],
            "--input-format",
            "stream-json",
            "--output-format",
            "stream-json",
            "--agent",
            "nuzlocke-vision",
            "--disable-slash-commands",
            "--mode",
            "plan",
            "--model",
            self.model,
        ]
        if effort := self.config.get("params", {}).get("reasoning_effort"):
            argv += ["--effort", effort]
        self.rpc = self.process_factory(argv, cwd=self.workspace, env=client_env(), timeout_s=self.config["timeout_s"])

    def _complete(self, prompt, images, role):
        self._start()
        turn = uuid.uuid4().hex
        frames = []
        for index, source in enumerate(images):
            dest = self.workspace / f"frame-{turn}-{index}.png"
            shutil.copyfile(source, dest)
            frames.append(str(dest))
        (self.workspace / "turn.json").write_text(json.dumps({"turn": turn, "images": frames}))
        (self.workspace / "viewed.jsonl").write_text("")
        # Headless input supports text blocks. Native view_file supplies the actual image.
        prompt = prompt.replace(
            "Do not use tools, change files, or control the emulator.",
            "Use view_file only to read the listed screenshots; never change files or control the emulator.",
        )
        prompt += "\nRead each current screenshot with view_file before answering:\n" + json.dumps(frames)
        self.rpc.send({"event": "user", "message": {"content": prompt}})
        deadline = time.monotonic() + self.config["timeout_s"]
        while True:
            event = self.rpc.receive(deadline)
            kind = event.get("event")
            if kind == "init":
                init = event.get("init") or {}
                if init.get("model") != self.model or init.get("agent") != "nuzlocke-vision":
                    raise ProviderError("antigravity: client did not select the requested model and agent")
                if init.get("permission_mode") not in {"request-review", "strict"}:
                    raise ProviderError("antigravity: set toolPermission to request-review or strict in agy settings")
                self.session_id = event.get("conversation_id")
            elif kind == "result":
                result = event.get("result") or {}
                if result.get("status") != "SUCCESS" or not self.session_id:
                    raise ProviderError("antigravity: turn failed; check login, model access, or quota")
                if result.get("conversation_id") != self.session_id:
                    raise ProviderError("antigravity: unexpected conversation in result")
                self.usage = result.get("usage")
                viewed = {
                    row["image"]
                    for line in (self.workspace / "viewed.jsonl").read_text().splitlines()
                    if (row := json.loads(line)).get("turn") == turn
                }
                if not set(frames).issubset(viewed):
                    raise ProviderError("antigravity: screenshot read was not verified; check CLI hook compatibility")
                text = result.get("response")
                if not isinstance(text, str) or not text.strip():
                    raise ProviderError("antigravity: missing response text")
                return text
