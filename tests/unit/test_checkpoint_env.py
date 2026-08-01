"""save_checkpoint must verify pokemon-agent actually wrote where /load reads.

pokemon-agent routes /save into a session-scoped folder whenever a dashboard
game session is active, but /load always reads the flat saves/ dir — a
silent mismatch that would otherwise make crash-recovery checkpoints
unloadable without any error.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from nuzlocke.environment.nous_red import NousRedEnvironment


@pytest.fixture
def env(tmp_path: Path) -> NousRedEnvironment:
    e = NousRedEnvironment(
        base_url="http://127.0.0.1:8765", run_dir=tmp_path, auto_start=False
    )
    e._client = MagicMock()
    return e


def _json_response(payload):
    return MagicMock(content=b"{}", json=lambda: payload, raise_for_status=lambda: None)


def test_save_checkpoint_succeeds_when_flat_listing_has_it(env: NousRedEnvironment):
    env._client.post = MagicMock(return_value=_json_response({"success": True}))
    env._client.get = MagicMock(
        return_value=_json_response({"saves": [{"name": "auto"}]})
    )
    result = env.save_checkpoint("auto")
    assert result["success"] is True


def test_save_checkpoint_raises_when_session_scoped(env: NousRedEnvironment):
    env._client.post = MagicMock(
        return_value=_json_response({"success": True, "session": "some-session-id"})
    )
    env._client.get = MagicMock(return_value=_json_response({"saves": []}))
    with pytest.raises(RuntimeError, match="session-scoped"):
        env.save_checkpoint("auto")


def test_list_checkpoints_returns_flat_list(env: NousRedEnvironment):
    env._client.get = MagicMock(
        return_value=_json_response({"saves": [{"name": "auto"}, {"name": "old"}]})
    )
    names = {s["name"] for s in env.list_checkpoints()}
    assert names == {"auto", "old"}
