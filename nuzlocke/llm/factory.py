"""Build the configured LLM provider."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from nuzlocke.llm.base import LLMProvider
from nuzlocke.llm.cursor_provider import CursorProvider
from nuzlocke.llm.jev import JevClient
from nuzlocke.llm.openai_provider import OpenAICompatibleProvider


def create_provider(
    agents_cfg: dict[str, Any], workspace: Path, *, on_stream: Any | None = None
) -> LLMProvider:
    provider = agents_cfg.get("provider", "cursor")
    cur = agents_cfg.get("cursor") or {}
    if provider in ("cursor", "dual"):
        model = cur.get("model", "composer-2.5")
        params = cur.get("params") or {}
        if provider == "dual":
            # System 2: the same Cursor vision agent, on the planner's model.
            planner = agents_cfg.get("planner") or {}
            model = planner.get("model") or cur.get("model", "grok-4.7")
            if planner.get("params") is not None:
                params = planner["params"]
        ws = cur.get("workspace")
        return CursorProvider(
            model=model,
            model_params=dict(params or {}),
            api_key=os.environ.get(cur.get("api_key_env", "CURSOR_API_KEY")),
            workspace=Path(ws) if ws else workspace,
            on_stream=on_stream,
            max_retries=int(cur.get("max_retries", 5)),
            compact_at_tokens=int(cur.get("compact_at_tokens", 250_000)),
            lazy_start=provider == "dual",
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


def create_jev(agents_cfg: dict[str, Any]) -> JevClient | None:
    """System 1 actor. Only constructed for ``provider: dual``."""
    if agents_cfg.get("provider") != "dual":
        return None
    jev = agents_cfg.get("jev") or {}
    env_name = str(jev.get("api_key_env") or "JEV_API_KEY")
    api_key = os.environ.get(env_name) or os.environ.get("TYPESAFE_API_KEY")
    if not api_key:
        raise RuntimeError(f"{env_name} is not set. Add it to .env or the environment.")
    return JevClient(
        api_key=api_key,
        base_url=str(jev.get("base_url") or "https://api.typesafe.ai"),
        model=str(jev.get("model") or "jev-latest"),
        timeout_s=float(jev.get("timeout_s", 8)),
        max_retries=int(jev.get("max_retries", 3)),
    )
