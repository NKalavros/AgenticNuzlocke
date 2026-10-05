"""Bounded JSON-lines subprocess transport. Never log child stderr or credentials."""

from __future__ import annotations

import json
import os
import queue
import signal
import subprocess
import threading
import time
from pathlib import Path

from nuzlocke.llm.base import ProviderError


class JsonProcess:
    def __init__(self, argv: list[str], *, cwd: Path, env: dict | None = None, timeout_s=120):
        self.timeout_s = timeout_s
        self.events: queue.Queue = queue.Queue()
        self.sequence = 0
        self.process = subprocess.Popen(
            argv,
            cwd=cwd,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            start_new_session=True,
        )
        self._reader = threading.Thread(target=self._read, daemon=True)
        self._stderr = threading.Thread(target=self._drain, daemon=True)
        self._reader.start()
        self._stderr.start()

    def _read(self):
        try:
            for line in self.process.stdout:
                try:
                    value = json.loads(line)
                    if isinstance(value, dict):
                        self.events.put(value)
                except ValueError:
                    # Some CLIs print startup notices. Never forward raw output.
                    continue
        finally:
            self.events.put(None)

    def _drain(self):
        for _ in self.process.stderr:
            pass

    def send(self, value: dict):
        try:
            self.process.stdin.write(json.dumps(value, separators=(",", ":")) + "\n")
            self.process.stdin.flush()
        except (OSError, ValueError):
            raise ProviderError("Model client disconnected") from None

    def receive(self, deadline: float) -> dict:
        try:
            message = self.events.get(timeout=max(0, deadline - time.monotonic()))
        except queue.Empty:
            raise ProviderError("Model client timed out; check authentication and connection") from None
        if message is None:
            raise ProviderError("Model client exited; check authentication and CLI compatibility")
        return message

    def request(self, method: str, params: dict, *, on_event=None) -> dict:
        self.sequence += 1
        request_id = self.sequence
        self.send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        deadline = time.monotonic() + self.timeout_s
        while True:
            message = self.receive(deadline)
            if message.get("id") == request_id and "method" not in message:
                if "error" in message:
                    # Remote messages may echo a prompt, key, or authorization URL.
                    error_text = json.dumps(message["error"]).lower()
                    if "no longer supported for gemini code assist for individuals" in error_text:
                        raise ProviderError(
                            "gemini_cli: Google retired personal-account CLI OAuth access. "
                            "Use an eligible Code Assist Standard/Enterprise account, or select "
                            "codex/claude_code. Google personal subscriptions now use Antigravity."
                        )
                    raise ProviderError(f"Model client rejected {method}; check login, model, quota, and CLI version")
                return message.get("result") or {}
            self.dispatch(message, on_event)

    def dispatch(self, message: dict, on_event=None):
        if "method" in message and "id" in message:
            if message["method"] == "session/request_permission":
                result = {"outcome": {"outcome": "cancelled"}}
            elif message["method"].endswith("/requestApproval"):
                result = {"decision": "decline"}
            else:
                self.send(
                    {"jsonrpc": "2.0", "id": message["id"], "error": {"code": -32601, "message": "Client tools are disabled"}}
                )
                return
            self.send({"jsonrpc": "2.0", "id": message["id"], "result": result})
        elif on_event:
            on_event(message)

    def close(self):
        if self.process.poll() is None:
            try:
                os.killpg(self.process.pid, signal.SIGTERM)
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                os.killpg(self.process.pid, signal.SIGKILL)
                self.process.wait(timeout=3)
            except ProcessLookupError:
                pass
        for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
            if stream:
                stream.close()
        self._reader.join(timeout=1)
        self._stderr.join(timeout=1)
