"""Stuck / noop detection state."""

from __future__ import annotations

from typing import NamedTuple

from nuzlocke.environment import screen
from nuzlocke.state.models import GameAction, PlayerObservation


class Fingerprint(NamedTuple):
    """Per-step state hash. ``world`` covers only the rows a Gen 1 text box never touches, so a
    step that changes ``frame`` but not ``world`` moved text, not the game."""

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
    return before[:5] == after[:5] and before.world == after.world


# Escalation thresholds, in prompt cycles. A few missed joystick taps must not call the recovery
# model: these sit well above a fumbled stair tile and well below a multi-minute freeze.
NO_PROGRESS_RECOVERY = 24
NO_PROGRESS_DISENGAGE = 48
NO_PROGRESS_REFRAME = 72
NO_PROGRESS_RESET = 120
NOOP_RECOVERY = 12
LOOP_RECOVERY = 12
STUCK_RECOVERY = 24
# Cycles on one tile before a forced disengage, counted only while the picture is frozen too.
SAME_TILE_BUDGET = 40
# Walks that left (map, x, y) unchanged. Water and NPC animation change the picture, so this is
# the signal that still fires on the Pallet shore.
IMMOBILE_DISENGAGE = 12

_SIDESTEPS: dict[str, tuple[GameAction, GameAction]] = {
    "walk_up": (GameAction.WALK_LEFT, GameAction.WALK_RIGHT),
    "walk_down": (GameAction.WALK_LEFT, GameAction.WALK_RIGHT),
    "walk_left": (GameAction.WALK_UP, GameAction.WALK_DOWN),
    "walk_right": (GameAction.WALK_UP, GameAction.WALK_DOWN),
}
# ``walk_up_3`` and ``walk_up`` both block the up direction.
_WALK_BASE = {f"{base}{n}": base for base in _SIDESTEPS for n in ("", "_2", "_3", "_4", "_5")}


def _phrase_affirmed(text: str, phrase: str) -> bool:
    """True when ``phrase`` appears outside a ``do not`` / ``don't``."""
    at = text.find(phrase)
    while at >= 0:
        prefix = text[max(0, at - 16) : at]
        if not any(negation in prefix for negation in ("do not ", "don't ", "dont ")):
            return True
        at = text.find(phrase, at + len(phrase))
    return False


def single_named_walk(text: str) -> GameAction | None:
    """The walk button a plan or recovery reason names, if it names exactly one."""
    lowered = text.lower().replace("_", " ")
    named = [base for base in _SIDESTEPS if _phrase_affirmed(lowered, base.replace("_", " "))]
    return GameAction(named[0]) if len(named) == 1 else None


def perpendicular_sidestep(failed_actions: list[str], *, alternate: int = 0) -> GameAction:
    """One-tile step off the last failed walk's axis (fence post / door-mat miss)."""
    for label in reversed(failed_actions):
        if label in _WALK_BASE:
            return _SIDESTEPS[_WALK_BASE[label]][alternate % 2]
    return GameAction.WALK_LEFT


def avoid_blocked_walk(
    actions: list[GameAction], blocked_on_tile: set[str] | list[str], *, alternate: int = 0
) -> list[GameAction]:
    """Swap a first walk that already failed on this tile for a sidestep.

    Only this tile: a walk that failed elsewhere is pressed as named. Buttons and menu macros are
    never touched.
    """
    first = _WALK_BASE.get(actions[0].value) if actions else None
    if first is None or first not in blocked_on_tile:
        return actions
    for turn in (alternate, alternate + 1):
        side = perpendicular_sidestep([first], alternate=turn)
        if side.value not in blocked_on_tile:
            return [side, *actions[1:]]
    return actions[1:] or actions


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
        # Steps that left the world region untouched. Animating dialogue text cannot reset it.
        self.no_progress_streak = 0
        self.same_tile_streak = 0
        # Walks that did not change (map, x, y), whether or not water or an NPC moved the picture.
        self.immobile_streak = 0
        self.last_immobile = False
        # Directions that failed to move the player, on the current tile only.
        self.blocked_on_tile: set[str] = set()
        # Button counts since the last tile change. The planner sees only the last few steps, so
        # one long book page can look like eight successful B presses.
        self.press_counts: dict[str, int] = {}
        # Signature -> times it ran without moving the world. Prompt evidence only, never an
        # action filter, so every action type counts.
        self.no_progress_counts: dict[tuple[str, ...], int] = {}
        self.disengage_index = 0
        self.recent_positions: list[tuple[str | None, int | None, int | None]] = []
        self.recent_actions: list[tuple[str, ...]] = []
        self.failed_approaches: list[list[str]] = []
        self._position_window = position_window
        self._same_tile_window = same_tile_window
        self._action_window = action_window
        self._failed_window = failed_window
        self._loop_unique_max = max(2, int(loop_unique_max))

    def pause_for_cutscene(self) -> None:
        """A title splash or an open text box is not a stuck overworld.

        Same-tile dwell is kept: a name list sits on one tile and should still force an early
        replan. Blocked directions are retried: a scripted scene holds the player still, so walks
        it refused say nothing about walls.
        """
        self.no_progress_streak = self.noop_streak = self.loop_streak = self.stuck_score = 0
        self.immobile_streak = 0
        self.last_immobile = False
        self.blocked_on_tile.clear()

    def needs_recovery(self) -> bool:
        return (
            self.noop_streak >= NOOP_RECOVERY
            or self.stuck_score >= STUCK_RECOVERY
            or self.loop_streak >= LOOP_RECOVERY
            or self.no_progress_streak >= NO_PROGRESS_RECOVERY
        )

    needs_guide = needs_recovery

    def escalation_tier(self) -> int:
        """0 fine · 1 LLM recovery · 2 forced disengage · 3 reframe · 4 hard reset.

        Repeating one recovery call is the same vision agent looking at the same frozen screen,
        so each tier answers differently.
        """
        if self.no_progress_streak >= NO_PROGRESS_RESET or self.stuck_score >= 48:
            return 4
        if self.no_progress_streak >= NO_PROGRESS_REFRAME or self.stuck_score >= 36:
            return 3
        # RAM x,y hold still through menus and cutscenes, so same-tile dwell only counts while
        # the world picture is frozen too.
        tile_frozen = self.same_tile_streak >= SAME_TILE_BUDGET and self.no_progress_streak >= 2
        if (
            self.no_progress_streak >= NO_PROGRESS_DISENGAGE
            or tile_frozen
            or self.stuck_score >= STUCK_RECOVERY
            or self.immobile_streak >= IMMOBILE_DISENGAGE
        ):
            return 2
        return 1 if self.needs_recovery() else 0

    def repeated_actions(self, limit: int = 5) -> list[dict[str, object]]:
        """Action signatures that keep failing, as prompt evidence."""
        ranked = sorted(self.no_progress_counts.items(), key=lambda kv: kv[1], reverse=True)
        return [
            {"actions": list(sig), "times_without_progress": count}
            for sig, count in ranked[:limit]
            if count >= 2
        ]

    def disengage_actions(self) -> list[GameAction]:
        """Mechanical un-stick: close any box, leave the tile, face elsewhere.

        Not an LLM call: when the screen looks identical every cycle the vision agents have
        nothing new to reason about, so the way out has to be blind and has to rotate.
        """
        ring = (
            (GameAction.PRESS_B, GameAction.WALK_DOWN, GameAction.WALK_LEFT),
            (GameAction.PRESS_B, GameAction.WALK_UP, GameAction.WALK_RIGHT),
            (GameAction.PRESS_B, GameAction.WALK_LEFT, GameAction.WALK_UP),
            (GameAction.PRESS_B, GameAction.WALK_RIGHT, GameAction.WALK_DOWN),
        )
        blocked = self.blocked_on_tile
        for _ in ring:
            chosen = ring[self.disengage_index % len(ring)]
            self.disengage_index += 1
            if not any(step.value in blocked for step in chosen):
                return list(chosen)
        # Every pattern walks into a blocked direction. Keep the last one's open walks, if any.
        kept = [step for step in chosen if step.value not in blocked]
        if any(step.value.startswith("walk_") for step in kept):
            return kept
        chosen = ring[self.disengage_index % len(ring)]
        self.disengage_index += 1
        return list(chosen)

    def update_position(self, obs: PlayerObservation) -> None:
        """Same-tile dwell detection.

        Intro and menus hold position by design, so stuck score only grows on a frozen same-tile
        dwell outside dialog and battle. A few-tile ping-pong does not decay it either: that is
        loop_streak's job in record_result.
        """
        pos = (obs.map_name, obs.x, obs.y)
        if self.recent_positions and self.recent_positions[-1] == pos:
            self.same_tile_streak += 1
        else:
            if self.recent_positions:
                self.immobile_streak = 0
                self.blocked_on_tile.clear()
                self.press_counts.clear()
            self.same_tile_streak = 0
        self.recent_positions.append(pos)
        self.recent_positions = self.recent_positions[-self._position_window :]
        window = self.recent_positions[-self._same_tile_window :]
        # A cutscene or a moving menu cursor changes the picture while RAM x,y hold still.
        frozen_dwell = (
            len(window) >= self._same_tile_window
            and len(set(window)) == 1
            and self.no_progress_streak >= 2
        )
        in_scene = obs.dialog_active or obs.in_battle
        if frozen_dwell and not in_scene:
            self.stuck_score += 1
        elif in_scene or not self.is_position_oscillation():
            self.stuck_score = max(0, self.stuck_score - 1)

    def is_position_oscillation(self) -> bool:
        window = self.recent_positions[-self._same_tile_window :]
        return (
            len(window) >= self._same_tile_window and 1 < len(set(window)) <= self._loop_unique_max
        )

    def is_action_oscillation(self) -> bool:
        recent = self.recent_actions[-6:]
        return (
            len(recent) >= 4
            and len(set(recent)) == 2
            and recent[-1] != recent[-2]
            and recent[-4] == recent[-2]
            and recent[-3] == recent[-1]
        )

    @staticmethod
    def fingerprint(obs: PlayerObservation) -> Fingerprint:
        path = obs.screenshot_path
        world, dialog = screen.digests_from_path(path)
        frame = screen.frame_digest_from_path(path)
        return Fingerprint(
            obs.map_name, obs.x, obs.y, obs.facing, obs.dialog_active, frame, world, dialog
        )

    def record_result(
        self,
        before_fp: Fingerprint,
        after_fp: Fingerprint,
        *,
        executed: bool,
        actions: list[str] | None = None,
        allow_immobile: bool = True,
    ) -> bool:
        """Update the streaks from a before/after pair. True when actions ran and the whole frame
        is unchanged (a noop).

        ``no_progress`` compares only the world region, so a dialogue loop still counts though
        its text changes the frame. ``immobile`` is a walk that left the tile unchanged, even
        while water or an NPC animates; that direction is blocked on this tile only.
        """
        actions = actions or []
        is_noop = after_fp == before_fp and executed
        no_progress = executed and world_static(before_fp, after_fp)
        walked = any(label in _WALK_BASE for label in actions)
        coords_known = None not in (before_fp.x, before_fp.y, after_fp.x, after_fp.y)
        # A walk into a wall from another facing only turns the player, as planned in "walk_up to
        # face the ball, then press_a". The second press the same way is the failure.
        turned = (
            None not in (before_fp.facing, after_fp.facing) and before_fp.facing != after_fp.facing
        )
        self.last_immobile = False
        if executed and coords_known and before_fp[:3] != after_fp[:3]:  # (map, x, y) changed
            self.immobile_streak = 0
            self.blocked_on_tile.clear()
        elif executed and coords_known and allow_immobile and walked and not turned:
            self.last_immobile = True
            self.immobile_streak += 1
            self.blocked_on_tile.update(
                _WALK_BASE[label] for label in actions if label in _WALK_BASE
            )
            # The player walked onto this tile, so one side is open. Four refused directions
            # mean something held the input, not walls.
            if len(self.blocked_on_tile) >= 4:
                self.blocked_on_tile.clear()
        if actions:
            sig = tuple(actions)
            self.recent_actions.append(sig)
            self.recent_actions = self.recent_actions[-self._action_window :]
            if is_noop and walked and self.failed_approaches[-1:] != [actions]:
                self.failed_approaches.append(list(actions))
                self.failed_approaches = self.failed_approaches[-self._failed_window :]
            if no_progress:
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
        if self.is_action_oscillation() or self.is_position_oscillation():
            self.loop_streak += 1
            self.stuck_score += 1
        else:
            self.loop_streak = 0
        return is_noop

    def discount(self, amount: int) -> None:
        """Lower stuck_score after a successful recovery action."""
        self.stuck_score = max(0, self.stuck_score - amount)
        self.loop_streak = max(0, self.loop_streak - 1)

    def hard_reset(self) -> None:
        """Tier 4. Without it the tracker stays pinned above every threshold and each cycle
        repeats the same top-tier response."""
        self.pause_for_cutscene()
        self.same_tile_streak = 0
        self.press_counts.clear()
        self.no_progress_counts.clear()
        self.failed_approaches.clear()
        self.recent_actions.clear()
