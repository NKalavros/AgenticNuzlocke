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
    e = NousRedEnvironment(base_url="http://127.0.0.1:8765", run_dir=tmp_path, auto_start=False)
    e._client = MagicMock()
    return e


def _json_response(payload):
    return MagicMock(content=b"{}", json=lambda: payload, raise_for_status=lambda: None)


def test_save_checkpoint_verifies_only_the_saved_file(env: NousRedEnvironment):
    import hashlib

    saved = env.run_dir / "data" / "saves" / "auto.state"
    saved.parent.mkdir(parents=True)
    saved.write_bytes(b"verified state")
    env._client.post = MagicMock(return_value=_json_response({"success": True, "path": str(saved)}))
    env._client.get = MagicMock(
        return_value=_json_response({"name": "auto", "sha256": hashlib.sha256(saved.read_bytes()).hexdigest()})
    )
    assert env.save_checkpoint("auto")["success"] is True
    assert env._client.get.call_args.args[0].endswith("/nuzlocke/saves/auto")
    assert env._client.get.call_count == 1


def test_save_checkpoint_rejects_a_different_server_file(env: NousRedEnvironment):
    saved = env.run_dir / "saved.state"
    saved.write_bytes(b"new state")
    env._client.post = MagicMock(return_value=_json_response({"success": True, "path": str(saved)}))
    env._client.get = MagicMock(return_value=_json_response({"name": "auto", "sha256": "stale checksum"}))
    with pytest.raises(RuntimeError, match="differs"):
        env.save_checkpoint("auto")


def test_save_checkpoint_requires_the_local_save(env: NousRedEnvironment):
    env._client.post = MagicMock(return_value=_json_response({"success": True}))
    env._client.get = MagicMock(return_value=_json_response({"name": "auto"}))
    with pytest.raises(RuntimeError, match="verifiable local save"):
        env.save_checkpoint("auto")


def test_saved_checkpoint_reads_only_flat_storage(tmp_path):
    import hashlib

    from fastapi import HTTPException
    from nuzlocke.environment.pa_serve import saved_checkpoint

    scoped = tmp_path / "games" / "session" / "saves" / "auto.state"
    scoped.parent.mkdir(parents=True)
    scoped.write_bytes(b"state")
    with pytest.raises(HTTPException) as err:
        saved_checkpoint(tmp_path, "auto")
    assert err.value.status_code == 404
    flat = tmp_path / "saves" / "auto.state"
    flat.parent.mkdir()
    flat.write_bytes(scoped.read_bytes())
    assert saved_checkpoint(tmp_path, "auto") == {"name": "auto", "sha256": hashlib.sha256(b"state").hexdigest()}
    with pytest.raises(HTTPException) as err:
        saved_checkpoint(tmp_path, "../auto")
    assert err.value.status_code == 400


def test_list_checkpoints_returns_flat_list(env: NousRedEnvironment):
    env._client.get = MagicMock(return_value=_json_response({"saves": [{"name": "auto"}, {"name": "old"}]}))
    names = {s["name"] for s in env.list_checkpoints()}
    assert names == {"auto", "old"}
