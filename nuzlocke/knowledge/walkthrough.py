"""Load Pokemon Red walkthrough excerpts for stuck recovery."""

from __future__ import annotations

import re
from pathlib import Path

from nuzlocke.config import project_root

_SECTION_RE = re.compile(r"^## (.+)$", re.M)


def skill_dir() -> Path:
    return project_root() / ".cursor" / "skills" / "pokemon-red-walkthrough"


def walkthrough_paths() -> list[Path]:
    d = skill_dir()
    return [d / "reference.md", d / "SKILL.md"]


def load_full_walkthrough() -> str:
    path = skill_dir() / "reference.md"
    if path.is_file():
        return path.read_text(encoding="utf-8")
    return ""


def _split_sections(full: str) -> list[tuple[str, str]]:
    matches = list(_SECTION_RE.finditer(full))
    out: list[tuple[str, str]] = []
    for i, match in enumerate(matches):
        title = match.group(1).strip()
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(full)
        out.append((title, full[start:end].strip()))
    return out


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

    hay = " ".join(x for x in (map_name or "", reason or "", memory or "") if x).lower()
    sections = _split_sections(full)

    # (keywords, title substring to prefer)
    rules: list[tuple[tuple[str, ...], str]] = [
        (("name", "keyboard", "letter", "rival name", "your name", "title", "new game"), "title"),
        (("2f", "bedroom", "stairs"), "2f"),
        (("1f", "mom", "living"), "1f"),
        (("lab", "starter", "poké ball", "poke ball", "ball table"), "lab"),
        (("pallet",), "pallet"),
        (("parcel", "pokedex", "pokédex", "mart"), "after starter"),
        (("route 1", "viridian forest", "forest"), "route 1"),
        (("pewter", "brock", "gym"), "pewter"),
        (("stuck", "noop", "oscillat", "bounce", "loop"), "stuck"),
    ]

    picked: list[tuple[str, str]] = []
    seen: set[str] = set()

    def add_matching(substr: str) -> None:
        for title, body in sections:
            if substr in title.lower() and title not in seen:
                seen.add(title)
                picked.append((title, body))

    for keys, substr in rules:
        if any(k in hay for k in keys):
            add_matching(substr)

    # Fall back to the generic stuck cheatsheet only — the early-game
    # sections (2F/1F/Pallet) are location-specific and actively misleading
    # once a run is past the early game and nothing else matched.
    if not any("stuck" in t.lower() for t, _ in picked):
        add_matching("stuck")

    chunks = [f"## {title}\n{body}" for title, body in picked]
    text = "\n\n".join(chunks).strip()
    if len(text) > max_chars:
        text = text[: max_chars - 20].rstrip() + "\n…(truncated)"
    return text
