"""Mid-burst execute uses peek_state; full observe only at cycle end."""

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
    return e


def _state(
    *,
    map_name: str = "Pallet Town",
    x: int = 5,
    y: int = 5,
    dialog_active: bool = False,
    joy_ignore: int = 0,
    in_battle: bool = False,
) -> dict:
    return {
        "player": {
            "position": {"x": x, "y": y, "map_name": map_name},
            "facing": "DOWN",
            "name": "RED",
        },
        "map": {"map_name": map_name, "map_id": 0},
        "dialog": {"active": dialog_active, "joy_ignore": joy_ignore, "text": None},
        "battle": {"in_battle": in_battle, "type": "wild" if in_battle else "none"},
        "party": [],
        "bag": [],
        "metadata": {"frame_count": 1},
    }


def test_execute_peeks_mid_burst_and_observes_once(env: NousRedEnvironment, tmp_path: Path):
    get = MagicMock()
    post = MagicMock()

    state = _state()
    get.side_effect = lambda url: MagicMock(
        status_code=200,
        content=b"\x89PNG",
        headers={"content-type": "application/json"},
        json=lambda: state if url.endswith("/state") else {"map": "."},
        text=".",
        raise_for_status=lambda: None,
    )
    post.return_value = MagicMock(
        content=b"{}",
        json=lambda: {},
        raise_for_status=lambda: None,
    )
    env._client.get = get
    env._client.post = post

    # Avoid PIL blank-frame path needing a real PNG structure beyond open.
    shots: list[str] = []

    def fake_screenshot(path: str | None = None) -> bytes:
        data = b"png"
        if path:
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
            shots.append(path)
        return data

    env.screenshot = fake_screenshot  # type: ignore[method-assign]

    result = env.execute([GameAction.WALK_UP, GameAction.WALK_UP, GameAction.PRESS_A])
    assert len(result.executed) == 3
    # One full observe at end → one screenshot (not per button).
    assert len(shots) == 1
    # Mid-burst peeks + final observe all hit /state.
    state_gets = [c for c in get.call_args_list if str(c.args[0]).endswith("/state")]
    assert len(state_gets) >= 4  # peek before + 3 peeks after buttons (+ observe state)


def test_peek_state_skips_screenshot(env: NousRedEnvironment):
    state = _state()
    env._client.get = MagicMock(
        return_value=MagicMock(
            status_code=200,
            json=lambda: state,
            raise_for_status=lambda: None,
        )
    )
    called = {"n": 0}

    def boom(path: str | None = None) -> bytes:
        called["n"] += 1
        raise AssertionError("screenshot should not run on peek")

    env.screenshot = boom  # type: ignore[method-assign]
    obs = env.peek_state()
    assert obs.map_name == "Pallet Town"
    assert obs.screenshot_path is None
    assert called["n"] == 0
