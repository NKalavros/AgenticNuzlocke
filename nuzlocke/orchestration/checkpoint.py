"""Continue-point savestates.

A run writes ``runs/<run-id>/savestates/auto.state`` on a cadence and again when it stops.
``nuzlocke run --resume <run-id>`` loads that file, so the intro does not have to be played again.

Saves are refused mid-battle and right after a ledger commit (no_outcome_rollback): a resumed run
replays forward, it does not undo a decided death or encounter.
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
