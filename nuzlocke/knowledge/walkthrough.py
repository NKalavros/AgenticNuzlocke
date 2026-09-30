"""Load Pokemon Red walkthrough excerpts for stuck recovery."""

from __future__ import annotations

import re
from pathlib import Path

from nuzlocke.config import project_root

_SECTION_RE = re.compile(r"^## (.+)$", re.MULTILINE)

# (keywords in the context, section title substring to pull in)
_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("name", "keyboard", "letter", "rival name", "your name", "title", "new game"), "title"),
    (("2f", "bedroom", "stairs"), "2f"),
    (("1f", "mom", "living", "door mat", "doormat"), "1f"),
    (("lab", "starter", "poké ball", "poke ball", "ball table", "aide"), "lab"),
    (("pallet", "fence", "post"), "pallet"),
    (("parcel", "pokedex", "pokédex", "mart", "aide"), "after starter"),
    (("route 1", "viridian forest", "forest", "ledge", "viridian"), "route 1"),
    (("pewter", "brock"), "pewter"),
    (("route 3", "route 4", "moon", "cerulean", "misty", "route 24", "route 25"), "route 3 / mt. moon"),
    (("stuck", "noop", "oscillat", "bounce", "loop"), "stuck"),
)


def skill_dir() -> Path:
    return project_root() / ".cursor" / "skills" / "pokemon-red-walkthrough"


def load_full_walkthrough() -> str:
    path = skill_dir() / "reference.md"
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def _split_sections(full: str) -> list[tuple[str, str]]:
    parts = _SECTION_RE.split(full)[1:]
    return [(title.strip(), body.strip()) for title, body in zip(parts[::2], parts[1::2])]


def excerpt_for_context(
    *,
    map_name: str | None = None,
    reason: str | None = None,
    memory: str | None = None,
    max_chars: int = 1800,
) -> str:
    """Pick the most relevant walkthrough section(s) for the current jam."""
    full = load_full_walkthrough()
    if not full:
        return ""
    hay = " ".join(x for x in (map_name, reason, memory) if x).lower()
    sections = _split_sections(full)
    picked: dict[str, str] = {}

    def add_matching(substr: str) -> None:
        for title, body in sections:
            if substr in title.lower():
                picked.setdefault(title, body)

    for keys, substr in _RULES:
        if any(k in hay for k in keys):
            add_matching(substr)
    # Only the generic stuck cheatsheet as a fallback: the early-game sections are
    # location-specific and actively misleading once a run is past them.
    if not any("stuck" in title.lower() for title in picked):
        add_matching("stuck")

    text = "\n\n".join(f"## {title}\n{body}" for title, body in picked.items()).strip()
    if len(text) > max_chars:
        text = text[: max_chars - 20].rstrip() + "\n…(truncated)"
    return text
