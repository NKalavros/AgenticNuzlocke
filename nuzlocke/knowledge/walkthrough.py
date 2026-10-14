"""Load stage-aware progression guidance and excerpts for stuck recovery."""

from __future__ import annotations

import json
import re
from pathlib import Path

from nuzlocke.config import project_root


def skill_dir() -> Path:
    return project_root() / ".cursor" / "skills" / "pokemon-red-walkthrough"


def _manifest(root=None):
    return json.loads(((root or skill_dir()) / "manifest.json").read_text(encoding="utf-8"))


def compose(*sections: str, root: Path | None = None, max_chars: int | None = None) -> str:
    """Expand named bundles in order, reject cycles, and read each fragment once."""
    if max_chars is not None and max_chars < 0:
        raise ValueError("max_chars must be nonnegative")
    root = (root or skill_dir()).resolve()
    manifest, seen, chunks = _manifest(root), set(), []

    def add(name, stack=()):
        if name in stack:
            raise ValueError(f"Walkthrough include cycle: {' -> '.join((*stack, name))}")
        if name in seen:
            return
        if name in manifest["bundles"]:
            for child in manifest["bundles"][name]:
                add(child, (*stack, name))
        else:
            path = (root / manifest["fragments"][name]).resolve()
            if not path.is_relative_to(root):
                raise ValueError(f"Walkthrough fragment escapes its root: {name}")
            chunks.append(path.read_text(encoding="utf-8").strip())
        seen.add(name)

    for section in sections:
        add(section)
    text = "\n\n".join(chunks)
    if max_chars is not None and len(text) > max_chars:
        suffix = "\n…(truncated)"
        text = text[: max(0, max_chars - len(suffix))].rstrip() + suffix[:max_chars]
    return text


def load_full_walkthrough() -> str:
    return compose("all")


def holds(obs, item_id, name):
    return any(
        item.get("quantity", 0) > 0
        and (item.get("id") == item_id or re.sub(r"[^A-Z0-9]", "", str(item.get("item", "")).upper().replace("É", "E")) == name)
        for item in obs.bag
    )


def story_battle(obs):
    """Match required battles using public observed identity, location and prerequisites."""
    from nuzlocke.assets import data

    battle = obs.battle or {}
    enemy = battle.get("enemy") or {}
    return next(
        (
            entry
            for entry in data("walkthrough/story_battles.json")
            if obs.in_battle
            and obs.map_id == entry["map"]
            and [obs.x, obs.y] in entry["positions"]
            and battle.get("type") == entry["type"]
            and enemy.get("species") == entry["species"]
            and enemy.get("level") == entry["level"]
            and holds(obs, entry["required_item"], entry["required_name"])
        ),
        None,
    )


def living_move(obs, move_id, name):
    return any(
        move.get("id") == move_id or str(move.get("name", "")).upper() == name
        for mon in obs.party
        if not mon.get("dead") and mon.get("hp", 0) > 0
        for move in mon.get("moves", [])
    )


def koga_stage(obs) -> str | None:
    """Inventory proves story prerequisites; reaching Fuchsia proves access already exists."""
    if obs is None or "Rainbow" not in obs.badges or "Soul" in obs.badges:
        return None
    if obs.map_id == 157:
        return "gym"
    if obs.map_id in {7, 152, 153, 154, 155, 156, 158, 164}:
        return "fuchsia"
    if obs.map_id in {24, 25, 26, 28, 29, 184, 185} or holds(obs, 73, "POKEFLUTE"):
        return "fuchsia_route"
    if holds(obs, 72, "SILPHSCOPE"):
        return "tower"
    if holds(obs, 74, "LIFTKEY"):
        return "rocket_scope"
    return "rocket_key" if obs.map_id in range(199, 204) else "rocket_entry"


def surf_stage(obs) -> str | None:
    """Never infer the HM or a usable field move from location or planner prose."""
    if obs is None:
        return None
    if living_move(obs, 57, "SURF"):
        return "field" if "Soul" in obs.badges else "locked"
    return "teach" if holds(obs, 198, "HM03") else None


def surge_stage(obs) -> str | None:
    """Shared observed prerequisite for planner guidance and displayed objectives."""
    if obs is None or "Cascade" not in obs.badges or "Thunder" in obs.badges:
        return None

    def normalized(value):
        return re.sub(r"[^A-Z0-9]", "", str(value).upper())

    held = [item for item in obs.bag if item.get("quantity", 0) > 0]
    ticket = any(item.get("id") == 63 or normalized(item.get("item")) == "SSTICKET" for item in held)
    hm = any(item.get("id") == 196 or normalized(item.get("item")) == "HM01" for item in held)
    cut = any(
        normalized(move.get("name")) == "CUT"
        for mon in obs.party
        if not mon.get("dead") and mon.get("hp", 0) > 0
        for move in mon.get("moves", [])
    )
    if cut:
        return "gym" if obs.map_id == 92 else "gym_access"
    return "teach_cut" if hm else "captain" if ticket else "bill"


def progression_hint(obs) -> str:
    """Compose only the current stage; observed prerequisites still control selection."""
    if obs is None or obs.in_battle:
        return ""
    sections = []
    if stage := surf_stage(obs):
        sections.append(compose("surf." + stage))
    for chapter, badge, stage in (("koga", "Rainbow", koga_stage(obs)), ("erika", "Thunder", erika_stage(obs))):
        if stage:
            sections.append(f"Post-{badge} progression — next stage: {stage}.\n\n{compose(chapter + '.' + stage)}")
            return "\n\n".join(sections)
    if stage := surge_stage(obs):
        if obs.map_id == 92 and (obs.surge_puzzle or {}).get("phase") == "open":
            sections.append(
                "Surge's two locks are already open (verified ROM RAM). Stop searching cans. "
                "Verify the visible barrier opens and cross the passage. Heal before challenging Lt. Surge; "
                "only the observed Thunder Badge completes the gym."
            )
        else:
            key = "surge." + stage
            sections.append(
                f"Post-Cascade progression — next unmet prerequisite: {_manifest()['stage_hints'][key]}\n\n{compose(key)}"
            )
    return "\n\n".join(sections)


def erika_stage(obs) -> str | None:
    """Location-based travel stage; only the observed Rainbow Badge completes it."""
    if obs is None or "Thunder" not in obs.badges or "Rainbow" in obs.badges:
        return None
    if obs.map_id == 134:
        return "gym"
    if obs.map_id == 6 or obs.map_id in range(122, 141):
        return "celadon"
    if obs.map_id in {4, 18, 19, 77, 78, 80, 121, 141}:
        return "underground_west"
    if obs.map_id == 21 and (obs.y or 0) >= 36:
        return "lavender"
    if obs.map_id in {82, 232}:
        return "rock_tunnel"
    if obs.map_id in {3, 20, 21, 64, 81}:
        return "route9"
    return "return_cerulean"


def excerpt_for_context(*, map_name=None, reason=None, memory=None, obs=None, max_chars=1800) -> str:
    """Select reusable sections for the current location and recovery reason."""
    if obs is not None and ("Rainbow" in obs.badges or surf_stage(obs)):
        text = progression_hint(obs) + "\n\n" + compose("stuck")
        return text[:max_chars]
    hay = " ".join(value for value in (map_name, reason, memory) if value).lower()
    selected = [name for rule in _manifest()["matches"] if any(key in hay for key in rule["keywords"]) for name in rule["include"]]
    return compose(*selected, "stuck", max_chars=max_chars)
