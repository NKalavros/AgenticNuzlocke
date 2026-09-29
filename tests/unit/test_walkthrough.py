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


def test_excerpt_picks_fence_and_parcel_geometry() -> None:
    fence = excerpt_for_context(map_name="Pallet Town", reason="fence post noop")
    assert "post" in fence.lower()
    parcel = excerpt_for_context(map_name="Oak's Lab", reason="aide parcel")
    assert "aide" in parcel.lower() or "oak" in parcel.lower()
    ledge = excerpt_for_context(map_name="Route 1", reason="viridian south ledge")
    assert "gap" in ledge.lower() or "ledge" in ledge.lower()


def test_excerpt_lab() -> None:
    text = excerpt_for_context(reason="need starter in oak lab")
    assert "Lab" in text or "starter" in text.lower()


def test_unmatched_late_game_context_does_not_leak_early_game_sections() -> None:
    # No keyword rule matches a mid/late-game map/reason — must not fall
    # back to Pallet/bedroom-specific hints, only the generic stuck cheatsheet.
    text = excerpt_for_context(map_name="Fuchsia City", reason="cannot find the Safari Zone exit")
    assert "Pallet Town" not in text
    assert "Red's House" not in text
    assert "stuck" in text.lower()
