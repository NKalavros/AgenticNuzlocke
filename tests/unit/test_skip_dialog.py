"""skip_dialog must not be able to re-open the NPC it just finished reading.

Regression cover for run 20260821-164159-3c5a68, where the macro mashed
`hold_b_120 + press_a` and exited only on a joy_ignore bit-5 transition. Red
Star reports joy_ignore=0 through real dialog, so the exit never fired: every
call ran all its rounds and the final A re-opened Prof Oak. 33 minutes and
~200 vision calls went into that 2-cycle.
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
    e._joy_ignore = MagicMock(return_value=0)  # type: ignore[method-assign]
    return e


def _posted(post: MagicMock) -> list[list[str]]:
    return [
        c.kwargs["json"]["actions"]
        for c in post.call_args_list
        if c.args[0].endswith("/action")
    ]


def test_skip_dialog_never_presses_a(env: NousRedEnvironment):
    """A is what re-opens an NPC. B advances Gen 1 text just as well."""
    post = MagicMock()
    env._client.post = post
    env._dialog_digest = MagicMock(side_effect=lambda: "same")  # type: ignore[method-assign]

    env.execute_skip_dialog()

    flat = [button for burst in _posted(post) for button in burst]
    assert flat, "expected at least one mash round"
    assert "press_a" not in flat
    assert "hold_a_30" not in flat
    assert set(flat) == {"hold_b_120"}


def test_skip_dialog_stops_once_the_text_box_stops_changing(env: NousRedEnvironment):
    post = MagicMock()
    env._client.post = post
    env._dialog_digest = MagicMock(return_value="quiet")  # type: ignore[method-assign]

    env.execute_skip_dialog(max_rounds=6)

    # First round matches the pre-read, second confirms → stop at 2, not 6.
    assert len(_posted(post)) == 2


def test_skip_dialog_keeps_mashing_while_text_advances(env: NousRedEnvironment):
    post = MagicMock()
    env._client.post = post
    pages = iter(["a", "b", "c", "d", "e", "f", "g", "h"])
    env._dialog_digest = MagicMock(  # type: ignore[method-assign]
        side_effect=lambda: next(pages, "end")
    )

    env.execute_skip_dialog(max_rounds=4)

    assert len(_posted(post)) == 4


def test_skip_dialog_yields_to_the_naming_keyboard(env: NousRedEnvironment):
    """Bit 6 is the one joy_ignore bit that held up across a full run."""
    post = MagicMock()
    env._client.post = post
    env._joy_ignore = MagicMock(return_value=0x40)  # type: ignore[method-assign]
    env._dialog_digest = MagicMock(return_value="x")  # type: ignore[method-assign]

    env.execute_skip_dialog()

    assert _posted(post) == []


def test_a_until_dialog_end_is_served_by_our_macro(env: NousRedEnvironment):
    """pokemon-agent's own opcode checks a flat dialog_active key wrongly."""
    env.peek_state = MagicMock(  # type: ignore[method-assign]
        return_value=MagicMock(joy_ignore=0, dialog_active=False, in_battle=False, map_name="Oak's Lab")
    )
    env.execute_skip_dialog = MagicMock(  # type: ignore[method-assign]
        return_value=MagicMock(
            joy_ignore=0, in_battle=False, map_name="Oak's Lab", dialog_active=False
        )
    )

    result = env.execute([GameAction.A_UNTIL_DIALOG_END])

    env.execute_skip_dialog.assert_called_once()
    assert result.executed == [GameAction.A_UNTIL_DIALOG_END]
