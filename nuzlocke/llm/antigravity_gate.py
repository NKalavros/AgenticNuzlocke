"""Antigravity hook: permit only this turn's screenshots, attest successful reads.

Executed directly by the vendor CLI with the runner's Python executable.
No vendor credential files are read or copied.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def gate(payload: dict, manifest: dict) -> dict:
    call = payload.get("toolCall") or {}
    args = call.get("args") or {}
    path = args.get("AbsolutePath")
    allowed = (
        call.get("name") == "view_file"
        and isinstance(path, str)
        and Path(path).is_absolute()
        and str(Path(path).resolve()) in manifest.get("images", [])
    )
    return {
        "decision": "allow" if allowed else "deny",
        "reason": "The Nuzlocke planner may only read the screenshots supplied for this turn.",
    }


def main() -> None:
    decision = {"decision": "deny", "reason": "Nuzlocke screenshot gate failed validation."}
    try:
        mode, root = sys.argv[1], Path(sys.argv[2])
        manifest = json.loads((root / "turn.json").read_text())
        payload = json.load(sys.stdin)
        decision = gate(payload, manifest)
        if mode == "post":
            if decision["decision"] == "allow" and not payload.get("error"):
                path = str(Path(payload["toolCall"]["args"]["AbsolutePath"]).resolve())
                with (root / "viewed.jsonl").open("a") as stream:
                    stream.write(json.dumps({"image": path, "turn": manifest["turn"]}) + "\n")
            decision = {}
    except (OSError, ValueError, TypeError, KeyError, IndexError, AttributeError):
        pass
    print(json.dumps(decision))


if __name__ == "__main__":
    main()
