"""Walks must never fire straight into a dialog-locked D-pad.

Reproduces a real failure seen live: `press_a` only advanced a text box to
its next page (didn't close it), so the queued walk actions right after it
were silently swallowed by the game — the agent then burned several turns
just re-diagnosing why it hadn't moved. `execute()` must instead play the
emulation (mash through the text) before firing a locked walk.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from nuzlocke.environment.nous_red import NousRedEnvironment
from nuzlocke.state.models import GameAction, PlayerObservation


@pytest.fixture
def env(tmp_path: Path) -> NousRedEnvironment:
    e = NousRedEnvironment(
        base_url="http://127.0.0.1:8765",
        run_dir=tmp_path,
        auto_start=False,
        press_interval_s=0.0,
    )
    e._client = MagicMock()
    return e


def _state(*, dialog_active: bool = False, joy_ignore: int = 0) -> dict:
    return {
        "player": {
            "position": {"x": 5, "y": 5, "map_name": "Pallet Town"},
            "facing": "DOWN",
            "name": "RED",
        },
        "map": {"map_name": "Pallet Town", "map_id": 0},
        "dialog": {"active": dialog_active, "joy_ignore": joy_ignore, "text": None},
        "battle": {"in_battle": False, "type": "none"},
        "party": [],
        "bag": [],
        "metadata": {"frame_count": 1},
    }


def _posted_action_lists(post: MagicMock) -> list[list[str]]:
    return [c.kwargs["json"]["actions"] for c in post.call_args_list if c.args[0].endswith("/action")]


def test_walk_deferred_until_dialog_lock_clears(env: NousRedEnvironment):
    locked = _state(dialog_active=True, joy_ignore=0x20)
    call_count = {"n": 0}

    def get_side_effect(url):
        call_count["n"] += 1
        state = locked if call_count["n"] == 1 else _state()
        return MagicMock(status_code=200, json=lambda: state, raise_for_status=lambda: None)

    env._client.get = MagicMock(side_effect=get_side_effect)
    post = MagicMock(content=b"{}", json=lambda: {}, raise_for_status=lambda: None)
    env._client.post = MagicMock(return_value=post)

    cleared = PlayerObservation(map_name="Pallet Town", x=5, y=5, dialog_active=False, joy_ignore=0)
    env.execute_skip_dialog = MagicMock(return_value=cleared)  # type: ignore[method-assign]

    result = env.execute([GameAction.WALK_RIGHT])

    env.execute_skip_dialog.assert_called_once()
    assert ["walk_right"] in _posted_action_lists(env._client.post)
    assert GameAction.WALK_RIGHT in result.executed
    assert result.stopped_early_because is None


def test_walk_never_posted_while_still_locked(env: NousRedEnvironment):
    locked = _state(dialog_active=True, joy_ignore=0x20)
    env._client.get = MagicMock(
        return_value=MagicMock(status_code=200, json=lambda: locked, raise_for_status=lambda: None)
    )
    env._client.post = MagicMock(
        return_value=MagicMock(content=b"{}", json=lambda: {}, raise_for_status=lambda: None)
    )

    # Mashing didn't clear it — a real decision point, not leftover text.
    still_locked = PlayerObservation(map_name="Pallet Town", x=5, y=5, dialog_active=True, joy_ignore=0x20)
    env.execute_skip_dialog = MagicMock(return_value=still_locked)  # type: ignore[method-assign]

    result = env.execute([GameAction.WALK_RIGHT])

    assert ["walk_right"] not in _posted_action_lists(env._client.post)
    assert result.stopped_early_because == "dialog_active"
    assert GameAction.WALK_RIGHT not in result.executed


def test_press_a_is_not_gated_during_dialog_lock(env: NousRedEnvironment):
    locked = _state(dialog_active=True, joy_ignore=0x20)
    env._client.get = MagicMock(
        return_value=MagicMock(status_code=200, json=lambda: locked, raise_for_status=lambda: None)
    )
    env._client.post = MagicMock(
        return_value=MagicMock(content=b"{}", json=lambda: {}, raise_for_status=lambda: None)
    )
    env.execute_skip_dialog = MagicMock(side_effect=AssertionError("must not mash for press_a"))
    env.observe = MagicMock(  # type: ignore[method-assign]
        return_value=PlayerObservation(map_name="Pallet Town", x=5, y=5, dialog_active=True, joy_ignore=0x20)
    )

    result = env.execute([GameAction.PRESS_A])

    assert ["press_a"] in _posted_action_lists(env._client.post)
    assert result.executed == [GameAction.PRESS_A]
