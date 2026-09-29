"""Paired emulator/controller commits for legal continuation.

A write-ahead marker refuses replay after an interrupted action. Immutable states and
controller records are published through an atomic pointer after each completed cycle.
The auto.state mirror remains available for diagnostic sandbox scripts.
"""

from __future__ import annotations

import shutil
from pathlib import Path

CHECKPOINT_NAME = "auto"


def savestate_path(run_dir: Path, name: str = CHECKPOINT_NAME) -> Path:
    return run_dir / "savestates" / f"{name}.state"


def _copy(src: Path, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if src.resolve() != dest.resolve():
        shutil.copy2(src, dest)
    return dest


def flat_saves_dir(saved: Path) -> Path | None:
    """Where ``/load`` looks, if ``saved`` was written into a game session.

    pokemon-agent puts a dashboard session's states at ``<data_dir>/games/<id>/saves/<name>.state``
    but ``POST /load`` reads ``<data_dir>/saves/<name>.state``.
    """
    games = saved.parent.parent.parent
    if saved.parent.name != "saves" or games.name != "games":
        return None
    return games.parent / "saves"


def mirror_save(saved: Path, *, run_dir: Path, name: str) -> Path:
    """Copy a just-written state into the flat dir and the run folder."""
    flat = flat_saves_dir(saved)
    if flat is not None:
        _copy(saved, flat / f"{name}.state")
    return _copy(saved, savestate_path(run_dir, name))


def stage_for_boot(run_dir: Path, name: str = CHECKPOINT_NAME) -> Path:
    """Put the run's savestate where a fresh pokemon-agent process will load it."""
    src = savestate_path(run_dir, name)
    boot = run_dir / "pokemon-agent-data" / "saves" / f"{name}.state"
    if not src.is_file():
        if not boot.is_file():
            raise FileNotFoundError(
                f"No savestate for this run ({src}). "
                "Stop a run from the dashboard once so it can write one."
            )
        src = boot
    return _copy(src, boot)


def data_dir_from_ps(text: str, port: str) -> Path | None:
    """Find ``--data-dir`` on the pokemon-agent process listening on ``port``."""
    for line in text.splitlines():
        parts = line.split()
        server = "pokemon-agent" in line or "nuzlocke.environment.pa_serve" in line
        if not server or "--data-dir" not in parts:
            continue
        if f"--port {port}" not in line and f"--port={port}" not in line:
            continue
        index = parts.index("--data-dir")
        if index + 1 < len(parts):
            return Path(parts[index + 1])
    return None


def should_checkpoint(
    *,
    steps: int,
    every_steps: int,
    in_battle: bool,
    last_ledger_change_step: int,
    min_gap_after_ledger_event: int = 3,
) -> bool:
    return (
        every_steps > 0
        and steps > 0
        and steps % every_steps == 0
        and not in_battle
        and steps - last_ledger_change_step >= min_gap_after_ledger_event
    )


class IntegrityError(RuntimeError):
    """The controller cannot safely continue this emulator history."""


class RunCheckpoint:
    """Immutable paired checkpoints, an atomic pointer, and a pending-action write-ahead record."""

    def __init__(self, run_dir: Path, identity: dict) -> None:
        self.run_dir = run_dir
        self.directory = run_dir / "checkpoints"
        self.directory.mkdir(parents=True, exist_ok=True)
        self.identity = identity
        self.sequence = 0
        self.pending = self.directory / "pending.json"
        self.pointer = self.directory / "current.json"

    @staticmethod
    def _write(path: Path, data: dict) -> None:
        import json
        import os

        temporary = path.with_suffix(".tmp")
        with temporary.open("w") as f:
            json.dump(data, f, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        temporary.replace(path)
        fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def begin(self) -> None:
        if not self.pending.exists():
            self._write(self.pending, {"after_sequence": self.sequence})

    def commit(self, env, controller: dict) -> None:
        import hashlib
        import os

        self.sequence += 1
        name = f"commit-{self.sequence:08d}"
        env.save_checkpoint(name)
        state = savestate_path(self.run_dir, name)
        with state.open("rb") as f:
            os.fsync(f.fileno())
        record = {
            "version": 1,
            "sequence": self.sequence,
            "identity": self.identity,
            "state": name,
            "state_sha256": hashlib.sha256(state.read_bytes()).hexdigest(),
            "controller": controller,
        }
        self._write(self.directory / f"{name}.json", record)
        self._write(self.pointer, record)
        self.pending.unlink(missing_ok=True)
        _copy(state, savestate_path(self.run_dir))

    def load(self) -> dict:
        import hashlib
        import json

        if self.pending.exists():
            raise IntegrityError(
                "An action was in flight at shutdown; automatic replay would risk rolling back an outcome. Inspect this run in sandbox."
            )
        if not self.pointer.exists():
            raise IntegrityError(
                "Legacy savestate has no matching controller history; use sandbox --from for diagnostics."
            )
        data = json.loads(self.pointer.read_text())
        if data.get("version") != 1 or data["identity"] != self.identity:
            raise IntegrityError("Checkpoint ROM/rules do not match this run")
        state = savestate_path(self.run_dir, data["state"])
        if hashlib.sha256(state.read_bytes()).hexdigest() != data["state_sha256"]:
            raise IntegrityError("Checkpoint state checksum mismatch")
        self.sequence = data["sequence"]
        _copy(state, savestate_path(self.run_dir))
        return data["controller"]
