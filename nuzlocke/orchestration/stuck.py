"""Stuck / noop detection state, extracted from RunLoop."""

from __future__ import annotations

from pathlib import Path

from nuzlocke.state.models import PlayerObservation

Fingerprint = tuple


class StuckTracker:
    """Tracks same-tile dwelling and action-noop streaks across steps."""

    def __init__(self, *, position_window: int = 8, same_tile_window: int = 6) -> None:
        self.stuck_score = 0
        self.noop_streak = 0
        self.recent_positions: list[tuple[str | None, int | None, int | None]] = []
        self.last_fingerprint: Fingerprint | None = None
        self._position_window = position_window
        self._same_tile_window = same_tile_window

    def update_position(self, obs: PlayerObservation) -> None:
        """Same-tile dwell detection.

        Intro/menus often hold position by design, so only accumulate stuck
        score when sitting on the same tile with no dialog and no battle.
        """
        pos = (obs.map_name, obs.x, obs.y)
        self.recent_positions.append(pos)
        self.recent_positions = self.recent_positions[-self._position_window :]
        same_tile = (
            len(self.recent_positions) >= self._same_tile_window
            and len(set(self.recent_positions[-self._same_tile_window :])) == 1
        )
        if same_tile and not obs.dialog_active and not obs.in_battle:
            self.stuck_score += 1
        else:
            self.stuck_score = max(0, self.stuck_score - 1)

    @staticmethod
    def fingerprint(obs: PlayerObservation) -> Fingerprint:
        return (
            obs.map_name,
            obs.x,
            obs.y,
            obs.facing,
            obs.dialog_active,
            Path(obs.screenshot_path).stat().st_size
            if obs.screenshot_path and Path(obs.screenshot_path).exists()
            else 0,
        )

    def record_result(
        self, before_fp: Fingerprint, after_fp: Fingerprint, *, executed: bool
    ) -> bool:
        """Update noop/stuck state from a before/after fingerprint pair.

        Returns True if this step was a noop (actions ran but nothing changed).
        """
        is_noop = after_fp == before_fp and executed
        if is_noop:
            self.noop_streak += 1
            self.stuck_score += 1
        else:
            self.noop_streak = 0
        self.last_fingerprint = after_fp
        return is_noop

    def discount(self, amount: int) -> None:
        """Lower stuck_score after a successful recovery action."""
        self.stuck_score = max(0, self.stuck_score - amount)
