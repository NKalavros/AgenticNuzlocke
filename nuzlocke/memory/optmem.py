"""Durable long-term memory: a capped, append-only notes file.

Holds **long-term** facts only (landmarks, rollups, run meta). Short-term
step history lives in the orchestrator prompt (`recent`), not here.
"""

from __future__ import annotations

from pathlib import Path

_ENTRY_MAX = 280


class OptMem:
    def __init__(
        self,
        memory_dir: Path,
        *,
        wake_lines: int = 48,
        enabled: bool = True,
    ) -> None:
        self.enabled = enabled
        self.memory_dir = memory_dir
        self.wake_lines = max(8, int(wake_lines))
        self.notes_path = self.memory_dir / "notes.log"
        if self.enabled:
            self.memory_dir.mkdir(parents=True, exist_ok=True)
            self.notes_path.touch(exist_ok=True)

    def wake(self) -> str:
        """Return the last ``wake_lines`` durable notes, newest last."""
        if not self.enabled or not self.notes_path.exists():
            return ""
        lines = self.notes_path.read_text(encoding="utf-8").splitlines()
        return "\n".join(lines[-self.wake_lines :]).strip()

    def note(self, text: str) -> str:
        """Append a durable note (landmarks / rollups / rare meta)."""
        if not self.enabled:
            return ""
        cleaned = " ".join(str(text).split())
        if not cleaned:
            return ""
        cleaned = cleaned[:_ENTRY_MAX]
        with self.notes_path.open("a", encoding="utf-8") as f:
            f.write(cleaned + "\n")
        return cleaned
