"""Durable long-term memory: a capped, append-only notes file.

Long-term facts only (landmarks, rollups, run meta). Short-term step history lives in the
orchestrator prompt (`recent`), not here.
"""

from __future__ import annotations

from pathlib import Path

_ENTRY_MAX = 280


def _normalized(line: str) -> str:
    return " ".join(line.lower().split())


class OptMem:
    def __init__(self, memory_dir: Path, *, wake_lines: int = 48, enabled: bool = True) -> None:
        self.enabled = enabled
        self.memory_dir = memory_dir
        self.wake_lines = max(8, int(wake_lines))
        self.notes_path = self.memory_dir / "notes.log"
        if self.enabled:
            self.memory_dir.mkdir(parents=True, exist_ok=True)
            self.notes_path.touch(exist_ok=True)

    def _recent_lines(self) -> list[str]:
        if not self.notes_path.exists():
            return []
        return self.notes_path.read_text(encoding="utf-8").splitlines()[-self.wake_lines :]

    def wake(self) -> str:
        """Return the last ``wake_lines`` durable notes, newest last."""
        return "\n".join(self._recent_lines()).strip() if self.enabled else ""

    def note(self, text: str) -> str:
        """Append a durable note (landmarks / rollups / rare meta)."""
        cleaned = " ".join(str(text).split())[:_ENTRY_MAX]
        if not self.enabled or not cleaned:
            return ""
        if cleaned.startswith(("LANDMARK ", "ANTI ")) and any(
            _normalized(line) == _normalized(cleaned) for line in self._recent_lines()
        ):
            return ""
        with self.notes_path.open("a", encoding="utf-8") as f:
            f.write(cleaned + "\n")
        return cleaned
