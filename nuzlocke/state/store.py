"""Append-only event log (events.jsonl), mirrored into run.sqlite."""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any


class EventStore:
    def __init__(self, run_dir: Path) -> None:
        self.run_dir = run_dir
        for sub in ("screenshots", "checkpoints", "agent_workspace"):
            (run_dir / sub).mkdir(parents=True, exist_ok=True)
        self.events_path = run_dir / "events.jsonl"
        self.db_path = run_dir / "run.sqlite"
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS events (
                    id TEXT PRIMARY KEY,
                    ts REAL NOT NULL,
                    kind TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS run_meta (
                    key TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL
                );
                """
            )

    def append(self, kind: str, payload: dict[str, Any]) -> str:
        event_id = f"evt-{uuid.uuid4().hex[:12]}"
        ts = time.time()
        record = {"id": event_id, "ts": ts, "kind": kind, "payload": payload}
        with self.events_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=True) + "\n")
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO events (id, ts, kind, payload_json) VALUES (?, ?, ?, ?)",
                (event_id, ts, kind, json.dumps(payload)),
            )
        return event_id

    def set_meta(self, key: str, value: Any) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO run_meta (key, value_json) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json
                """,
                (key, json.dumps(value)),
            )
