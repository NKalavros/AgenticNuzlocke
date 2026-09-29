from nuzlocke.environment.macros import drop_naming_confirm_if_walking, expand_actions
from nuzlocke.state.models import GameAction


def test_expand_walk_macro():
    assert expand_actions([GameAction.WALK_UP_3]) == [
        GameAction.WALK_UP,
        GameAction.WALK_UP,
        GameAction.WALK_UP,
    ]


def test_expand_mixed_burst():
    got = expand_actions([GameAction.WALK_RIGHT_2, GameAction.PRESS_A, GameAction.SKIP_DIALOG])
    assert got == [
        GameAction.WALK_RIGHT,
        GameAction.WALK_RIGHT,
        GameAction.PRESS_A,
        GameAction.SKIP_DIALOG,
    ]


def test_drop_naming_confirm_strips_a_from_walk_burst():
    got = drop_naming_confirm_if_walking(
        [GameAction.WALK_RIGHT_5, GameAction.WALK_RIGHT_3, GameAction.PRESS_A]
    )
    assert got == [GameAction.WALK_RIGHT_5, GameAction.WALK_RIGHT_3]


def test_drop_naming_confirm_keeps_a_only_burst():
    assert drop_naming_confirm_if_walking([GameAction.PRESS_A]) == [GameAction.PRESS_A]
