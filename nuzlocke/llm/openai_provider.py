"""API-key transports for OpenAI Responses and Chat Completions endpoints."""

from __future__ import annotations

import base64
import json
import os
import time
from pathlib import Path
from typing import Any

import httpx

from nuzlocke.llm.base import LLMProvider, ProviderError
from nuzlocke.llm.json_util import extract_json_object
from nuzlocke.state.models import AgentRole, LLMResponse

API_RESERVED_PARAMS = {"model", "messages", "input", "instructions", "tools", "stream", "text", "response_format", "store"}


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
        temperature: float | None = None,
        timeout_s: float = 120,
        params: dict | None = None,
        max_retries: int = 3,
        structured_output: str = "prompt",
        transport=None,
        sleep=time.sleep,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key or os.environ.get(api_key_env) or api_key_default
        self.params = dict(params or {})
        if self.params.keys() & API_RESERVED_PARAMS:
            raise ValueError("API params cannot override model, input, tools, or output format")
        if temperature is not None:
            self.params["temperature"] = temperature
        self.max_retries = max_retries
        self.structured_output = structured_output
        self._sleep = sleep
        self._client = httpx.Client(timeout=timeout_s, transport=transport)

    def _post(self, path: str, body: dict) -> dict:
        for attempt in range(self.max_retries):
            try:
                response = self._client.post(
                    f"{self.base_url}/{path}", headers={"Authorization": f"Bearer {self.api_key}"}, json=body
                )
            except httpx.TransportError:
                if attempt + 1 == self.max_retries:
                    raise ProviderError(f"{self.name}: connection failed or timed out") from None
                self._sleep(min(0.25 * 2**attempt, 4))
                continue
            if response.status_code in {429, 500, 502, 503, 504, 529} and attempt + 1 < self.max_retries:
                try:
                    delay = float(response.headers.get("retry-after", 0.25 * 2**attempt))
                except ValueError:
                    delay = 1.0
                self._sleep(min(max(delay, 0), 8))
                continue
            if response.is_error:
                raise ProviderError(f"{self.name}: HTTP {response.status_code}; check credentials, model access, or quota")
            try:
                data = response.json()
                if isinstance(data, dict):
                    return data
            except ValueError:
                pass
            raise ProviderError(f"{self.name}: response was not a JSON object")
        raise ProviderError(f"{self.name}: retries exhausted")

    def _generate(self, system: str, user: str, schema: dict | None = None, image_paths=None):
        content: Any = user
        if image_paths:
            content = [{"type": "text", "text": user}]
            for path in image_paths:
                content.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": "data:image/png;base64," + base64.b64encode(Path(path).read_bytes()).decode()},
                    }
                )
        body = {
            **self.params,
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": content}],
        }
        if schema and self.structured_output == "json_schema":
            body["response_format"] = {"type": "json_schema", "json_schema": {"name": "decision", "strict": True, "schema": schema}}
        elif schema and self.structured_output == "json_object":
            body["response_format"] = {"type": "json_object"}
        data = self._post("chat/completions", body)
        try:
            choice = data["choices"][0]
            if choice.get("finish_reason") not in (None, "stop") or choice["message"].get("refusal"):
                raise ValueError
            text = choice["message"]["content"]
            if not isinstance(text, str) or not text.strip():
                raise ValueError
        except (KeyError, IndexError, TypeError, ValueError):
            raise ProviderError(f"{self.name}: incomplete, refused, or missing text response") from None
        return text, data.get("usage")

    def structured(self, *, system: str, user: str, schema: dict):
        text, usage = self._generate(system + "\nJSON schema:\n" + json.dumps(schema), user, schema)
        parsed = extract_json_object(text)
        if not isinstance(parsed, dict):
            raise ProviderError(f"{self.name}: invalid structured response")
        return parsed, usage

    def complete(
        self, *, role: AgentRole, system: str, user: str, schema_hint: dict | None = None, image_paths: list[Path] | None = None
    ) -> LLMResponse:
        text, usage = self._generate(
            system + "\nReturn ONLY a JSON object matching this example:\n" + json.dumps(schema_hint or {}),
            user,
            image_paths=image_paths,
        )
        return LLMResponse(
            role=role, raw_text=text, parsed=extract_json_object(text), model=self.model, provider=self.name, usage=usage
        )

    def close(self) -> None:
        self._client.close()


class OpenAIResponsesProvider(OpenAICompatibleProvider):
    name = "openai"

    def _generate(self, system: str, user: str, schema: dict | None = None, image_paths=None):
        body = {
            **self.params,
            "model": self.model,
            "instructions": system,
            "input": [{"role": "user", "content": user}],
            "store": False,
        }
        if schema:
            body["text"] = {"format": {"type": "json_schema", "name": "decision", "strict": True, "schema": schema}}
        data = self._post("responses", body)
        if data.get("status") not in (None, "completed"):
            raise ProviderError("openai: response did not complete")
        try:
            content = [part for item in data["output"] if item.get("type") == "message" for part in item.get("content", [])]
            if any(part.get("type") == "refusal" for part in content):
                raise ValueError
            text = "".join(part["text"] for part in content if part.get("type") == "output_text")
            if not text.strip():
                raise ValueError
        except (KeyError, TypeError, ValueError):
            raise ProviderError("openai: refused or missing output text") from None
        return text, data.get("usage")
