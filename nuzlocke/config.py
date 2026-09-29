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
    try:
        text = (path or ROOT / ".env").read_text(encoding="utf-8")
    except OSError:
        return
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("#"):
            continue
        key, sep, value = line.removeprefix("export ").partition("=")
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        if sep and key and key not in os.environ:
            os.environ[key] = value


def _env_flag(name: str, default: Any) -> Any:
    """``name`` read as a yes/no flag, or ``default`` when it is unset or blank."""
    raw = os.environ.get(name, "").strip()
    return raw.lower() in {"1", "true", "yes", "on"} if raw else default


# Hosts that must not be sent through gost. The emulator and the Cursor SDK
# bridge both listen on loopback; the proxy answers those with an empty 503.
_LOOPBACK_NO_PROXY = ("127.0.0.1", "localhost", "::1")
_PROXY_ENV = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")
# Local gost: HTTP on 9999, forwarding to socks5 on 8888.
_DEFAULT_RELAY = "http://127.0.0.1:9999"
_HTTP2_PRELOAD = ROOT / "nuzlocke" / "llm" / "cursor_http2_proxy.cjs"


def _local_port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.3):
            return True
    except OSError:
        return False


def ensure_relay_routing() -> None:
    """Localhost stays direct. The Cursor tunnel is opt-in.

    On an open network the bridge connects straight to Cursor. Set
    ``NUZLOCKE_RELAY=1`` when a firewall resets that connection: if nothing
    has set a proxy and gost is listening, this points the process at
    ``http://127.0.0.1:9999``.

    The SDK bridge is Node 24. Its ``fetch`` ignores ``HTTP_PROXY`` unless
    ``NODE_USE_ENV_PROXY=1``. Its agent calls use ``http2.connect``, which
    ignores that flag, so a preload tunnels those sessions through the same
    HTTP proxy.
    """
    if (
        _env_flag("NUZLOCKE_RELAY", False)
        and not any(os.environ.get(name) for name in _PROXY_ENV)
        and _local_port_open("127.0.0.1", 9999)
    ):
        for name in _PROXY_ENV:
            os.environ[name] = _DEFAULT_RELAY
    if any(os.environ.get(name) for name in _PROXY_ENV):
        os.environ["NODE_USE_ENV_PROXY"] = os.environ.get("NODE_USE_ENV_PROXY") or "1"
        node_options = os.environ.get("NODE_OPTIONS", "")
        if _HTTP2_PRELOAD.is_file() and str(_HTTP2_PRELOAD) not in node_options:
            os.environ["NODE_OPTIONS"] = f"{node_options} --require {_HTTP2_PRELOAD}".strip()
    for name in ("NO_PROXY", "no_proxy"):
        hosts = [part.strip() for part in os.environ.get(name, "").split(",") if part.strip()]
        hosts += [host for host in _LOOPBACK_NO_PROXY if host not in hosts]
        os.environ[name] = ",".join(hosts)


def load_agents_config(path: Path | None = None) -> dict[str, Any]:
    return load_yaml(path or ROOT / "config" / "agents.yaml")


def load_run_config(path: Path | None = None) -> dict[str, Any]:
    cfg = load_yaml(path or ROOT / "config" / "run.yaml")
    rom = os.environ.get("NUZLOCKE_ROM") or cfg.get("rom_path")
    if rom:
        cfg["rom_path"] = str(Path(rom).expanduser().resolve())
    # NUZLOCKE_ACTION_INTERVAL_S is an older name for the same setting.
    raw_interval = (
        os.environ.get("NUZLOCKE_PROMPT_INTERVAL_S", "").strip()
        or os.environ.get("NUZLOCKE_ACTION_INTERVAL_S", "").strip()
    )
    if raw_interval:
        cfg["prompt_interval_s"] = float(raw_interval)
    else:
        cfg.setdefault("prompt_interval_s", 2.0)
    cfg["vision_only"] = _env_flag("NUZLOCKE_VISION_ONLY", cfg.get("vision_only", True))
    mem = cfg.get("memory")
    if not isinstance(mem, dict):
        mem = {}
    mem["enabled"] = _env_flag("NUZLOCKE_MEMORY", mem.get("enabled", False))
    cfg["memory"] = mem
    return cfg


def load_rules(path: Path | None = None) -> dict[str, Any]:
    return load_yaml(path or ROOT / "config" / "rules_red.yaml")
