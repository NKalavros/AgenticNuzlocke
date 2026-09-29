"""Append-only event log (events.jsonl), mirrored into run.sqlite."""

from __future__ import annotations

import hashlib
import json
import os
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
        if kind in {
            "ledger_commit",
            "candy_grant",
            "candy_use",
            "nuzlocke_wipe",
            "milestone_complete",
        }:
            with sqlite3.connect(self.db_path) as conn:
                row = conn.execute(
                    "SELECT value_json FROM run_meta WHERE key='integrity_head'"
                ).fetchone()
            record["previous_hash"] = json.loads(row[0]) if row else None
            record["hash"] = hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest()
        with self.events_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=True) + "\n")
            if "hash" in record:
                f.flush()
                os.fsync(f.fileno())
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO events (id, ts, kind, payload_json) VALUES (?, ?, ?, ?)",
                (event_id, ts, kind, json.dumps(payload)),
            )
            if "hash" in record:
                conn.execute(
                    "INSERT OR REPLACE INTO run_meta VALUES ('integrity_head', ?)",
                    (json.dumps(record["hash"]),),
                )
        return event_id

    def integrity_head(self, *, verify: bool = False) -> str | None:
        from nuzlocke.orchestration.checkpoint import IntegrityError

        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT value_json FROM run_meta WHERE key='integrity_head'"
            ).fetchone()
        expected = json.loads(row[0]) if row else None
        if not verify:
            return expected
        head = None
        if self.events_path.exists():
            try:
                with self.events_path.open() as events:
                    for line in events:
                        event = json.loads(line)
                        digest = event.pop("hash", None)
                        if digest is None:
                            continue
                        if (
                            event.get("previous_hash") != head
                            or hashlib.sha256(
                                json.dumps(event, sort_keys=True).encode()
                            ).hexdigest()
                            != digest
                        ):
                            raise IntegrityError("Rule-event history checksum mismatch")
                        head = digest
            except (ValueError, OSError) as exc:
                raise IntegrityError("Rule-event history is incomplete") from exc
        if head != expected:
            raise IntegrityError("Rule-event history and database disagree")
        return head

    def set_meta(self, key: str, value: Any) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO run_meta (key, value_json) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json
                """,
                (key, json.dumps(value)),
            )
