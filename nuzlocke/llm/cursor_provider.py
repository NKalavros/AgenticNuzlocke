"""Cursor SDK provider (Composer 2.5 by default)."""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from cursor_sdk import (
    Agent,
    AgentOptions,
    CursorAgentError,
    LocalAgentOptions,
    ModelParameterValue,
    ModelSelection,
    SDKImage,
    SDKImageDimension,
    SendOptions,
    UserMessage,
)

from nuzlocke.llm.base import LLMProvider
from nuzlocke.llm.json_util import extract_json_object
from nuzlocke.state.models import AgentRole, LLMResponse

_COMPACT_PROMPT = """\
You are compacting the conversation for a Pokemon Red vision agent.
Reply with ONLY JSON: {"summary":"..."}.
Max 500 characters. Keep: current goal, what the screen has been showing,
what was tried, what clearly failed. Invent nothing.
"""


def _is_bridge_down(err: BaseException) -> bool:
    text = str(err).lower()
    return (
        "connection refused" in text
        or "connecterror" in text
        or "bridge request failed" in text
    )


class CursorProvider(LLMProvider):
    """Role calls via one long-lived local Cursor agent.

    Follow-up ``send`` keeps conversation context. Every ``compact_every``
    successful turns we ask for a short text summary (no screenshot), then
    recreate the agent and carry that summary forward — bounds token growth
    without thrashing the bridge every prompt.
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
        compact_every: int = 20,
    ) -> None:
        self.model = model
        self.model_params = model_params or {}
        self.api_key = api_key or os.environ.get("CURSOR_API_KEY")
        if not self.api_key:
            raise RuntimeError(
                "CURSOR_API_KEY is not set. Export it or put it in the environment."
            )
        self.workspace = workspace
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.on_stream = on_stream
        self.max_retries = max(1, int(max_retries))
        self.compact_every = max(0, int(compact_every))
        self._turns_on_agent = 0
        self._session_summary = ""
        self._last_stream_push = 0.0
        self._agent = self._create_agent()

    def _selection(self) -> ModelSelection:
        return ModelSelection(
            id=self.model,
            params=[
                ModelParameterValue(id=k, value=str(v))
                for k, v in self.model_params.items()
            ]
            or None,
        )

    def _create_agent(self) -> Any:
        return Agent.create(
            AgentOptions(
                model=self._selection(),
                api_key=self.api_key,
                local=LocalAgentOptions(cwd=str(self.workspace)),
            )
        )

    def _recreate_agent(self) -> None:
        try:
            self._agent.close()
        except Exception:
            pass
        self._agent = self._create_agent()
        self._turns_on_agent = 0

    def _build_prompt(
        self,
        *,
        role: AgentRole,
        system: str,
        user: str,
        schema_hint: dict[str, Any] | None,
    ) -> str:
        schema_text = (
            json.dumps(schema_hint, separators=(",", ":"))
            if schema_hint
            else "a JSON object"
        )
        has_walkthrough_hint = '"walkthrough_hint"' in user
        if has_walkthrough_hint:
            skill_rule = (
                "- A walkthrough_hint is already in the user payload — follow it. "
                "Do NOT Read skill files or browse the repo."
            )
        else:
            skill_rule = (
                "- Do NOT browse the repo. Stay JSON-only "
                "(orchestrator injects walkthrough excerpts when stuck)."
            )
        summary_block = ""
        if self._session_summary.strip():
            summary_block = (
                f"\nSession summary (compacted earlier):\n"
                f"{self._session_summary.strip()}\n"
            )
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
        self,
        message: Any,
        *,
        role: AgentRole,
        force: bool = False,
    ) -> tuple[Any, list[str]]:
        chunks: list[str] = []
        send_opts = SendOptions(local={"force": True}) if force else None
        run = (
            self._agent.send(message, send_opts)
            if send_opts is not None
            else self._agent.send(message)
        )
        for event in run.stream():
            text = _stream_text(event)
            if not text:
                continue
            chunks.append(text)
            if self.on_stream and len(text.strip()) > 0:
                now = time.time()
                if now - self._last_stream_push < 0.5:
                    continue
                self._last_stream_push = now
                snippet = text.strip().replace("\n", " ")
                if len(snippet) > 220:
                    snippet = snippet[:217] + "…"
                self.on_stream(f"[{role.value}] {snippet}")
        result = run.wait()
        return result, chunks

    def _compact_and_reset(self) -> None:
        """Ask the live agent for a short summary, then start a fresh agent."""
        if self.on_stream:
            self.on_stream("[cursor] compacting session context…")
        try:
            result, chunks = self._run_send(_COMPACT_PROMPT, role=AgentRole.DIRECTOR)
            text = (result.result if result else None) or "".join(chunks)
            parsed = extract_json_object(text) or {}
            summary = str(parsed.get("summary") or "").strip()
            if summary:
                self._session_summary = summary[:500]
                if self.on_stream:
                    self.on_stream(f"[cursor] compacted: {self._session_summary[:120]}")
        except Exception as err:
            if self.on_stream:
                self.on_stream(f"[cursor] compact failed (keeping agent): {err}")
            return
        try:
            self._recreate_agent()
        except Exception as err:
            if self.on_stream:
                self.on_stream(f"[cursor] recreate after compact failed: {err}")

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
        (inbox / "request.json").write_text(
            json.dumps(payload, indent=2), encoding="utf-8"
        )
        prompt_text = self._build_prompt(
            role=role, system=system, user=user, schema_hint=schema_hint
        )
        images: list[SDKImage] = []
        for path in image_paths or []:
            if path and Path(path).exists():
                images.append(
                    SDKImage.from_file(
                        str(path),
                        dimension=SDKImageDimension(width=160, height=144),
                    )
                )
        message: Any = (
            UserMessage(text=prompt_text, images=images)
            if images
            else prompt_text
        )
        if self.on_stream:
            param_bits = ",".join(f"{k}={v}" for k, v in self.model_params.items())
            label = f"{self.model}[{param_bits}]" if param_bits else self.model
            vision = f" +{len(images)} image(s)" if images else ""
            self.on_stream(f"[{role.value}] thinking with {label}{vision}…")

        last_err: Exception | None = None
        result = None
        chunks: list[str] = []
        for attempt in range(self.max_retries):
            chunks = []
            try:
                result, chunks = self._run_send(
                    message, role=role, force=bool(attempt)
                )
            except CursorAgentError as err:
                last_err = err
                if self.on_stream:
                    self.on_stream(
                        f"[{role.value}] startup error "
                        f"(retry {attempt + 1}/{self.max_retries}): {err}"
                    )
                if attempt < self.max_retries - 1:
                    delay = (
                        4.0 * (attempt + 1)
                        if _is_bridge_down(err)
                        else 1.5 * (attempt + 1)
                    )
                    try:
                        self._recreate_agent()
                    except Exception as recreate_err:
                        last_err = recreate_err  # type: ignore[assignment]
                    time.sleep(delay)
                    continue
                raise RuntimeError(
                    f"Cursor agent startup failed: {err} "
                    f"(retryable={getattr(err, 'is_retryable', None)})"
                ) from err
            except Exception as err:
                last_err = err
                if self.on_stream:
                    self.on_stream(
                        f"[{role.value}] error "
                        f"(retry {attempt + 1}/{self.max_retries}): {err}"
                    )
                if attempt < self.max_retries - 1:
                    delay = (
                        4.0 * (attempt + 1)
                        if _is_bridge_down(err)
                        else 1.5 * (attempt + 1)
                    )
                    try:
                        self._recreate_agent()
                    except Exception:
                        pass
                    time.sleep(delay)
                    continue
                raise RuntimeError(f"Cursor agent failed: {err}") from err

            if result is not None and result.status != "error":
                break
            last_err = RuntimeError(
                f"Cursor run failed: {getattr(result, 'id', '?')}"
            )
            if self.on_stream:
                self.on_stream(
                    f"[{role.value}] run error, "
                    f"retry {attempt + 1}/{self.max_retries}…"
                )
            if attempt < self.max_retries - 1:
                self._recreate_agent()
                time.sleep(1.25 * (attempt + 1))
        else:
            if isinstance(last_err, CursorAgentError):
                raise RuntimeError(
                    f"Cursor agent startup failed: {last_err} "
                    f"(retryable={getattr(last_err, 'is_retryable', None)})"
                ) from last_err
            raise RuntimeError(str(last_err) if last_err else "Cursor run failed")

        assert result is not None
        text = result.result or "".join(chunks)
        parsed = extract_json_object(text)
        usage = None
        if getattr(result, "usage", None) is not None:
            u = result.usage
            usage = {
                "input_tokens": getattr(u, "input_tokens", None),
                "output_tokens": getattr(u, "output_tokens", None),
                "total_tokens": getattr(u, "total_tokens", None),
            }
        resp = LLMResponse(
            role=role,
            raw_text=text,
            parsed=parsed,
            model=self.model
            + (
                "["
                + ",".join(f"{k}={v}" for k, v in self.model_params.items())
                + "]"
                if self.model_params
                else ""
            ),
            provider=self.name,
            usage=usage,
        )

        self._turns_on_agent += 1
        if self.compact_every > 0 and self._turns_on_agent >= self.compact_every:
            self._compact_and_reset()
        return resp

    def close(self) -> None:
        try:
            self._agent.close()
        except Exception:
            pass


def _stream_text(event: Any) -> str:
    etype = getattr(event, "type", None)
    if etype == "assistant":
        message = getattr(event, "message", None)
        content = getattr(message, "content", None) or []
        parts: list[str] = []
        for block in content:
            if getattr(block, "type", None) == "text":
                parts.append(getattr(block, "text", "") or "")
        return "".join(parts)
    if etype == "thinking":
        return getattr(event, "text", "") or ""
    if etype == "tool_call":
        name = getattr(event, "name", "tool")
        status = getattr(event, "status", "")
        return f"(tool {name} {status})"
    return ""
