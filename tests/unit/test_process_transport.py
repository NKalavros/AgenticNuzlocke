"""Exercise actual subprocess I/O, permissions and cleanup without inference."""

import sys
import time

import pytest

from nuzlocke.llm.base import ProviderError
from nuzlocke.llm.process_transport import JsonProcess


def test_rpc_interleaves_notifications_and_denies_permissions(tmp_path):
    script = """import json,sys
request=json.loads(input())
print(json.dumps({"jsonrpc":"2.0","id":99,"method":"session/request_permission","params":{}}),flush=True)
reply=json.loads(input())
assert reply["result"]["outcome"]["outcome"] == "cancelled"
print(json.dumps({"method":"progress","params":{"text":"ready"}}),flush=True)
print(json.dumps({"id":request["id"],"result":{"ok":True}}),flush=True)
"""
    process = JsonProcess([sys.executable, "-u", "-c", script], cwd=tmp_path, timeout_s=2)
    events = []
    try:
        assert process.request("test", {}, on_event=events.append) == {"ok": True}
        assert events[0]["method"] == "progress"
    finally:
        process.close()
    assert process.process.poll() is not None


def test_timeout_can_be_closed_without_leaking_process(tmp_path):
    process = JsonProcess(
        [sys.executable, "-u", "-c", "import time; time.sleep(10)"], cwd=tmp_path, timeout_s=0.05
    )
    try:
        with pytest.raises(ProviderError, match="timed out"):
            process.receive(time.monotonic() + 0.05)
    finally:
        process.close()
    assert process.process.poll() is not None


def test_gemini_retirement_error_is_actionable_and_redacted(tmp_path):
    script = """import json
request=json.loads(input())
print(json.dumps({"id":request["id"],"error":{"message":"This client is no longer supported for Gemini Code Assist for individuals. secret-sentinel"}}),flush=True)
"""
    process = JsonProcess([sys.executable, "-u", "-c", script], cwd=tmp_path, timeout_s=2)
    try:
        with pytest.raises(ProviderError, match="Standard/Enterprise") as err:
            process.request("session/new", {})
        assert "secret-sentinel" not in str(err.value)
    finally:
        process.close()
