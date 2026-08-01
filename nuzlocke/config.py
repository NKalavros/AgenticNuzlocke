"""Config loading helpers."""

from __future__ import annotations

import os
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
        mem.setdefault("enabled", True)
    cfg["memory"] = mem
    return cfg


def load_rules(path: Path | None = None) -> dict[str, Any]:
    return load_yaml(path or ROOT / "config" / "rules_red.yaml")
