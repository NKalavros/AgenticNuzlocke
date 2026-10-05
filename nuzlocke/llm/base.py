"""LLM provider interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from nuzlocke.state.models import AgentRole, LLMResponse


class ProviderError(RuntimeError):
    """Sanitized backend failure; the orchestrator must pause before more input."""


class LLMProvider(ABC):
    name: str

    @abstractmethod
    def complete(
        self,
        *,
        role: AgentRole,
        system: str,
        user: str,
        schema_hint: dict[str, Any] | None = None,
        image_paths: list[Path] | None = None,
    ) -> LLMResponse:
        """Return model text; prefer JSON object matching schema_hint."""

    def close(self) -> None:
        return None
