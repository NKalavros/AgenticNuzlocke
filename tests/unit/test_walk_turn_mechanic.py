"""One walk_* press is one tile, whichever way the player was facing.

Gen 1 has no turn-in-place: a press into an open tile turns and steps, a press
into a wall only turns. An earlier version sent a second press after any turn.
In run 20260927-235608-cc25eb that moved two tiles on 57 of 63 turning walks,
so the tile below the starter ball — reached by a turn — could not be stood
on: "walk_right one tile" went (5,5)->(7,5) and "walk_left one tile" went
straight back. Checked on the emulator from that run's savestate:
(5,3,up) -walk_down-> (5,4); -walk_right-> (6,4); -walk_up-> faces the ball.
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
        base_url="http://127.0.0.1:8765", run_dir=tmp_path, auto_start=False, press_interval_s=0.0
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
    return [
        c.kwargs["json"]["actions"] for c in post.call_args_list if c.args[0].endswith("/action")
    ]


def _wire(env: NousRedEnvironment, facing: str) -> None:
    state = _state(facing=facing)
    env._client.get = MagicMock(
        return_value=MagicMock(status_code=200, json=lambda: state, raise_for_status=lambda: None)
    )
    env._client.post = MagicMock(
        return_value=MagicMock(content=b"{}", json=dict, raise_for_status=lambda: None)
    )


@pytest.mark.parametrize("facing", ["up", "down", "left", "right"])
def test_walk_is_one_press_from_any_facing(env: NousRedEnvironment, facing: str):
    _wire(env, facing)

    result = env.execute([GameAction.WALK_RIGHT])

    assert _posted_actions(env._client.post) == [["walk_right"]]
    assert result.executed == [GameAction.WALK_RIGHT]


def test_multi_tile_macro_is_one_press_per_tile(env: NousRedEnvironment):
    pos = {"x": 5}

    def state() -> dict:
        return _state(facing="up", x=pos["x"])

    def get(url: str, **kwargs: object) -> MagicMock:
        return MagicMock(status_code=200, json=state, raise_for_status=lambda: None)

    def post(url: str, json: dict | None = None, **kwargs: object) -> MagicMock:
        if (json or {}).get("actions") == ["walk_right"]:
            pos["x"] += 1
        return MagicMock(content=b"{}", json=dict, raise_for_status=lambda: None)

    env._client.get = MagicMock(side_effect=get)
    env._client.post = MagicMock(side_effect=post)

    result = env.execute([GameAction.WALK_RIGHT_3])

    assert _posted_actions(env._client.post) == [["walk_right"], ["walk_right"], ["walk_right"]]
    assert result.executed == [GameAction.WALK_RIGHT] * 3
