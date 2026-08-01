"""Client-side action macros (not pokemon-agent opcodes)."""

from __future__ import annotations

from nuzlocke.state.models import GameAction

# Multi-tile walks: one proposal slot → N tile steps.
_WALK_MACRO_STEPS: dict[GameAction, tuple[GameAction, int]] = {
    GameAction.WALK_UP_2: (GameAction.WALK_UP, 2),
    GameAction.WALK_UP_3: (GameAction.WALK_UP, 3),
    GameAction.WALK_UP_4: (GameAction.WALK_UP, 4),
    GameAction.WALK_UP_5: (GameAction.WALK_UP, 5),
    GameAction.WALK_DOWN_2: (GameAction.WALK_DOWN, 2),
    GameAction.WALK_DOWN_3: (GameAction.WALK_DOWN, 3),
    GameAction.WALK_DOWN_4: (GameAction.WALK_DOWN, 4),
    GameAction.WALK_DOWN_5: (GameAction.WALK_DOWN, 5),
    GameAction.WALK_LEFT_2: (GameAction.WALK_LEFT, 2),
    GameAction.WALK_LEFT_3: (GameAction.WALK_LEFT, 3),
    GameAction.WALK_LEFT_4: (GameAction.WALK_LEFT, 4),
    GameAction.WALK_LEFT_5: (GameAction.WALK_LEFT, 5),
    GameAction.WALK_RIGHT_2: (GameAction.WALK_RIGHT, 2),
    GameAction.WALK_RIGHT_3: (GameAction.WALK_RIGHT, 3),
    GameAction.WALK_RIGHT_4: (GameAction.WALK_RIGHT, 4),
    GameAction.WALK_RIGHT_5: (GameAction.WALK_RIGHT, 5),
}


def expand_actions(actions: list[GameAction]) -> list[GameAction]:
    """Expand walk_*_N macros into repeated single-tile walks."""
    out: list[GameAction] = []
    for action in actions:
        spec = _WALK_MACRO_STEPS.get(action)
        if spec is None:
            out.append(action)
            continue
        base, n = spec
        out.extend([base] * n)
    return out


def is_walk_macro(action: GameAction) -> bool:
    return action in _WALK_MACRO_STEPS
