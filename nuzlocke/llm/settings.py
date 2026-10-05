"""Resolve independent actor/planner settings, including legacy configurations."""

from __future__ import annotations

import copy
import os
import shutil
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from nuzlocke.assets import data as asset_data
from nuzlocke.llm.openai_provider import API_RESERVED_PARAMS


class ProviderConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Literal["jev", "cursor", "codex", "claude_code", "gemini_cli", "antigravity", "openai", "openai_compatible"]
    model: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    base_url: str | None = None
    api_key_env: str | None = None
    api_key_default: str = ""
    binary: str | None = None
    timeout_s: float = Field(default=120, gt=0)
    max_retries: int = Field(default=3, ge=1, le=10)
    workspace: str | None = None
    compact_at_tokens: int = Field(default=250_000, ge=0)
    temperature: float | None = None
    structured_output: Literal["json_schema", "json_object", "prompt"] = "json_schema"


DEFAULTS = asset_data("providers.json")


def resolve_agents_config(cfg: dict, overrides: dict | None = None) -> dict:
    result = copy.deepcopy(cfg)
    mode = result.get("provider", "cursor")
    if mode not in {"dual", "cursor", "openai_compatible"}:
        raise ValueError(f"Unknown orchestration provider: {mode}")
    result["provider"] = mode
    for role in ("system1", "system2"):
        if role == "system1":
            legacy = {**(cfg.get("jev") or {}), "provider": "jev"}
        elif mode == "openai_compatible":
            legacy = {"model": "qwen3", **(cfg.get("openai_compatible") or {}), "provider": "openai_compatible"}
        else:
            legacy = {**(cfg.get("cursor") or {}), "provider": "cursor"}
            if mode == "dual":
                for key in ("model", "params"):
                    if key in (cfg.get("planner") or {}):
                        legacy[key] = cfg["planner"][key]
        explicit = cfg.get(role) or {}
        if not isinstance(explicit, dict):
            raise ValueError(f"{role} must be a mapping")  # noqa: TRY004 — CLI configuration error
        values = legacy if explicit.get("provider", legacy["provider"]) == legacy["provider"] else {}
        values = {**values, **explicit}
        override = (overrides or {}).get(role) or {}
        if override.get("provider") and override["provider"] != values.get("provider"):
            values = {"provider": override["provider"]}
        values.update({k: v for k, v in override.items() if v is not None})
        name = values.get("provider")
        try:
            parsed = ProviderConfig.model_validate({**DEFAULTS.get(name, {}), **values})
        except ValidationError as err:
            # ValidationError includes input values; never print credentials or arbitrary params.
            fields = ", ".join(".".join(map(str, item["loc"])) for item in err.errors())
            raise ValueError(f"Invalid {role} configuration fields: {fields}") from None
        allowed = (
            {"jev", "openai", "openai_compatible", "codex"}
            if role == "system1"
            else {"cursor", "codex", "claude_code", "gemini_cli", "antigravity", "openai_compatible"}
        )
        if parsed.provider not in allowed:
            raise ValueError(f"{parsed.provider} is not supported for {role}")
        if role == "system1" and parsed.provider == "codex" and not parsed.model:
            raise ValueError("system1.model is required for codex")
        if parsed.provider in {"openai", "openai_compatible"} and not parsed.model:
            raise ValueError(f"{role}.model is required for {parsed.provider}")
        if parsed.provider in {"codex", "claude_code", "gemini_cli", "antigravity"} and not parsed.binary:
            raise ValueError(f"{role}.binary is required for {parsed.provider}")
        if parsed.provider in {"jev", "openai", "openai_compatible"}:
            if not parsed.base_url or not parsed.api_key_env:
                raise ValueError(f"{role} requires base_url and api_key_env")
            try:
                url = urlsplit(parsed.base_url)
                valid_url = url.scheme in {"http", "https"} and bool(url.hostname)
                embedded_secret = bool(url.username or url.password or url.query or url.fragment)
            except ValueError:
                valid_url, embedded_secret = False, False
            if not valid_url or embedded_secret:
                raise ValueError(f"{role}.base_url must be an HTTP(S) URL without credentials, query, or fragment")
        if parsed.provider in {"openai", "openai_compatible"} and parsed.params.keys() & (
            API_RESERVED_PARAMS | {"api_key", "authorization", "headers"}
        ):
            raise ValueError(f"{role}: params cannot override input, authentication, tools, or output format")
        if parsed.provider in {"codex", "claude_code", "antigravity"} and set(parsed.params) - {"reasoning_effort"}:
            raise ValueError(f"{role}: {parsed.provider} params supports only reasoning_effort")
        if parsed.provider == "antigravity" and parsed.params.get("reasoning_effort") not in (None, "low", "medium", "high", "max"):
            raise ValueError(f"{role}: antigravity reasoning_effort must be low, medium, high, or max")
        if parsed.provider == "gemini_cli" and parsed.params:
            raise ValueError(f"{role}: gemini_cli uses --model; params must be empty")
        result[role] = parsed.model_dump()
    return result


def preflight(cfg: dict) -> None:
    """Check local setup before starting an emulator; never call inference."""
    roles = ("system1", "system2") if cfg["provider"] == "dual" else ("system2",)
    for role in roles:
        options = cfg[role]
        binary = options.get("binary")
        if binary and not shutil.which(binary):
            raise RuntimeError(f"{role}: executable {binary!r} not found. Install the vendor CLI or set binary.")
        name = options["provider"]
        if name in {"jev", "openai", "openai_compatible"}:
            key = os.environ.get(options["api_key_env"] or "")
            if name == "jev":
                key = key or os.environ.get("TYPESAFE_API_KEY")
            if not key and not options.get("api_key_default"):
                raise RuntimeError(f"{role}: {options['api_key_env']} is not set. Add it to .env or the environment.")


def provider_identity(cfg: dict) -> dict:
    """Non-secret settings that determine which planner produced a plan."""
    return {k: cfg.get(k) for k in ("provider", "model", "params", "base_url", "binary")}
