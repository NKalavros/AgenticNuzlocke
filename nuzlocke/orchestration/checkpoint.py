"""Crash-recovery checkpoint gating.

Save states are for crash recovery only (no_outcome_rollback in
rules_red.yaml): never checkpoint mid-battle or immediately after a
permadeath/encounter ledger commit, so a resumed run can only replay
forward from a safe point, never "undo" a decided outcome.
"""

from __future__ import annotations

CHECKPOINT_NAME = "auto"


def should_checkpoint(
    *,
    steps: int,
    every_steps: int,
    in_battle: bool,
    last_ledger_change_step: int,
    min_gap_after_ledger_event: int = 3,
) -> bool:
    if every_steps <= 0 or steps <= 0:
        return False
    if steps % every_steps != 0:
        return False
    if in_battle:
        return False
    return steps - last_ledger_change_step >= min_gap_after_ledger_event
