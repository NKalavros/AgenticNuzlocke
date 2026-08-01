from pathlib import Path

from nuzlocke.agents.roles import rollup_memory
from nuzlocke.llm.base import LLMProvider
from nuzlocke.state.models import AgentRole, LLMResponse


class FakeLLM(LLMProvider):
    name = "fake"

    def __init__(self, notes: list[str]) -> None:
        self.notes = notes
        self.calls = 0
        self.last_images: list[Path] | None = None

    def complete(
        self,
        *,
        role: AgentRole,
        system: str,
        user: str,
        schema_hint: dict | None = None,
        image_paths: list[Path] | None = None,
    ) -> LLMResponse:
        self.calls += 1
        self.last_images = image_paths
        return LLMResponse(
            role=role,
            raw_text="{}",
            parsed={"notes": self.notes},
            model="fake",
            provider=self.name,
        )


def test_rollup_memory_text_only():
    llm = FakeLLM(["goal: oak lab", "LANDMARK stairs south"])
    notes = rollup_memory(llm, memory="step1 walk up noop\nstep2 walk down")
    assert notes == ["goal: oak lab", "LANDMARK stairs south"]
    assert llm.calls == 1
    assert llm.last_images is None


def test_rollup_memory_empty_wake():
    llm = FakeLLM(["should not call"])
    assert rollup_memory(llm, memory="   ") == []
    assert llm.calls == 0
