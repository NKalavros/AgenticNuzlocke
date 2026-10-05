"""Official local-client integrations. OAuth credentials stay with each vendor."""

from __future__ import annotations

import base64
import json
import os
import subprocess
import time
from pathlib import Path

from nuzlocke.assets import data as asset_data
from nuzlocke.llm.base import LLMProvider, ProviderError
from nuzlocke.llm.json_util import extract_json_object
from nuzlocke.llm.process_transport import JsonProcess
from nuzlocke.state.models import AgentRole, LLMResponse


def client_env() -> dict:
    env = os.environ.copy()
    # The Cursor-only HTTP/2 preload must not alter other vendors' Node clients.
    if "cursor_http2_proxy.cjs" in env.get("NODE_OPTIONS", ""):
        import shlex

        parts = shlex.split(env["NODE_OPTIONS"])
        clean = []
        index = 0
        while index < len(parts):
            if parts[index] == "--require" and index + 1 < len(parts) and "cursor_http2_proxy.cjs" in parts[index + 1]:
                index += 2
            else:
                clean.append(parts[index])
                index += 1
        env["NODE_OPTIONS"] = shlex.join(clean)
    return env


def validate_output(data: dict | None, hint: dict | None) -> dict:
    if not isinstance(data, dict):
        raise ProviderError("Planner returned invalid JSON")
    hint = hint or {}
    if "scene" in hint:
        if data.get("scene") not in {"title", "dialog", "naming", "overworld", "battle", "menu"}:
            raise ProviderError("Planner returned an invalid scene")
        for key in ("see", "plan"):
            if not isinstance(data.get(key), str) or not data[key].strip():
                raise ProviderError(f"Planner response is missing {key}")
    for key in ("steps", "do_not", "actions", "proposed_actions", "landmarks", "notes"):
        if key in data and not isinstance(data[key], list):
            raise ProviderError(f"Planner response has invalid {key}")
    if "proposed_actions" in hint and not isinstance(data.get("proposed_actions"), list):
        raise ProviderError("Recovery response is missing proposed_actions")
    if "actions" in hint and not isinstance(data.get("actions"), list):
        raise ProviderError("Role response is missing actions")
    return data


class CLIProvider(LLMProvider):
    def __init__(self, *, config: dict, workspace: Path, on_stream=None, process_factory=JsonProcess):
        self.config = config
        self.model = config.get("model")
        self.workspace = Path(workspace).resolve()
        self.on_stream = on_stream
        self.process_factory = process_factory
        self.rpc = None
        self.session_id = None
        self.usage = None
        self._thought = ""
        self._last_emit = 0.0

    def _emit(self, text):
        if self.on_stream:
            self.on_stream(text)

    def _thinking(self, text, role, *, flush=False):
        self._thought += text
        if self._thought and (flush or time.monotonic() - self._last_emit >= 0.2):
            self._emit(f"[{role.value}:thinking] {self._thought}")
            self._last_emit = time.monotonic()

    def complete(self, *, role, system, user, schema_hint=None, image_paths=None):
        self.workspace.mkdir(parents=True, exist_ok=True)
        prompt = (
            f"You are the Nuzlocke {role.value} role. The attached screenshot is ground truth. "
            "Use only the provided context. Do not use tools, change files, or control the emulator. "
            "Reply with ONLY a JSON object matching this example (descriptions are not literal values):\n"
            + json.dumps(schema_hint or {})
            + "\nInstructions:\n"
            + system
            + "\nObservation:\n"
            + user
        )
        self._thought = ""
        self.usage = None
        self._emit(f"[{role.value}] thinking with {self.name}/{self.model or 'default'}…")
        try:
            text = self._complete(prompt, image_paths or [], role)
            parsed = validate_output(extract_json_object(text), schema_hint)
            self._thinking("", role, flush=True)
            return LLMResponse(
                role=role, raw_text=text, parsed=parsed, model=self.model or "default", provider=self.name, usage=self.usage
            )
        except Exception as err:
            self.close()
            if isinstance(err, ProviderError):
                raise
            raise ProviderError(f"{self.name}: client failure; check login, model, and installed CLI version") from None

    def close(self):
        if self.rpc is not None:
            self.rpc.close()
            self.rpc = None
        self.session_id = None


class CodexProvider(CLIProvider):
    name = "codex"

    def _start(self):
        if self.rpc:
            return
        self.rpc = self.process_factory(
            [self.config["binary"], "app-server", "--stdio"],
            cwd=self.workspace,
            env=client_env(),
            timeout_s=self.config["timeout_s"],
        )
        self.rpc.request("initialize", {"clientInfo": {"name": "nuzlocke", "version": "0.1.0"}})
        self.rpc.send({"method": "initialized"})
        account = self.rpc.request("account/read", {"refreshToken": False}).get("account") or {}
        if account.get("type") != "chatgpt":
            raise ProviderError("codex: ChatGPT login required; run codex login")
        models = []
        cursor = None
        while True:
            page = self.rpc.request("model/list", {"limit": 100, "cursor": cursor})
            models.extend(page.get("data") or [])
            cursor = page.get("nextCursor")
            if not cursor:
                break
        selected = next((m for m in models if (m.get("model") == self.model or m.get("id") == self.model) if self.model), None)
        if not self.model:
            selected = next(
                (m for m in models if m.get("isDefault") and "image" in m.get("inputModalities", ["text", "image"])), None
            )
        if not selected or "image" not in selected.get("inputModalities", ["text", "image"]):
            raise ProviderError("codex: selected/default model is unavailable or lacks vision; check codex model access")
        self.model = selected.get("model") or selected["id"]
        effort = self.config.get("params", {}).get("reasoning_effort")
        if effort and effort not in {v["reasoningEffort"] for v in selected.get("supportedReasoningEfforts", [])}:
            raise ProviderError("codex: requested reasoning_effort is unavailable for this model")
        inherited = self.rpc.request("config/read", {"includeLayers": False}).get("config") or {}
        restricted = dict(asset_data("clients.json")["codex_restrictions"])
        for key in inherited.get("mcp_servers") or {}:
            restricted[f"mcp_servers.{key}.enabled"] = False
        for key in inherited.get("plugins") or {}:
            restricted[f"plugins.{key}.enabled"] = False
        thread = self.rpc.request(
            "thread/start",
            {
                "model": self.model,
                "cwd": str(self.workspace),
                "approvalPolicy": "never",
                "sandbox": "read-only",
                "config": restricted,
                "developerInstructions": "You are a vision decision engine. Never call tools. Return only requested JSON.",
            },
        )
        self.session_id = thread["thread"]["id"]

    def structured(self, *, system: str, user: str, schema: dict):
        """Text-only System 1 choices through the same vendor-owned login."""
        self.workspace.mkdir(parents=True, exist_ok=True)
        self._thought = ""
        self.usage = None
        prompt = (
            "You are the Nuzlocke System 1 decision engine. Use only the current state and "
            "offered choices below; they supersede previous observations. Never call tools. "
            "Return only the requested JSON object.\n"
            + system
            + "\nJSON schema:\n"
            + json.dumps(schema)
            + "\nCurrent state and questions:\n"
            + user
        )
        try:
            text = self._complete(prompt, [], AgentRole.OVERWORLD, output_schema=schema)
            return validate_output(extract_json_object(text), None), self.usage
        except Exception as err:
            self.close()
            if isinstance(err, ProviderError):
                raise
            raise ProviderError("codex: decision client failed; check login and model access") from None

    def _complete(self, prompt, images, role, *, output_schema=None):
        self._start()
        messages = []
        final = {}
        completed = [False]
        failure = [False]

        def event(message):
            method, params = message.get("method"), message.get("params") or {}
            if params.get("threadId") not in (None, self.session_id):
                return
            if method == "item/agentMessage/delta":
                messages.append(params.get("delta", ""))
            elif method in {"item/reasoning/summaryTextDelta", "item/reasoning/textDelta"}:
                self._thinking(params.get("delta", ""), role)
            elif method == "item/completed":
                item = params.get("item") or {}
                if item.get("type") == "agentMessage":
                    final[item.get("id", "final")] = item
            elif method == "thread/tokenUsage/updated":
                self.usage = (params.get("tokenUsage") or {}).get("last")
            elif method == "turn/completed":
                completed[0] = True
                failure[0] = (params.get("turn") or {}).get("status") != "completed"

        content = [{"type": "text", "text": prompt}]
        content += [{"type": "localImage", "path": str(Path(p).resolve())} for p in images]
        args = {"threadId": self.session_id, "input": content}
        if output_schema is not None:
            args["outputSchema"] = output_schema
        effort = self.config.get("params", {}).get("reasoning_effort")
        if effort:
            args["effort"] = effort
        self.rpc.request("turn/start", args, on_event=event)
        deadline = time.monotonic() + self.config["timeout_s"]
        while not completed[0]:
            self.rpc.dispatch(self.rpc.receive(deadline), event)
        if failure[0]:
            raise ProviderError("codex: turn failed; check model access or quota, then press START")
        finals = [item["text"] for item in final.values() if item.get("phase") == "final_answer"]
        return "\n".join(finals or [item.get("text", "") for item in final.values()]) or "".join(messages)


class ClaudeCodeProvider(CLIProvider):
    name = "claude_code"

    def _complete(self, prompt, images, role):
        env = client_env()
        status = subprocess.run(
            [self.config["binary"], "auth", "status"], capture_output=True, text=True, env=env, timeout=15, check=False
        )
        try:
            auth = json.loads(status.stdout)
        except ValueError:
            auth = {}
        if not auth.get("loggedIn") or auth.get("authMethod") not in {"oauth_token", "claude_ai"}:
            raise ProviderError("claude_code: subscription login required; run claude auth login and check claude auth status")
        argv = [self.config["binary"], *asset_data("clients.json")["claude_args"]]
        if self.model:
            argv += ["--model", self.model]
        if self.session_id:
            argv += ["--resume", self.session_id]
        if effort := self.config.get("params", {}).get("reasoning_effort"):
            argv += ["--effort", str(effort)]
        self.rpc = self.process_factory(argv, cwd=self.workspace, env=env, timeout_s=self.config["timeout_s"])
        content = [{"type": "text", "text": prompt}]
        content += [
            {
                "type": "image",
                "source": {"type": "base64", "media_type": "image/png", "data": base64.b64encode(Path(p).read_bytes()).decode()},
            }
            for p in images
        ]
        self.rpc.send(
            {
                "type": "user",
                "message": {"role": "user", "content": content},
                "parent_tool_use_id": None,
                "session_id": self.session_id or "",
            }
        )
        # Each invocation is one turn; --resume preserves the explicit conversation.
        self.rpc.process.stdin.close()
        deadline = time.monotonic() + self.config["timeout_s"]
        try:
            while True:
                event = self.rpc.receive(deadline)
                if event.get("type") == "system" and event.get("subtype") == "init":
                    self.session_id = event.get("session_id") or self.session_id
                    self.model = event.get("model") or self.model
                elif event.get("type") == "stream_event":
                    delta = (event.get("event") or {}).get("delta") or {}
                    if delta.get("type") == "thinking_delta":
                        self._thinking(delta.get("thinking", ""), role)
                elif event.get("type") == "result":
                    if event.get("is_error") or event.get("subtype") != "success":
                        raise ProviderError("claude_code: turn failed; check model access or subscription quota")
                    self.session_id = event.get("session_id") or self.session_id
                    self.usage = event.get("usage")
                    return event.get("result", "")
        finally:
            self.rpc.close()
            self.rpc = None


class GeminiCLIProvider(CLIProvider):
    name = "gemini_cli"

    def _start(self):
        if self.rpc:
            return
        # Auth stays in the vendor home. Only non-secret run-local settings are written here.
        settings_dir = self.workspace / ".gemini"
        settings_dir.mkdir(exist_ok=True)
        (settings_dir / "settings.json").write_text(json.dumps(asset_data("clients.json")["gemini_settings"]))
        policy = settings_dir / "nuzlocke-policy.toml"
        policy.write_text('[[rule]]\ndecision = "deny"\npriority = 999\n')
        env = client_env()
        env["NO_BROWSER"] = "true"
        argv = [self.config["binary"], "--acp", "--extensions", "none", "--admin-policy", str(policy)]
        if self.model:
            argv += ["--model", self.model]
        self.rpc = self.process_factory(argv, cwd=self.workspace, env=env, timeout_s=self.config["timeout_s"])
        response = self.rpc.request(
            "initialize", {"protocolVersion": 1, "clientCapabilities": {}, "clientInfo": {"name": "nuzlocke", "version": "0.1.0"}}
        )
        if not response.get("agentCapabilities", {}).get("promptCapabilities", {}).get("image"):
            raise ProviderError("gemini_cli: installed client does not advertise image support")
        session = self.rpc.request("session/new", {"cwd": str(self.workspace), "mcpServers": []})
        self.session_id = session["sessionId"]
        self.model = session.get("models", {}).get("currentModelId") or self.model

    def _complete(self, prompt, images, role):
        self._start()
        text = []

        def event(message):
            params = message.get("params") or {}
            if message.get("method") != "session/update" or params.get("sessionId") != self.session_id:
                return
            update = params.get("update") or {}
            kind = update.get("sessionUpdate")
            content = update.get("content") or {}
            if kind == "agent_message_chunk" and content.get("type") == "text":
                text.append(content.get("text", ""))
            elif kind == "agent_thought_chunk" and content.get("type") == "text":
                self._thinking(content.get("text", ""), role)
            elif kind == "usage_update":
                self.usage = {k: v for k, v in update.items() if k != "sessionUpdate"}

        content = [{"type": "text", "text": prompt}]
        content += [
            {"type": "image", "mimeType": "image/png", "data": base64.b64encode(Path(p).read_bytes()).decode()} for p in images
        ]
        result = self.rpc.request("session/prompt", {"sessionId": self.session_id, "prompt": content}, on_event=event)
        if result.get("stopReason") != "end_turn":
            raise ProviderError("gemini_cli: turn incomplete; check quota or model access")
        return "".join(text)
