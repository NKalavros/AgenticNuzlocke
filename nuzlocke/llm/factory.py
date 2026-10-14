"""Build independently configured actor and planner backends."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from nuzlocke.llm.base import LLMProvider
from nuzlocke.llm.decisions import APIDecisionProvider, DecisionProvider
from nuzlocke.llm.jev import JevClient
from nuzlocke.llm.openai_provider import OpenAICompatibleProvider, OpenAIResponsesProvider
from nuzlocke.llm.settings import resolve_agents_config


def _api(options: dict):
    cls = OpenAIResponsesProvider if options["provider"] == "openai" else OpenAICompatibleProvider
    keys = "base_url model api_key_env api_key_default temperature timeout_s params max_retries structured_output"
    return cls(**{key: options[key] for key in keys.split()})


def create_provider(agents_cfg: dict[str, Any], workspace: Path, *, on_stream=None, role="system2") -> LLMProvider:
    cfg = resolve_agents_config(agents_cfg)
    options = cfg[role]
    name = options["provider"]
    if name == "cursor":
        from nuzlocke.llm.cursor_provider import CursorProvider

        return CursorProvider(
            model=options["model"],
            model_params=options["params"],
            api_key=os.environ.get(options["api_key_env"]),
            workspace=Path(options["workspace"]) if options["workspace"] and role == "system2" else workspace,
            on_stream=on_stream,
            max_retries=options["max_retries"],
            compact_at_tokens=options["compact_at_tokens"],
            lazy_start=cfg["provider"] == "dual",
        )
    if name == "openai_compatible":
        return _api(options)
    if name == "antigravity":
        from nuzlocke.llm.antigravity_provider import AntigravityProvider

        return AntigravityProvider(config=options, workspace=workspace / name, on_stream=on_stream)
    from nuzlocke.llm.cli_providers import ClaudeCodeProvider, CodexProvider, GeminiCLIProvider

    cls = {"codex": CodexProvider, "claude_code": ClaudeCodeProvider, "gemini_cli": GeminiCLIProvider}[name]
    return cls(config=options, workspace=workspace / name, on_stream=on_stream)


def create_actor(agents_cfg: dict[str, Any], *, workspace: Path | None = None) -> DecisionProvider | None:
    cfg = resolve_agents_config(agents_cfg)
    if cfg["provider"] != "dual":
        return None
    options = cfg["system1"]
    if options["provider"] == "codex":
        from nuzlocke.llm.cli_providers import CodexProvider

        if workspace is None:
            raise ValueError("A run workspace is required for the Codex actor")
        return APIDecisionProvider(CodexProvider(config=options, workspace=workspace / "system1-codex"))
    if options["provider"] != "jev":
        return APIDecisionProvider(_api(options))
    env_name = options["api_key_env"]
    key = os.environ.get(env_name) or os.environ.get("TYPESAFE_API_KEY")
    if not key:
        raise RuntimeError(f"{env_name} is not set. Add it to .env or the environment.")
    return JevClient(
        api_key=key,
        base_url=options["base_url"],
        model=options["model"],
        timeout_s=options["timeout_s"],
        max_retries=options["max_retries"],
    )


# Existing callers and tests can continue using the old factory name.
create_jev = create_actor
