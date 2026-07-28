"""Append-only event store + lightweight SQLite views."""

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
        self.run_dir.mkdir(parents=True, exist_ok=True)
        (self.run_dir / "screenshots").mkdir(exist_ok=True)
        (self.run_dir / "checkpoints").mkdir(exist_ok=True)
        (self.run_dir / "agent_workspace").mkdir(exist_ok=True)
        self.events_path = self.run_dir / "events.jsonl"
        self.db_path = self.run_dir / "run.sqlite"
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
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
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO events (id, ts, kind, payload_json) VALUES (?, ?, ?, ?)",
                (event_id, ts, kind, json.dumps(payload)),
            )
        return event_id

    def set_meta(self, key: str, value: Any) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO run_meta (key, value_json) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json
                """,
                (key, json.dumps(value)),
            )

    def get_meta(self, key: str, default: Any = None) -> Any:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value_json FROM run_meta WHERE key = ?", (key,)
            ).fetchone()
        if row is None:
            return default
        return json.loads(row["value_json"])

    def recent(self, limit: int = 20, kind: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT id, ts, kind, payload_json FROM events"
        params: list[Any] = []
        if kind:
            query += " WHERE kind = ?"
            params.append(kind)
        query += " ORDER BY ts DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [
            {
                "id": r["id"],
                "ts": r["ts"],
                "kind": r["kind"],
                "payload": json.loads(r["payload_json"]),
            }
            for r in rows
        ]
