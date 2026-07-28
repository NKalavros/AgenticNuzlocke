"""OpenAI-compatible provider for local Qwen / vLLM / Ollama later."""

from __future__ import annotations

import json
import os
from typing import Any

import httpx

from nuzlocke.llm.base import LLMProvider
from nuzlocke.llm.json_util import extract_json_object
from nuzlocke.state.models import AgentRole, LLMResponse


class OpenAICompatibleProvider(LLMProvider):
    name = "openai_compatible"

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str | None = None,
        api_key_env: str = "OPENAI_API_KEY",
        api_key_default: str = "not-needed",
        temperature: float = 0.2,
        timeout_s: float = 120.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key or os.environ.get(api_key_env) or api_key_default
        self.temperature = temperature
        self.timeout_s = timeout_s
        self._client = httpx.Client(timeout=timeout_s)

    def complete(
        self,
        *,
        role: AgentRole,
        system: str,
        user: str,
        schema_hint: dict[str, Any] | None = None,
        image_paths: list | None = None,
    ) -> LLMResponse:
        schema_text = (
            json.dumps(schema_hint, indent=2)
            if schema_hint
            else "a JSON object"
        )
        note = ""
        if image_paths:
            note = (
                "\n(Screenshot paths were provided but this OpenAI-compatible "
                "text endpoint ignores images for now.)\n"
            )
        messages = [
            {
                "role": "system",
                "content": (
                    f"{system}\n\nRespond with ONLY JSON matching:\n{schema_text}"
                ),
            },
            {"role": "user", "content": note + user},
        ]
        resp = self._client.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": self.model,
                "temperature": self.temperature,
                "messages": messages,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        text = data["choices"][0]["message"]["content"] or ""
        usage = data.get("usage")
        return LLMResponse(
            role=role,
            raw_text=text,
            parsed=extract_json_object(text),
            model=self.model,
            provider=self.name,
            usage=usage,
        )

    def close(self) -> None:
        self._client.close()
