"""The headless sandbox copies a savestate and never reuses a live port."""

from __future__ import annotations

import json
import socket
from pathlib import Path
from types import SimpleNamespace

import pytest

from nuzlocke.orchestration.sandbox import (
    format_rows,
    free_port,
    new_sandbox,
    parse_script,
    run_script,
    summarize,
)
from nuzlocke.state.models import GameAction


def test_script_tokens_repeat_and_mix_raw_opcodes():
    assert parse_script("skip_dialog, walk_down*2 hold_b_30 wait_30") == [
        "skip_dialog",
        "walk_down",
        "walk_down",
        "hold_b_30",
        "wait_30",
    ]


def test_an_unknown_button_is_refused():
    with pytest.raises(ValueError, match="unknown button"):
        parse_script("walk_down jump")


def test_a_sandbox_copies_the_source_savestate(tmp_path: Path):
    source = tmp_path / "runs" / "live-run" / "pokemon-agent-data" / "saves"
    source.mkdir(parents=True)
    (source / "auto.state").write_bytes(b"state")

    run_id, run_dir = new_sandbox("live-run", root=tmp_path)

    assert run_id.startswith("sandbox-")
    assert (run_dir / "savestates" / "auto.state").read_bytes() == b"state"
    meta = json.loads((run_dir / "sandbox.json").read_text())
    assert meta["source"] == "live-run"
    # The live run's own file is untouched.
    assert (source / "auto.state").read_bytes() == b"state"


def test_a_missing_savestate_is_an_error(tmp_path: Path):
    (tmp_path / "runs" / "empty").mkdir(parents=True)
    with pytest.raises(FileNotFoundError):
        new_sandbox("empty", root=tmp_path)


def test_free_port_skips_a_port_in_use():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen(1)
        taken = busy.getsockname()[1]
        assert free_port(start=taken, tries=5) != taken


def _obs(x: int, y: int) -> SimpleNamespace:
    return SimpleNamespace(map_name="Oak's Lab", x=x, y=y, facing="down", screenshot_path=None)


class _FakeEnv:
    def __init__(self) -> None:
        self.y = 3
        self.raw: list[list[str]] = []
        self.executed: list[GameAction] = []

    def observe(self):
        return _obs(5, self.y)

    def execute(self, actions):
        self.executed.extend(actions)
        if actions == [GameAction.WALK_DOWN]:
            self.y += 1
        return SimpleNamespace(
            observation=_obs(5, self.y), executed=list(actions), stopped_early_because=None
        )

    def _post_json(self, path, payload):
        self.raw.append(payload["actions"])


def test_a_script_uses_the_harness_for_actions_and_raw_for_opcodes(tmp_path: Path):
    env = _FakeEnv()

    rows = run_script(env, ["walk_down", "wait_30"], tmp_path / "frames")  # type: ignore[arg-type]

    assert env.executed == [GameAction.WALK_DOWN]
    assert env.raw == [["wait_30"]]
    assert [(row["button"], row["y"]) for row in rows] == [
        ("start", 3),
        ("walk_down", 4),
        ("wait_30", 4),
    ]
    assert "walk_down" in format_rows(rows)


def test_summary_reads_only_the_last_session(tmp_path: Path):
    events = [
        {"kind": "run_start", "ts": 0.0, "payload": {}},
        {"kind": "arbiter", "ts": 1.0, "payload": {"executed_actions": ["press_a"]}},
        {"kind": "run_start", "ts": 10.0, "payload": {}},
        {"kind": "observation", "ts": 10.1, "payload": {"map_name": "Lab", "x": 5, "y": 3}},
        {"kind": "plan", "ts": 10.2, "payload": {"latency_s": 4.0}},
        {
            "kind": "jev",
            "ts": 10.3,
            "payload": {"reason": "speech on screen; skip_dialog", "looks": ["plan spent"]},
        },
        {
            "kind": "arbiter",
            "ts": 11.0,
            "payload": {
                "executed_actions": ["skip_dialog"],
                "stopped_early_because": "skip_dialog",
            },
        },
        {"kind": "observation", "ts": 11.1, "payload": {"map_name": "Lab", "x": 5, "y": 4}},
        {
            "kind": "arbiter",
            "ts": 12.0,
            "payload": {"executed_actions": ["walk_down"], "stopped_early_because": None},
        },
    ]
    (tmp_path / "events.jsonl").write_text("\n".join(json.dumps(e) for e in events))

    report = summarize(tmp_path)

    assert report["cycles"] == 2
    assert report["planner_looks"] == 1
    assert report["looks_by_reason"] == {"plan spent": 1}
    assert report["planner_s"] == {"median": 4.0, "p90": 4.0, "total": 4.0}
    assert report["buttons"] == {"skip_dialog": 1, "walk_down": 1}
    assert report["distinct_tiles"] == 2
    assert report["reasons"] == {"speech on screen": 1}
    assert report["jev"] is None


def test_summary_reports_jev_calls(tmp_path: Path):
    call = {"scene": "overworld", "state_bytes": 900, "latency_s": 0.2}
    events = [
        {"kind": "run_start", "ts": 0.0, "payload": {}},
        {"kind": "jev_call", "ts": 1.0, "payload": {**call, "confidence": 0.8, "accepted": True}},
        {"kind": "jev_call", "ts": 2.0, "payload": {**call, "confidence": 0.3, "accepted": False}},
    ]
    (tmp_path / "events.jsonl").write_text("\n".join(json.dumps(e) for e in events))

    jev = summarize(tmp_path)["jev"]

    assert jev["calls"] == 2
    assert jev["unsure_share"] == 0.5
    assert jev["state_bytes_mean"] == 900
    assert jev["by_scene"] == {"overworld": 2}
