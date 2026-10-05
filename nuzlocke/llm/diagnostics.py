"""Non-inference diagnostics. Credential contents are never returned."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from nuzlocke.llm.cli_providers import client_env

LOGIN = {
    "codex": "codex login",
    "claude_code": "claude auth login",
    "gemini_cli": "gemini (choose Sign in with Google)",
    "antigravity": "agy (sign in with Google); agy models",
}


def doctor(cfg: dict) -> dict:
    rows = {}
    for role in ("system1", "system2") if cfg["provider"] == "dual" else ("system2",):
        options = cfg[role]
        name = options["provider"]
        row = {"provider": name, "model": options["model"] or "vendor default", "ready": False}
        rows[role] = row
        if not options.get("binary"):
            key = os.environ.get(options.get("api_key_env") or "")
            if name == "jev":
                key = key or os.environ.get("TYPESAFE_API_KEY")
            row["ready"] = bool(key or options.get("api_key_default"))
            row["authentication"] = "credential configured" if row["ready"] else "missing credential"
            row["setup"] = f"Set {options.get('api_key_env')} in the environment or .env"
            continue
        binary = shutil.which(options["binary"])
        row["binary"] = binary
        row["setup"] = LOGIN[name]
        if not binary:
            row["authentication"] = "client not installed"
            continue
        try:
            env = client_env()
            version = subprocess.run([binary, "--version"], capture_output=True, text=True, env=env, timeout=15, check=False)
            row["version"] = version.stdout.strip().splitlines()[0][:100] if version.stdout.strip() else "unknown"
            if name == "codex":
                result = subprocess.run(
                    [binary, "login", "status"], capture_output=True, text=True, env=env, timeout=15, check=False
                )
                row["ready"] = result.returncode == 0 and "ChatGPT" in result.stdout + result.stderr
                row["authentication"] = "ChatGPT login" if row["ready"] else "ChatGPT login required"
            elif name == "claude_code":
                result = subprocess.run(
                    [binary, "auth", "status"], capture_output=True, text=True, env=env, timeout=15, check=False
                )
                status = json.loads(result.stdout)
                row["ready"] = bool(status.get("loggedIn") and status.get("authMethod") in {"oauth_token", "claude_ai"})
                row["authentication"] = "subscription login" if row["ready"] else "subscription login required"
            elif name == "antigravity":
                from nuzlocke.llm.antigravity_provider import available_models
                from nuzlocke.llm.base import ProviderError

                try:
                    models = available_models(binary)
                    row["models"] = models
                    row["ready"] = not options["model"] or options["model"] in models
                    row["authentication"] = "Google model access verified" if row["ready"] else "selected model unavailable"
                except ProviderError:
                    row["authentication"] = "Google model access unavailable; sign in with agy"
            else:
                row["availability"] = (
                    "Google retired personal-account Gemini CLI access; "
                    "Code Assist Standard/Enterprise eligibility is required. "
                    "A cached login alone does not establish eligibility."
                )
                root = Path(os.environ.get("GEMINI_CLI_HOME") or Path.home()) / ".gemini"
                row["ready"] = (root / "oauth_creds.json").is_file()
                row["authentication"] = (
                    "Google credential cache present (validity checked on use)" if row["ready"] else "Google login required"
                )
        except (OSError, ValueError, subprocess.TimeoutExpired):
            row["authentication"] = "client status unavailable"
    return {
        "ready": all(row["ready"] for row in rows.values()),
        "systems": rows,
        "note": "No inference performed. Model access, quota, and cached-token validity are checked when used.",
    }
