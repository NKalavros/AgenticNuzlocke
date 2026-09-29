"""Client-side action macros (not pokemon-agent opcodes)."""

from __future__ import annotations

from nuzlocke.state.models import GameAction

_WALK_MACRO_STEPS = {
    GameAction(f"walk_{direction}_{n}"): (GameAction(f"walk_{direction}"), n)
    for direction in ("up", "down", "left", "right")
    for n in range(2, 6)
}
_NAMING_CONFIRM = {GameAction.PRESS_A, GameAction.HOLD_A_30, GameAction.A_UNTIL_DIALOG_END}


def expand_actions(actions: list[GameAction]) -> list[GameAction]:
    """Expand walk_*_N macros into repeated single-tile walks."""
    out: list[GameAction] = []
    for action in actions:
        step, count = _WALK_MACRO_STEPS.get(action, (action, 1))
        out.extend([step] * count)
    return out


def drop_naming_confirm_if_walking(actions: list[GameAction]) -> list[GameAction]:
    """On the letter grid, walks move the cursor and A types the glyph under it.

    A in a walking burst types junk before the cursor reaches END, so it waits for the next cycle.
    """
    if not any(action.value.startswith("walk_") for action in actions):
        return actions
    return [action for action in actions if action not in _NAMING_CONFIRM]
