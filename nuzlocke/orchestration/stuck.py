"""Stuck / noop detection state, extracted from RunLoop."""

from __future__ import annotations

from typing import NamedTuple

from nuzlocke.environment import screen
from nuzlocke.state.models import GameAction, PlayerObservation


class Fingerprint(NamedTuple):
    """Per-step state hash, split so text animation can't fake progress.

    ``frame`` is the whole-PNG hash (unchanged noop semantics). ``world`` only
    covers the top 12 tile rows — the part of the screen a Gen 1 text box never
    touches. A step that changes ``frame`` but not ``world`` moved text, not the
    game.
    """

    map_name: str | None
    x: int | None
    y: int | None
    facing: str | None
    dialog_active: bool
    frame: str
    world: str
    dialog: str


def world_static(before: Fingerprint, after: Fingerprint) -> bool:
    """True when the game world is byte-identical — text box changes ignored."""
    return tuple(before[:5]) == tuple(after[:5]) and before.world == after.world


# Escalation thresholds, in prompt cycles. Cycles are about a second, so a
# few missed joystick taps must not call the recovery model. These sit well
# above a fumbled stair tile and well below a multi-minute freeze.
NO_PROGRESS_RECOVERY = 24
NO_PROGRESS_DISENGAGE = 48
NO_PROGRESS_REFRAME = 72
NO_PROGRESS_RESET = 120
NOOP_RECOVERY = 12
LOOP_RECOVERY = 12
STUCK_RECOVERY = 24
# Hard per-location budget: cycles on one tile before we force a disengage,
# and only when the picture is frozen too.
SAME_TILE_BUDGET = 40

_WALK_AXIS: dict[str, str] = {}
for _name, _axis in (
    ("up", "vertical"),
    ("down", "vertical"),
    ("left", "horizontal"),
    ("right", "horizontal"),
):
    _WALK_AXIS[f"walk_{_name}"] = _axis
    for _n in range(2, 6):
        _WALK_AXIS[f"walk_{_name}_{_n}"] = _axis

_SIDESTEPS: dict[str, tuple[GameAction, GameAction]] = {
    "vertical": (GameAction.WALK_LEFT, GameAction.WALK_RIGHT),
    "horizontal": (GameAction.WALK_UP, GameAction.WALK_DOWN),
}


def is_walk_burst(actions: list[str]) -> bool:
    return any(label in _WALK_AXIS for label in actions)


def last_walk_axis(actions: list[str]) -> str | None:
    for label in reversed(actions):
        axis = _WALK_AXIS.get(label)
        if axis:
            return axis
    return None


def perpendicular_sidestep(
    failed_actions: list[str], *, alternate: int = 0
) -> GameAction:
    """One-tile step off the failed walk axis (fence post / door-mat miss)."""
    axis = last_walk_axis(failed_actions)
    if axis is None:
        return GameAction.WALK_LEFT
    pair = _SIDESTEPS[axis]
    return pair[alternate % 2]


def filter_repeated_noops(
    actions: list[GameAction],
    failed_approaches: list[list[str]],
    *,
    alternate: int = 0,
) -> list[GameAction]:
    """Drop a walk burst that already nooped; never rewrite button/menu macros.

    Boot/title/dialog often false-noop (same PNG size, animation). Banning
    press_a / skip_dialog and substituting B is how a copyright splash
    permanently blocked NEW GAME.
    """
    if not actions or not failed_approaches:
        return actions
    labels = [a.value for a in actions]
    if not is_walk_burst(labels):
        return actions
    failed_tuples = [
        tuple(item) for item in failed_approaches if item and is_walk_burst(item)
    ]
    if not failed_tuples:
        return actions

    kept: list[str]
    if tuple(labels) in failed_tuples:
        kept = []
    else:
        kept = labels
        for failed in failed_tuples:
            n = len(failed)
            if n and tuple(labels[:n]) == failed:
                kept = labels[n:]
                break

    if kept:
        out: list[GameAction] = []
        for item in kept:
            try:
                out.append(GameAction(item))
            except ValueError:
                continue
        if out:
            return out

    last_walk = next(
        (item for item in reversed(failed_approaches) if is_walk_burst(item)),
        None,
    )
    if not last_walk:
        return actions
    return [perpendicular_sidestep(last_walk, alternate=alternate)]


class StuckTracker:
    """Tracks same-tile dwelling, action-noop streaks, and ping-pong loops."""

    def __init__(
        self,
        *,
        position_window: int = 8,
        same_tile_window: int = 6,
        action_window: int = 8,
        failed_window: int = 6,
        loop_unique_max: int = 3,
    ) -> None:
        self.stuck_score = 0
        self.noop_streak = 0
        self.loop_streak = 0
        # Consecutive executed steps that left the *world* region untouched.
        # Unlike noop_streak this survives animating dialogue text.
        self.no_progress_streak = 0
        # Consecutive observations on one (map, x, y) — the per-location budget.
        self.same_tile_streak = 0
        # signature -> times it ran without moving the world. Every action type,
        # not just walks: this is prompt evidence, never an action filter.
        self.no_progress_counts: dict[tuple[str, ...], int] = {}
        self.disengage_index = 0
        self.recent_positions: list[tuple[str | None, int | None, int | None]] = []
        self.recent_actions: list[tuple[str, ...]] = []
        self.failed_approaches: list[list[str]] = []
        self.last_fingerprint: Fingerprint | None = None
        self._position_window = position_window
        self._same_tile_window = same_tile_window
        self._action_window = action_window
        self._failed_window = failed_window
        self._loop_unique_max = max(2, int(loop_unique_max))

    def pause_for_cutscene(self) -> None:
        """A title splash or an open text box is not a stuck overworld.

        Same-tile dwell is kept: a name list sits on one tile and should
        still force an early replan. The frozen picture must not.
        """
        self.no_progress_streak = 0
        self.noop_streak = 0
        self.loop_streak = 0
        self.stuck_score = 0

    def needs_recovery(self) -> bool:
        return (
            self.noop_streak >= NOOP_RECOVERY
            or self.stuck_score >= STUCK_RECOVERY
            or self.loop_streak >= LOOP_RECOVERY
            or self.no_progress_streak >= NO_PROGRESS_RECOVERY
        )

    def needs_guide(self) -> bool:
        return self.needs_recovery()

    def escalation_tier(self) -> int:
        """0 fine · 1 LLM recovery · 2 forced disengage · 3 reframe · 4 hard reset.

        Tiers exist because one undifferentiated recovery call is not an escape
        hatch — it is the same vision agent looking at the same frozen screen.
        In run 20260821-164159-3c5a68 it fired 222 times and proposed the same
        two actions every time.
        """
        if self.no_progress_streak >= NO_PROGRESS_RESET or self.stuck_score >= 48:
            return 4
        if self.no_progress_streak >= NO_PROGRESS_REFRAME or self.stuck_score >= 36:
            return 3
        # RAM coordinates stay put through menus and cutscenes. A same-tile
        # count only means "stuck" when the world picture is frozen too;
        # otherwise this fires on a name menu and never asks Jev.
        tile_frozen = (
            self.same_tile_streak >= SAME_TILE_BUDGET
            and self.no_progress_streak >= 2
        )
        if (
            self.no_progress_streak >= NO_PROGRESS_DISENGAGE
            or tile_frozen
            or self.stuck_score >= STUCK_RECOVERY
        ):
            return 2
        if self.needs_recovery():
            return 1
        return 0

    def repeated_actions(self, limit: int = 5) -> list[dict[str, object]]:
        """Action signatures that keep failing, as prompt evidence."""
        ranked = sorted(
            self.no_progress_counts.items(), key=lambda kv: kv[1], reverse=True
        )
        return [
            {"actions": list(sig), "times_without_progress": count}
            for sig, count in ranked[:limit]
            if count >= 2
        ]

    def disengage_actions(self) -> list[GameAction]:
        """Mechanical un-stick: close any box, leave the tile, face elsewhere.

        Deliberately not an LLM call. When the screen looks identical every
        cycle the vision agents have nothing new to reason about, so the way
        out has to be blind and has to rotate.
        """
        ring = (
            (GameAction.PRESS_B, GameAction.WALK_DOWN, GameAction.WALK_LEFT),
            (GameAction.PRESS_B, GameAction.WALK_UP, GameAction.WALK_RIGHT),
            (GameAction.PRESS_B, GameAction.WALK_LEFT, GameAction.WALK_UP),
            (GameAction.PRESS_B, GameAction.WALK_RIGHT, GameAction.WALK_DOWN),
        )
        chosen = ring[self.disengage_index % len(ring)]
        self.disengage_index += 1
        return list(chosen)

    def update_position(self, obs: PlayerObservation) -> None:
        """Same-tile dwell detection.

        Intro/menus often hold position by design, so only accumulate stuck
        score when sitting on the same tile with no dialog and no battle.
        Two-tile / few-tile ping-pong does not decay the score (loop_streak is
        refreshed in record_result).
        """
        pos = (obs.map_name, obs.x, obs.y)
        if self.recent_positions and self.recent_positions[-1] == pos:
            self.same_tile_streak += 1
        else:
            self.same_tile_streak = 0
        self.recent_positions.append(pos)
        self.recent_positions = self.recent_positions[-self._position_window :]
        if obs.dialog_active or obs.in_battle:
            self.stuck_score = max(0, self.stuck_score - 1)
            return
        window = self.recent_positions[-self._same_tile_window :]
        unique = len(set(window))
        same_tile = len(window) >= self._same_tile_window and unique == 1
        confined = (
            len(window) >= self._same_tile_window
            and 1 < unique <= self._loop_unique_max
        )
        # An animating cutscene or a moving menu cursor changes the picture
        # while RAM x,y do not. Don't treat that dwell as stuck.
        if same_tile and self.no_progress_streak >= 2:
            self.stuck_score += 1
        elif confined:
            # Fence-row / door-mat wiggle: do not decay (loop_streak in record_result).
            return
        else:
            self.stuck_score = max(0, self.stuck_score - 1)

    def is_position_oscillation(self) -> bool:
        window = self.recent_positions[-self._same_tile_window :]
        if len(window) < self._same_tile_window:
            return False
        unique = len(set(window))
        return 1 < unique <= self._loop_unique_max

    def is_action_oscillation(self) -> bool:
        recent = self.recent_actions[-6:]
        if len(recent) < 4:
            return False
        if len(set(recent)) != 2:
            return False
        if recent[-1] == recent[-2]:
            return False
        return recent[-4] == recent[-2] and recent[-3] == recent[-1]

    @staticmethod
    def fingerprint(obs: PlayerObservation) -> Fingerprint:
        path = obs.screenshot_path
        frame = screen.frame_digest_from_path(path)
        world, dialog = screen.digests_from_path(path)
        return Fingerprint(
            map_name=obs.map_name,
            x=obs.x,
            y=obs.y,
            facing=obs.facing,
            dialog_active=obs.dialog_active,
            frame=frame,
            world=world,
            dialog=dialog,
        )

    def record_result(
        self,
        before_fp: Fingerprint,
        after_fp: Fingerprint,
        *,
        executed: bool,
        actions: list[str] | None = None,
    ) -> bool:
        """Update noop/stuck/loop state from a before/after fingerprint pair.

        Returns True if this step was a noop (actions ran but nothing changed).

        Two distinct signals, because they catch different failures:

        - ``is_noop`` — the whole frame is identical. Blind to dialogue loops:
          animating text changes the PNG every cycle, so ``noop_streak`` sat at
          0 through 200 wasted steps in run 20260821-164159-3c5a68.
        - ``no_progress`` — the world region is identical. Opening and closing a
          text box does not move it, so an NPC re-talk loop reads as exactly
          what it is.
        """
        is_noop = after_fp == before_fp and executed
        no_progress = executed and world_static(before_fp, after_fp)
        if actions:
            sig = tuple(actions)
            self.recent_actions.append(sig)
            self.recent_actions = self.recent_actions[-self._action_window :]
            if is_noop and is_walk_burst(actions):
                self._record_failed(list(actions))
            if no_progress:
                # Every action type, walks included — this list only ever
                # reaches a prompt, so it cannot ban A on a boot splash the way
                # filter_repeated_noops would.
                self.no_progress_counts[sig] = self.no_progress_counts.get(sig, 0) + 1
        if is_noop:
            self.noop_streak += 1
            self.stuck_score += 1
        else:
            self.noop_streak = 0
        if no_progress:
            self.no_progress_streak += 1
        else:
            self.no_progress_streak = 0
            self.no_progress_counts.clear()
        self._refresh_loop_streak()
        self.last_fingerprint = after_fp
        return is_noop

    def _record_failed(self, actions: list[str]) -> None:
        if not actions:
            return
        if self.failed_approaches and self.failed_approaches[-1] == actions:
            return
        self.failed_approaches.append(actions)
        self.failed_approaches = self.failed_approaches[-self._failed_window :]

    def _refresh_loop_streak(self) -> None:
        if self.is_action_oscillation() or self.is_position_oscillation():
            self.loop_streak += 1
            self.stuck_score += 1
        else:
            self.loop_streak = 0

    def discount(self, amount: int) -> None:
        """Lower stuck_score after a successful recovery action."""
        self.stuck_score = max(0, self.stuck_score - amount)
        self.loop_streak = max(0, self.loop_streak - 1)

    def hard_reset(self) -> None:
        """Tier 4: drop every accumulated belief and restart the escape.

        Without this the tracker stays pinned above every threshold forever and
        each cycle repeats the same top-tier response.
        """
        self.stuck_score = 0
        self.noop_streak = 0
        self.loop_streak = 0
        self.no_progress_streak = 0
        self.same_tile_streak = 0
        self.no_progress_counts.clear()
        self.failed_approaches.clear()
        self.recent_actions.clear()
