"""Gen 1's real movement mechanic: a directional press only turns the
sprite when not already facing that way — a second press is needed to
actually move a tile. Confirmed live: facing updated with zero position
change on a first press, then position advanced on a second. walk_X must
send a turn press first when needed, or it silently only turns.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from nuzlocke.environment.nous_red import NousRedEnvironment
from nuzlocke.state.models import GameAction


@pytest.fixture
def env(tmp_path: Path) -> NousRedEnvironment:
    e = NousRedEnvironment(
        base_url="http://127.0.0.1:8765",
        run_dir=tmp_path,
        auto_start=False,
        press_interval_s=0.0,
    )
    e._client = MagicMock()
    e.observe = MagicMock(return_value=None)  # type: ignore[method-assign]
    return e


def _state(*, facing: str = "up", x: int = 5, y: int = 5) -> dict:
    return {
        "player": {
            "position": {"x": x, "y": y, "map_name": "Pallet Town"},
            "facing": facing,
            "name": "RED",
        },
        "map": {"map_name": "Pallet Town", "map_id": 0},
        "dialog": {"active": False, "joy_ignore": 0, "text": None},
        "battle": {"in_battle": False, "type": "none"},
        "party": [],
        "bag": [],
        "metadata": {"frame_count": 1},
    }


def _posted_actions(post: MagicMock) -> list[list[str]]:
    return [c.kwargs["json"]["actions"] for c in post.call_args_list if c.args[0].endswith("/action")]


def test_walk_sends_turn_then_move_when_not_already_facing(env: NousRedEnvironment):
    call = {"n": 0}

    def get_side_effect(url):
        call["n"] += 1
        if call["n"] == 1:
            state = _state(facing="up", x=5)  # initial peek
        elif call["n"] == 2:
            state = _state(facing="right", x=5)  # after turn press: no move yet
        else:
            state = _state(facing="right", x=6)  # after move press
        return MagicMock(status_code=200, json=lambda: state, raise_for_status=lambda: None)

    env._client.get = MagicMock(side_effect=get_side_effect)
    env._client.post = MagicMock(
        return_value=MagicMock(content=b"{}", json=lambda: {}, raise_for_status=lambda: None)
    )

    result = env.execute([GameAction.WALK_RIGHT])

    posted = _posted_actions(env._client.post)
    # One /action payload: turn then step (Field Log shows a single ACT).
    assert posted == [["walk_right", "walk_right"]]
    assert result.executed == [GameAction.WALK_RIGHT]


def test_walk_does_not_pre_turn_when_already_facing(env: NousRedEnvironment):
    state = _state(facing="right", x=5)
    env._client.get = MagicMock(
        return_value=MagicMock(status_code=200, json=lambda: state, raise_for_status=lambda: None)
    )
    env._client.post = MagicMock(
        return_value=MagicMock(content=b"{}", json=lambda: {}, raise_for_status=lambda: None)
    )

    result = env.execute([GameAction.WALK_RIGHT])

    posted = _posted_actions(env._client.post)
    assert posted.count(["walk_right"]) == 1
    assert result.executed == [GameAction.WALK_RIGHT]


def test_multi_tile_macro_turns_once_then_moves_each_tile(env: NousRedEnvironment):
    # walk_right_3 expands to 3x walk_right; only the first should need a
    # turn press if starting off-facing.
    call = {"n": 0}

    def get_side_effect(url):
        call["n"] += 1
        if call["n"] == 1:
            state = _state(facing="up", x=5)
        elif call["n"] == 2:
            state = _state(facing="right", x=5)  # turn only
        else:
            state = _state(facing="right", x=5 + (call["n"] - 2))  # subsequent moves
        return MagicMock(status_code=200, json=lambda: state, raise_for_status=lambda: None)

    env._client.get = MagicMock(side_effect=get_side_effect)
    env._client.post = MagicMock(
        return_value=MagicMock(content=b"{}", json=lambda: {}, raise_for_status=lambda: None)
    )

    result = env.execute([GameAction.WALK_RIGHT_3])

    posted = _posted_actions(env._client.post)
    # 1 combined turn+step, then 2 already-facing steps.
    assert posted == [
        ["walk_right", "walk_right"],
        ["walk_right"],
        ["walk_right"],
    ]
    assert result.executed == [GameAction.WALK_RIGHT] * 3


def test_execute_drops_a_when_walking_on_naming_grid(env: NousRedEnvironment):
    state = _state(facing="right", x=5)
    state["dialog"]["joy_ignore"] = 64  # naming keyboard
    env._client.get = MagicMock(
        return_value=MagicMock(
            status_code=200, json=lambda: state, raise_for_status=lambda: None
        )
    )
    env._client.post = MagicMock(
        return_value=MagicMock(
            content=b"{}", json=lambda: {}, raise_for_status=lambda: None
        )
    )
    result = env.execute([GameAction.WALK_RIGHT_2, GameAction.PRESS_A])
    posted = _posted_actions(env._client.post)
    assert ["press_a"] not in posted
    assert result.executed == [GameAction.WALK_RIGHT, GameAction.WALK_RIGHT]


def test_execute_stops_after_skip_dialog(env: NousRedEnvironment):
    state = _state()
    peek = env._observation_from_state(state)
    env._client.get = MagicMock(
        return_value=MagicMock(
            status_code=200, json=lambda: state, raise_for_status=lambda: None
        )
    )
    env.execute_skip_dialog = MagicMock(return_value=peek)  # type: ignore[method-assign]
    result = env.execute(
        [GameAction.SKIP_DIALOG, GameAction.WALK_RIGHT, GameAction.PRESS_A]
    )
    assert result.executed == [GameAction.SKIP_DIALOG]
    assert result.stopped_early_because == "skip_dialog"
    env.execute_skip_dialog.assert_called_once()


def test_naming_grid_does_not_double_walk_for_stale_facing(env: NousRedEnvironment):
    """DECIDE walk_right must be one cursor cell, not turn+step from RAM facing."""
    state = _state(facing="up", x=3, y=6)
    state["dialog"]["joy_ignore"] = 64
    env._client.get = MagicMock(
        return_value=MagicMock(
            status_code=200, json=lambda: state, raise_for_status=lambda: None
        )
    )
    env._client.post = MagicMock(
        return_value=MagicMock(
            content=b"{}", json=lambda: {}, raise_for_status=lambda: None
        )
    )
    result = env.execute([GameAction.WALK_RIGHT])
    posted = _posted_actions(env._client.post)
    assert posted == [["walk_right"]]
    assert result.executed == [GameAction.WALK_RIGHT]
