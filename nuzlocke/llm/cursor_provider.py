"""Cursor SDK provider (Composer 2.5 by default)."""

from __future__ import annotations

import contextlib
import json
import os
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
from cursor_sdk import (
    Agent,
    AgentOptions,
    Bridge,
    Client,
    CursorAgentError,
    LocalAgentOptions,
    ModelParameterValue,
    ModelSelection,
    SDKImage,
    SDKImageDimension,
    SendOptions,
    UserMessage,
)

from nuzlocke.config import ensure_relay_routing
from nuzlocke.llm.base import LLMProvider
from nuzlocke.llm.json_util import extract_json_object
from nuzlocke.state.models import AgentRole, LLMResponse


def install_bridge_token_guard() -> None:
    """Keep SDK callback auth tokens from starting with ``-``.

    The bridge parses any argument starting with ``-`` as a flag, so
    ``--tool-callback-auth-token`` then exits before discovery.
    """
    import cursor_sdk._store_callback as store_cb
    import cursor_sdk._tool_callback as tool_cb

    def guard(generate: Callable[[], str]) -> Callable[[], str]:
        def wrapped() -> str:
            for _ in range(8):
                token = generate()
                if token and not str(token).startswith("-"):
                    return str(token)
            return "t" + str(generate()).lstrip("-")

        return wrapped

    tool_cb._new_auth_token = guard(tool_cb._new_auth_token)
    store_cb._new_auth_token = guard(store_cb._new_auth_token)


_COMPACT_PROMPT = """\
You are compacting the conversation for a Pokemon Red vision agent.
Reply with ONLY JSON: {"summary":"..."}.
Max 500 characters. Keep: current goal, what the screen has been showing,
what was tried, what clearly failed. Invent nothing.
"""

_BRIDGE_DOWN_MARKERS = ("connection refused", "connecterror", "bridge request failed")
_USAGE_KEYS = ("input_tokens", "output_tokens", "total_tokens")


def _is_bridge_down(err: BaseException) -> bool:
    text = str(err).lower()
    return any(marker in text for marker in _BRIDGE_DOWN_MARKERS)


def _close_quietly(resource: Any) -> None:
    if resource is not None:
        with contextlib.suppress(Exception):
            resource.close()


class CursorProvider(LLMProvider):
    """Role calls via one long-lived local Cursor agent.

    When reported (or estimated) input context reaches ``compact_at_tokens``, the
    agent is asked for a short summary and recreated with that summary carried forward.
    """

    name = "cursor"

    def __init__(
        self,
        *,
        model: str = "composer-2.5",
        model_params: dict[str, str] | None = None,
        api_key: str | None = None,
        workspace: Path,
        on_stream: Callable[[str], None] | None = None,
        max_retries: int = 5,
        compact_at_tokens: int = 250_000,
        lazy_start: bool = False,
    ) -> None:
        self.model = model
        self.model_params = model_params or {}
        self.api_key = api_key or os.environ.get("CURSOR_API_KEY")
        if not self.api_key:
            raise RuntimeError("CURSOR_API_KEY is not set. Export it or put it in the environment.")
        self.workspace = workspace
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.on_stream = on_stream
        self.max_retries = max(1, int(max_retries))
        self.compact_at_tokens = max(0, int(compact_at_tokens))
        self._session_summary = ""
        self._est_context_tokens = 0
        self._last_stream_push = 0.0
        self._bridge: Bridge | None = None
        self._client: Client | None = None
        self._http: httpx.Client | None = None
        self._bridge_lines: list[str] = []
        try:
            self._agent: Any = None if lazy_start else self._create_agent()
        except Exception:
            self._shutdown_bridge()
            raise

    def _emit(self, text: str) -> None:
        if self.on_stream:
            self.on_stream(text)

    def _bridge_alive(self) -> bool:
        proc = getattr(self._bridge, "process", None)
        return proc is not None and proc.poll() is None

    def _ensure_client(self) -> Client:
        """Talk to the local bridge directly. Its own fetch uses gost."""
        if self._client is not None and self._bridge_alive():
            return self._client
        self._shutdown_bridge()
        ensure_relay_routing()
        install_bridge_token_guard()
        bridge = Bridge.launch(workspace=str(self.workspace))
        self._bridge = bridge
        # The SDK stops reading stderr after discovery. A full pipe blocks the
        # bridge, and the next RPC then fails with connection refused.
        threading.Thread(target=self._drain_bridge_stderr, daemon=True).start()
        self._http = httpx.Client(trust_env=False, timeout=60.0)
        self._client = Client(bridge.endpoint, http_client=self._http)
        return self._client

    def _drain_bridge_stderr(self) -> None:
        stderr = getattr(getattr(self._bridge, "process", None), "stderr", None)
        if stderr is None:
            return
        for line in stderr:
            text = line.strip()
            if text:
                self._bridge_lines.append(text)
                del self._bridge_lines[:-30]

    def _bridge_hint(self) -> str:
        state = "up" if self._bridge_alive() else "down"
        tail = " | ".join(self._bridge_lines[-3:])[-300:]
        return f" (bridge {state}: {tail})" if tail else f" (bridge {state})"

    def _shutdown_bridge(self) -> None:
        bridge, http = self._bridge, self._http
        self._bridge = self._client = self._http = None
        _close_quietly(bridge)
        _close_quietly(http)

    def _create_agent(self) -> Any:
        params = [ModelParameterValue(id=k, value=str(v)) for k, v in self.model_params.items()]
        options = AgentOptions(
            model=ModelSelection(id=self.model, params=params or None),
            api_key=self.api_key,
            local=LocalAgentOptions(cwd=str(self.workspace)),
        )
        return Agent.create(options, client=self._ensure_client())

    def _recreate_agent(self) -> None:
        _close_quietly(self._agent)
        self._agent = self._create_agent()
        self._est_context_tokens = len(self._session_summary) // 4

    def _build_prompt(
        self, *, role: AgentRole, system: str, user: str, schema_hint: dict[str, Any] | None
    ) -> str:
        schema_text = (
            json.dumps(schema_hint, separators=(",", ":")) if schema_hint else "a JSON object"
        )
        if '"walkthrough_hint"' in user:
            skill_rule = (
                "- A walkthrough_hint is already in the user payload — follow it. "
                "Do NOT Read skill files or browse the repo."
            )
        else:
            skill_rule = (
                "- Do NOT browse the repo. Stay JSON-only "
                "(orchestrator injects walkthrough excerpts when stuck)."
            )
        summary = self._session_summary.strip()
        summary_block = f"\nSession summary (compacted earlier):\n{summary}\n" if summary else ""
        return f"""You are the Nuzlocke '{role.value}' role agent.

Rules:
- The attached screenshot is ground truth. Prefer it over RAM JSON if they disagree.
- Do NOT edit project source files or change the emulator.
{skill_rule}
- Reply with ONLY a single JSON object matching this schema (no markdown prose):
{schema_text}
{summary_block}
System instructions:
{system}

User / observation:
{user}
"""

    def _run_send(
        self, message: Any, *, role: AgentRole, force: bool = False
    ) -> tuple[Any, list[str]]:
        if self._agent is None:
            self._agent = self._create_agent()
        if force:
            run = self._agent.send(message, SendOptions(local={"force": True}))
        else:
            run = self._agent.send(message)
        chunks: list[str] = []
        for event in run.stream():
            text = _stream_text(event)
            if not text:
                continue
            chunks.append(text)
            now = time.time()
            if self.on_stream and text.strip() and now - self._last_stream_push >= 0.5:
                self._last_stream_push = now
                snippet = text.strip().replace("\n", " ")
                if len(snippet) > 220:
                    snippet = snippet[:217] + "…"
                self.on_stream(f"[{role.value}] {snippet}")
        return run.wait(), chunks

    def _send_with_retries(self, message: Any, role: AgentRole) -> tuple[Any, list[str]]:
        for attempt in range(1, self.max_retries + 1):
            retry = f"retry {attempt}/{self.max_retries}"
            try:
                result, chunks = self._run_send(message, role=role, force=attempt > 1)
            except Exception as err:
                startup = isinstance(err, CursorAgentError)
                kind = "startup error" if startup else "error"
                self._emit(f"[{role.value}] {kind} ({retry}): {err}")
                if attempt == self.max_retries:
                    if startup:
                        retryable = getattr(err, "is_retryable", None)
                        failure = f"Cursor agent startup failed: {err} (retryable={retryable})"
                    else:
                        failure = f"Cursor agent failed: {err}"
                    raise RuntimeError(failure + self._bridge_hint()) from err
                with contextlib.suppress(Exception):
                    self._recreate_agent()
                time.sleep((4.0 if _is_bridge_down(err) else 1.5) * attempt)
                continue
            if result is not None and result.status != "error":
                return result, chunks
            self._emit(f"[{role.value}] run error, {retry}…")
            if attempt < self.max_retries:
                self._recreate_agent()
                time.sleep(1.25 * attempt)
        raise RuntimeError(f"Cursor run failed: {getattr(result, 'id', '?')}")

    def _compact_and_reset(self) -> None:
        """Ask the live agent for a short summary, then start a fresh agent."""
        self._emit("[cursor] compacting session context…")
        try:
            result, chunks = self._run_send(_COMPACT_PROMPT, role=AgentRole.DIRECTOR)
            text = (result.result if result else None) or "".join(chunks)
            parsed = extract_json_object(text) or {}
            summary = str(parsed.get("summary") or "").strip()
            if summary:
                self._session_summary = summary[:500]
                self._emit(f"[cursor] compacted: {self._session_summary[:120]}")
        except Exception as err:
            self._emit(f"[cursor] compact failed (keeping agent): {err}")
            return
        try:
            self._recreate_agent()
        except Exception as err:
            self._emit(f"[cursor] recreate after compact failed: {err}")

    def complete(
        self,
        *,
        role: AgentRole,
        system: str,
        user: str,
        schema_hint: dict[str, Any] | None = None,
        image_paths: list[Path] | None = None,
    ) -> LLMResponse:
        inbox = self.workspace / "inbox"
        inbox.mkdir(exist_ok=True)
        payload = {
            "role": role.value,
            "system": system,
            "user": user,
            "schema": schema_hint,
            "images": [str(p) for p in (image_paths or [])],
            "session_summary": self._session_summary or None,
        }
        (inbox / "request.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
        prompt_text = self._build_prompt(
            role=role, system=system, user=user, schema_hint=schema_hint
        )
        images = [_sdk_image(p) for p in image_paths or [] if p and Path(p).exists()]
        message: Any = UserMessage(text=prompt_text, images=images) if images else prompt_text
        params = ",".join(f"{k}={v}" for k, v in self.model_params.items())
        label = f"{self.model}[{params}]" if params else self.model
        vision = f" +{len(images)} image(s)" if images else ""
        self._emit(f"[{role.value}] thinking with {label}{vision}…")

        result, chunks = self._send_with_retries(message, role)
        text = result.result or "".join(chunks)
        usage = None
        if getattr(result, "usage", None) is not None:
            usage = {key: getattr(result.usage, key, None) for key in _USAGE_KEYS}
        resp = LLMResponse(
            role=role,
            raw_text=text,
            parsed=extract_json_object(text),
            model=label,
            provider=self.name,
            usage=usage,
        )

        try:
            context_tokens = int((usage or {}).get("input_tokens"))
        except (TypeError, ValueError):
            context_tokens = 0
        if context_tokens <= 0:
            # Usage missing: grow a rough estimate (chars / 4, ~1120 tokens per
            # 160x144 image) so compaction still fires.
            self._est_context_tokens += len(prompt_text) // 4 + 1120 * len(images)
            context_tokens = self._est_context_tokens
        if context_tokens > 0:
            self._emit(
                f"[cursor] context≈{context_tokens} tokens "
                f"(compact≥{self.compact_at_tokens or 'off'})"
            )
        if 0 < self.compact_at_tokens <= context_tokens:
            self._compact_and_reset()
        return resp

    def close(self) -> None:
        _close_quietly(self._agent)
        self._shutdown_bridge()


def _sdk_image(path: Path | str) -> SDKImage:
    """Attach a frame at its real pixel size: 160x144 native, or the 4x grid overlay."""
    try:
        from PIL import Image

        with Image.open(path) as img:
            width, height = img.size
    except Exception:
        width, height = 160, 144
    return SDKImage.from_file(str(path), dimension=SDKImageDimension(width=width, height=height))


def _stream_text(event: Any) -> str:
    etype = getattr(event, "type", None)
    if etype == "assistant":
        content = getattr(getattr(event, "message", None), "content", None) or []
        return "".join(
            getattr(block, "text", "") or ""
            for block in content
            if getattr(block, "type", None) == "text"
        )
    if etype == "thinking":
        return getattr(event, "text", "") or ""
    if etype == "tool_call":
        return f"(tool {getattr(event, 'name', 'tool')} {getattr(event, 'status', '')})"
    return ""
