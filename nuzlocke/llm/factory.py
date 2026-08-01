"""Build the configured LLM provider."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from nuzlocke.llm.base import LLMProvider
from nuzlocke.llm.cursor_provider import CursorProvider
from nuzlocke.llm.openai_provider import OpenAICompatibleProvider


def create_provider(
    agents_cfg: dict[str, Any],
    workspace: Path,
    *,
    on_stream: Any | None = None,
) -> LLMProvider:
    provider = agents_cfg.get("provider", "cursor")
    if provider == "cursor":
        cur = agents_cfg.get("cursor") or {}
        api_key_env = cur.get("api_key_env", "CURSOR_API_KEY")
        ws = cur.get("workspace")
        # compact_every preferred; refresh_every kept as legacy alias.
        compact = cur.get("compact_every", cur.get("refresh_every", 20))
        return CursorProvider(
            model=cur.get("model", "composer-2.5"),
            model_params=dict(cur.get("params") or {}),
            api_key=os.environ.get(api_key_env),
            workspace=Path(ws) if ws else workspace,
            on_stream=on_stream,
            max_retries=int(cur.get("max_retries", 5)),
            compact_every=int(compact),
        )
    if provider == "openai_compatible":
        oai = agents_cfg.get("openai_compatible") or {}
        return OpenAICompatibleProvider(
            base_url=oai.get("base_url", "http://127.0.0.1:8000/v1"),
            model=oai.get("model", "qwen3"),
            api_key_env=oai.get("api_key_env", "OPENAI_API_KEY"),
            api_key_default=oai.get("api_key_default", "not-needed"),
            temperature=float(oai.get("temperature", 0.2)),
            timeout_s=float(oai.get("timeout_s", 120)),
        )
    raise ValueError(f"Unknown LLM provider: {provider}")
