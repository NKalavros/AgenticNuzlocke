"""Thin wrapper around VictorTaelin/OptMem (`memo` CLI).

OptMem holds **long-term** facts only (landmarks, rollups, run meta).
Short-term step history lives in the orchestrator prompt, not here.

Wake text is injected into role prompts; pending compressions are auto-napped
deterministically (no invented content). If wake is blocked on homework, we
drain naps and return empty rather than injecting compression instructions.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

from nuzlocke.config import project_root

_ENTRY_MAX = 280
_NAP_ID_RE = re.compile(r"\bnap\s+(\d+-\d+)\s+\"")
_NAP_LINE_RE = re.compile(r"#\d+\s+\d{4}-\d{2}-\d{2}\s+(.+)")


def resolve_memo_bin(explicit: str | None = None) -> Path:
    if explicit:
        path = Path(explicit).expanduser()
        if path.is_file():
            return path
    vendored = project_root() / "third_party" / "optmem" / "memo"
    if vendored.is_file():
        return vendored
    home = Path.home() / ".optmem" / "memo"
    if home.is_file():
        return home
    which = shutil.which("memo")
    if which:
        return Path(which)
    raise FileNotFoundError(
        "OptMem `memo` not found. Expected third_party/optmem/memo or ~/.optmem/memo. "
        "Install: curl -fsSL https://raw.githubusercontent.com/VictorTaelin/OptMem/main/install.sh | sh"
    )


class OptMem:
    def __init__(
        self,
        memory_dir: Path,
        *,
        memo_bin: str | Path | None = None,
        wake_lines: int = 48,
        enabled: bool = True,
    ) -> None:
        self.enabled = enabled
        self.memory_dir = memory_dir
        self.memo_bin = resolve_memo_bin(str(memo_bin) if memo_bin else None)
        self.wake_lines = max(8, int(wake_lines))
        if self.enabled:
            self.memory_dir.mkdir(parents=True, exist_ok=True)
            self._run(["init"], check=False)
            self._run(["config", f"WAKE_LINES={self.wake_lines}"], check=False)

    def _env(self) -> dict[str, str]:
        env = os.environ.copy()
        env["MEMORY_DIR"] = str(self.memory_dir.resolve())
        return env

    def _run(self, args: list[str], *, check: bool = True) -> str:
        if not self.enabled:
            return ""
        proc = subprocess.run(
            [str(self.memo_bin), *args],
            capture_output=True,
            text=True,
            env=self._env(),
            check=False,
        )
        out = (proc.stdout or "") + (
            ("\n" + proc.stderr) if proc.stderr and proc.returncode != 0 else ""
        )
        if check and proc.returncode != 0:
            raise RuntimeError(
                f"memo {' '.join(args)} failed ({proc.returncode}): {out.strip()}"
            )
        return out.strip()

    def wake(self) -> str:
        if not self.enabled:
            return ""
        text = self._run(["wake"], check=False)
        if "Cannot wake" in text:
            self._auto_nap(text, max_naps=64)
            text = self._run(["wake"], check=False)
        if "Cannot wake" in text:
            # Never inject OptMem homework into the LLM prompt.
            return ""
        # Drop trailing compression homework from the injected context.
        lines = []
        for line in text.splitlines():
            if line.startswith("Compress memories"):
                break
            if line.startswith("Run:"):
                break
            if line.startswith("Cannot wake"):
                continue
            if line.startswith("Do the ") and "compressions" in line:
                continue
            lines.append(line)
        return "\n".join(lines).strip()

    def note(self, text: str) -> str:
        """Append a durable long-term note (landmarks / rollups / rare meta)."""
        if not self.enabled:
            return ""
        cleaned = " ".join(str(text).split())
        if not cleaned:
            return ""
        cleaned = cleaned[:_ENTRY_MAX]
        out = self._run(["note", cleaned], check=False)
        self._auto_nap(out, max_naps=16)
        return out

    def recall(self, pattern: str) -> str:
        if not self.enabled:
            return ""
        return self._run(["recall", pattern], check=False)

    def _auto_nap(self, note_out: str, *, max_naps: int = 8) -> None:
        """Satisfy OptMem compressions without an extra LLM round-trip."""
        pending = note_out
        for _ in range(max(1, int(max_naps))):
            match = _NAP_ID_RE.search(pending)
            if not match:
                return
            nap_id = match.group(1)
            lines = _NAP_LINE_RE.findall(pending)
            if len(lines) < 2:
                return
            summary = f"{lines[0].strip()} | {lines[1].strip()}"[:_ENTRY_MAX]
            pending = self._run(["nap", nap_id, summary], check=False)
            if "Nothing left to compress" in pending:
                return
