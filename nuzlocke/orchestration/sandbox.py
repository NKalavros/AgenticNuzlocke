"""Headless sandbox: a private emulator for trying a fix on a real savestate.

A sandbox copies a run's savestate into ``runs/sandbox-*``, starts its own
pokemon-agent on a free port, and presses a script (no LLM) or runs the real
loop headless. The emulator only advances inside ``/action``, so the same
savestate and the same buttons give the same frames every time.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import socket
import statistics
import time
import uuid
from collections import Counter
from pathlib import Path
from typing import Any

from nuzlocke.config import project_root
from nuzlocke.environment import screen
from nuzlocke.environment.nous_red import NousRedEnvironment
from nuzlocke.orchestration.checkpoint import CHECKPOINT_NAME, savestate_path
from nuzlocke.state.models import GameAction

SANDBOX_PORT = 8791
_RAW_KINDS = ("press_", "walk_", "hold_", "wait_")
_ACTIONS = {action.value for action in GameAction}


def free_port(host: str = "127.0.0.1", start: int = SANDBOX_PORT, tries: int = 50) -> int:
    """First port from ``start`` with nothing listening on it."""
    for port in range(start, start + tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.2)
            if sock.connect_ex((host, port)) != 0:
                return port
    raise RuntimeError(f"no free port in {start}..{start + tries - 1}")


def source_savestate(run_dir: Path, state: str = CHECKPOINT_NAME) -> Path:
    """The savestate a run left behind, wherever that run wrote it."""
    for candidate in (
        savestate_path(run_dir, state),
        run_dir / "pokemon-agent-data" / "saves" / f"{state}.state",
    ):
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"no {state}.state under {run_dir}")


def new_sandbox(
    source: str | None, *, state: str = CHECKPOINT_NAME, root: Path | None = None
) -> tuple[str, Path]:
    """Make ``runs/sandbox-*`` and copy ``source``'s savestate in as its continue point."""
    runs = (root or project_root()) / "runs"
    run_id = "sandbox-" + time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4]
    run_dir = runs / run_id
    run_dir.mkdir(parents=True)
    meta: dict[str, Any] = {"source": source, "state": state, "created": time.time()}
    if source:
        src = source_savestate(runs / source, state)
        dest = savestate_path(run_dir, CHECKPOINT_NAME)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        meta["savestate"] = str(src)
        source_dir = runs / source
        record_path = source_dir / "checkpoints" / (
            "current.json" if state == CHECKPOINT_NAME else f"{state}.json"
        )
        if record_path.exists():
            record = json.loads(record_path.read_text())
            if record.get("state_sha256") == hashlib.sha256(src.read_bytes()).hexdigest():
                shutil.copy2(record_path, run_dir / "sandbox-controller.json")
                meta["controller_history"] = "paired diagnostic copy"
                meta["source_sequence"] = record.get("sequence")
        meta.setdefault("controller_history", "legacy: empty controller")
    (run_dir / "sandbox.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return run_id, run_dir


def parse_script(text: str) -> list[str]:
    """Comma- or space-separated buttons. ``walk_up*3`` repeats a token."""
    tokens: list[str] = []
    for raw in text.replace(",", " ").split():
        name, _, count = raw.partition("*")
        name = name.strip().lower()
        if not name:
            continue
        if name not in _ACTIONS and not name.startswith(_RAW_KINDS):
            raise ValueError(
                f"unknown button {name!r}: use a GameAction (skip_dialog, walk_up_3, "
                "press_a, ...) or a raw pokemon-agent opcode (press_X, walk_X, "
                "hold_X_N, wait_N)"
            )
        tokens.extend([name] * (int(count) if count else 1))
    return tokens


def run_script(
    env: NousRedEnvironment, tokens: list[str], frames_dir: Path
) -> list[dict[str, Any]]:
    """Press each token and record where the player is and what is on screen.

    A GameAction goes through ``execute`` (burst stops, ``skip_dialog``); any
    other token is one raw ``/action`` opcode.
    """
    frames_dir.mkdir(parents=True, exist_ok=True)
    rows = [_row(0, "start", env.observe(), frames_dir)]
    for index, token in enumerate(tokens, start=1):
        if token in _ACTIONS:
            result = env.execute([GameAction(token)])
            obs, stopped = result.observation, result.stopped_early_because
            executed = [a.value for a in result.executed]
        else:
            env._post_json("/action", {"actions": [token]})
            obs, executed, stopped = env.observe(), [token], None
        rows.append(_row(index, token, obs, frames_dir, executed, stopped))
    return rows


def _row(
    index: int,
    token: str,
    obs: Any,
    frames_dir: Path,
    executed: list[str] | None = None,
    stopped: str | None = None,
) -> dict[str, Any]:
    path = None
    if obs.screenshot_path and Path(obs.screenshot_path).is_file():
        path = str(frames_dir / f"{index:03d}_{token}.png")
        shutil.copy2(obs.screenshot_path, path)
    world, dialog = screen.digests_from_path(path)
    return {
        "index": index,
        "button": token,
        "executed": executed,
        "stopped": stopped,
        "map": obs.map_name,
        "x": obs.x,
        "y": obs.y,
        "facing": obs.facing,
        "text_box": screen.text_box_open(path),
        "prompt_box": screen.prompt_box_open(path),
        "world_digest": world[:8],
        "dialog_digest": dialog[:8],
        "frame": path,
    }


def format_rows(rows: list[dict[str, Any]]) -> str:
    lines = []
    for row in rows:
        box = "prompt" if row["prompt_box"] else ("text" if row["text_box"] else "-")
        stop = f" stop={row['stopped']}" if row["stopped"] else ""
        lines.append(
            f"{row['index']:3d} {row['button']:<14} {row['map']} "
            f"({row['x']},{row['y']}) {row['facing'] or '?':<5} box={box:<6} "
            f"world={row.get('world_digest', '')} dlg={row['dialog_digest']}{stop}"
        )
    return "\n".join(lines)


def _spread(values: list[float]) -> dict[str, float] | None:
    if not values:
        return None
    ordered = sorted(values)
    return {
        "median": round(statistics.median(ordered), 2),
        "p90": round(ordered[min(len(ordered) - 1, int(0.9 * len(ordered)))], 2),
        "total": round(sum(ordered), 1),
    }


def summarize(run_dir: Path) -> dict[str, Any]:
    """What the last session of a run did, read back from ``events.jsonl``."""
    path = run_dir / "events.jsonl"
    events = [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    starts = [i for i, event in enumerate(events) if event["kind"] == "run_start"]
    session = events[starts[-1] :] if starts else events
    buttons: Counter[str] = Counter()
    stops: Counter[str] = Counter()
    reasons: Counter[str] = Counter()
    looks: Counter[str] = Counter()
    planner: list[float] = []
    jev_calls: list[dict[str, Any]] = []
    tiles: list[tuple[Any, Any, Any]] = []
    cycle_times: list[float] = []
    last_ts: float | None = None
    last_observation: dict[str, Any] = {}
    rule_alerts = 0
    eligibility_alerts = 0
    for event in session:
        kind, payload = event["kind"], event["payload"]
        if kind == "observation":
            last_observation = payload
            tile = (payload.get("map_name"), payload.get("x"), payload.get("y"))
            if not tiles or tiles[-1] != tile:
                tiles.append(tile)
        elif kind == "party_ineligible":
            eligibility_alerts += 1
        elif kind == "rule_violation":
            # Older runs labeled the post-battle/pre-badge cap gap as a violation.
            if last_observation and not last_observation.get("in_battle"):
                eligibility_alerts += 1
            else:
                rule_alerts += 1
        elif kind == "plan" and payload.get("latency_s") is not None:
            planner.append(float(payload["latency_s"]))
        elif kind == "jev_call":
            jev_calls.append(payload)
        elif kind == "jev":
            reasons[str(payload.get("reason") or "").split(";")[0][:40]] += 1
            looks.update(payload.get("looks") or [])
        elif kind == "arbiter":
            buttons.update(payload.get("executed_actions") or [])
            stops[str(payload.get("stopped_early_because"))] += 1
            if last_ts is not None:
                cycle_times.append(event["ts"] - last_ts)
            last_ts = event["ts"]
    cycles = sum(stops.values())
    return {
        "cycles": cycles,
        "completed_brock": any(
            e["kind"] == "milestone_complete" and e["payload"].get("milestone") == "brock"
            for e in session
        ),
        "wiped": any(e["kind"] == "nuzlocke_wipe" for e in session),
        "rule_alerts": rule_alerts,
        "eligibility_alerts": eligibility_alerts,
        "policy_rejections": sum(e["kind"] == "policy_rejection" for e in session),
        "candy_grants": sum(
            e["payload"].get("granted", 0) for e in session if e["kind"] == "candy_grant"
        ),
        "candy_uses": sum(e["kind"] == "candy_use" for e in session),
        "casualties": max(
            (len(e["payload"].get("deaths", [])) for e in session if e["kind"] == "ledger_commit"),
            default=0,
        ),
        "planner_looks": sum(1 for e in session if e["kind"] == "plan"),
        "looks_by_reason": dict(looks.most_common()),
        "planner_s": _spread(planner),
        "recoveries": sum(1 for e in session if e["kind"] == "recovery"),
        "seconds": round(session[-1]["ts"] - session[0]["ts"], 1) if session else 0.0,
        "median_cycle_s": round(statistics.median(cycle_times), 2) if cycle_times else None,
        "distinct_tiles": len(set(tiles)),
        "path": [f"{m} ({x},{y})" for m, x, y in tiles[-12:]],
        "buttons": dict(buttons.most_common(10)),
        "stops": dict(stops.most_common()),
        "reasons": dict(reasons.most_common(8)),
        "jev": _jev_stats(jev_calls),
    }


def _jev_stats(calls: list[dict[str, Any]]) -> dict[str, Any] | None:
    """How sure Jev was, how big its input was, and how long it took."""
    if not calls:
        return None
    confidence = sorted(float(call.get("confidence") or 0.0) for call in calls)
    size = [int(call.get("state_bytes") or 0) for call in calls]
    latency = [float(call["latency_s"]) for call in calls if call.get("latency_s") is not None]
    unsure = sum(1 for call in calls if not call.get("accepted"))
    return {
        "calls": len(calls),
        "confidence_p10": round(confidence[int(0.1 * (len(confidence) - 1))], 3),
        "confidence_p50": round(statistics.median(confidence), 3),
        "unsure_share": round(unsure / len(calls), 3),
        "state_bytes_mean": round(statistics.mean(size)),
        "latency_s": _spread(latency),
        "by_scene": dict(Counter(str(call.get("scene")) for call in calls).most_common()),
    }


def benchmark(*, trials: int = 5, steps: int = 1500, rom: Path | None = None) -> dict[str, Any]:
    """Independent fresh boots; failures are retained, never retried into the success count."""
    from nuzlocke.orchestration.loop import RunLoop

    if trials < 1 or steps < 1:
        raise ValueError("benchmark requires positive trials and steps")
    reports = []
    for trial in range(trials):
        run_id, run_dir = new_sandbox(None)
        loop = None
        error = None
        try:
            loop = RunLoop(rom_path=rom, run_id=run_id, port=free_port(), headless=True)
            loop.run(max_steps=steps)
        except Exception as exc:  # noqa: BLE001 — retain failed trials of every kind
            error = f"{type(exc).__name__}: {exc}"
        finally:
            if loop is not None:
                loop.env.shutdown()
        report = summarize(run_dir) if (run_dir / "events.jsonl").exists() else {}
        report.update(trial=trial + 1, run_id=run_id, error=error)
        (run_dir / "summary.json").write_text(json.dumps(report, indent=2))
        reports.append(report)
    return {
        "trials": reports,
        "passed": len(reports) == trials
        and all(
            r.get("completed_brock")
            and not r.get("wiped")
            and not r.get("error")
            and not r.get("rule_alerts")
            for r in reports
        ),
    }
