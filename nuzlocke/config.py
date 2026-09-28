"""Config loading helpers."""

from __future__ import annotations

import os
import socket
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Expected mapping in {path}")
    return data


def project_root() -> Path:
    return ROOT


def load_project_env(path: Path | None = None) -> None:
    """Load KEY=VALUE lines from ``.env`` without overriding the real environment.

    Values already set in the process win. The file is never logged.
    """
    env_path = path or (ROOT / ".env")
    if not env_path.is_file():
        return
    try:
        text = env_path.read_text(encoding="utf-8")
    except OSError:
        return
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value


# Hosts that must not be sent through gost. The emulator and the Cursor SDK
# bridge both listen on loopback; the proxy answers those with an empty 503.
_LOOPBACK_NO_PROXY = ("127.0.0.1", "localhost", "::1")
_PROXY_ENV = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
)
# Local gost: HTTP on 9999, forwarding to socks5 on 8888.
_DEFAULT_RELAY = "http://127.0.0.1:9999"


def _local_port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.3):
            return True
    except OSError:
        return False


def _relay_requested() -> bool:
    return os.environ.get("NUZLOCKE_RELAY", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def ensure_relay_routing() -> None:
    """Localhost stays direct. The Cursor tunnel is opt-in.

    On an open network the bridge connects straight to Cursor. Set
    ``NUZLOCKE_RELAY=1`` when a firewall resets that connection: if nothing
    has set a proxy and gost is listening, this points the process at
    ``http://127.0.0.1:9999``.

    The SDK bridge is Node 24. Its ``fetch`` ignores ``HTTP_PROXY`` unless
    ``NODE_USE_ENV_PROXY=1``. Its agent calls use ``http2.connect``, which
    ignores that flag, so a preload tunnels those sessions through the same
    HTTP proxy. Loopback stays in ``NO_PROXY`` so the emulator and the bridge
    itself are not sent through gost.
    """
    if (
        _relay_requested()
        and not any(os.environ.get(name) for name in _PROXY_ENV)
        and _local_port_open("127.0.0.1", 9999)
    ):
        for name in _PROXY_ENV:
            os.environ[name] = _DEFAULT_RELAY
    if any(os.environ.get(name) for name in _PROXY_ENV) and not os.environ.get(
        "NODE_USE_ENV_PROXY"
    ):
        os.environ["NODE_USE_ENV_PROXY"] = "1"
    _enable_http2_proxy_preload()
    for name in ("NO_PROXY", "no_proxy"):
        current = [part.strip() for part in os.environ.get(name, "").split(",") if part.strip()]
        for host in _LOOPBACK_NO_PROXY:
            if host not in current:
                current.append(host)
        os.environ[name] = ",".join(current)


def _enable_http2_proxy_preload() -> None:
    """Point the bridge's Node at the HTTP/2 CONNECT preload when a proxy is set."""
    if not any(os.environ.get(name) for name in _PROXY_ENV):
        return
    preload = ROOT / "nuzlocke" / "llm" / "cursor_http2_proxy.cjs"
    if not preload.is_file():
        return
    flag = f"--require {preload}"
    current = os.environ.get("NODE_OPTIONS", "")
    if str(preload) in current:
        return
    os.environ["NODE_OPTIONS"] = f"{current} {flag}".strip()


def load_agents_config(path: Path | None = None) -> dict[str, Any]:
    return load_yaml(path or ROOT / "config" / "agents.yaml")


def load_run_config(path: Path | None = None) -> dict[str, Any]:
    cfg = load_yaml(path or ROOT / "config" / "run.yaml")
    rom = os.environ.get("NUZLOCKE_ROM") or cfg.get("rom_path")
    if rom:
        cfg["rom_path"] = str(Path(rom).expanduser().resolve())
    # Minimum wall-clock seconds between agent prompt cycles.
    # Actions from each prompt still execute immediately (real-time).
    raw_prompt = os.environ.get("NUZLOCKE_PROMPT_INTERVAL_S")
    if raw_prompt is None or str(raw_prompt).strip() == "":
        # Back-compat with the short-lived per-action pacing env name.
        raw_prompt = os.environ.get("NUZLOCKE_ACTION_INTERVAL_S")
    if raw_prompt is not None and str(raw_prompt).strip() != "":
        cfg["prompt_interval_s"] = float(raw_prompt)
    else:
        cfg.setdefault("prompt_interval_s", 2.0)

    raw_vision = os.environ.get("NUZLOCKE_VISION_ONLY")
    if raw_vision is not None and str(raw_vision).strip() != "":
        cfg["vision_only"] = str(raw_vision).strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
    else:
        cfg.setdefault("vision_only", True)

    mem = cfg.get("memory") or {}
    if not isinstance(mem, dict):
        mem = {}
    raw_mem = os.environ.get("NUZLOCKE_MEMORY")
    if raw_mem is not None and str(raw_mem).strip() != "":
        mem["enabled"] = str(raw_mem).strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
    else:
        mem.setdefault("enabled", False)
    cfg["memory"] = mem
    return cfg


def load_rules(path: Path | None = None) -> dict[str, Any]:
    return load_yaml(path or ROOT / "config" / "rules_red.yaml")
