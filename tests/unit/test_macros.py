from nuzlocke.environment.macros import expand_actions, is_walk_macro
from nuzlocke.state.models import GameAction


def test_expand_walk_macro():
    assert expand_actions([GameAction.WALK_UP_3]) == [
        GameAction.WALK_UP,
        GameAction.WALK_UP,
        GameAction.WALK_UP,
    ]


def test_expand_mixed_burst():
    got = expand_actions(
        [GameAction.WALK_RIGHT_2, GameAction.PRESS_A, GameAction.SKIP_DIALOG]
    )
    assert got == [
        GameAction.WALK_RIGHT,
        GameAction.WALK_RIGHT,
        GameAction.PRESS_A,
        GameAction.SKIP_DIALOG,
    ]


def test_is_walk_macro():
    assert is_walk_macro(GameAction.WALK_DOWN_5)
    assert not is_walk_macro(GameAction.WALK_DOWN)
