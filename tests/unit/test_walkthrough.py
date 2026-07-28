"""Walkthrough excerpt selection tests."""

from __future__ import annotations

from nuzlocke.knowledge.walkthrough import excerpt_for_context, load_full_walkthrough, skill_dir


def test_walkthrough_files_exist() -> None:
    assert (skill_dir() / "SKILL.md").is_file()
    assert (skill_dir() / "reference.md").is_file()
    assert "Pallet" in load_full_walkthrough()


def test_excerpt_picks_house_and_stuck() -> None:
    text = excerpt_for_context(map_name="Red's House 2F", reason="noop stairs")
    assert "2F" in text or "stairs" in text.lower()
    assert "Stuck" in text or "stuck" in text.lower()


def test_excerpt_lab() -> None:
    text = excerpt_for_context(reason="need starter in oak lab")
    assert "Lab" in text or "starter" in text.lower()
