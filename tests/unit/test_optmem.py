"""OptMem wrapper tests."""

from __future__ import annotations

from pathlib import Path

from nuzlocke.memory.optmem import OptMem


def test_optmem_note_wake_and_nap(tmp_path: Path) -> None:
    mem = OptMem(tmp_path / "memory", wake_lines=32, enabled=True)
    mem.note("Red Star house: dark TV tile is not stairs")
    mem.note("up/down oscillation was false outdoors read; stay indoors strategy")
    wake = mem.wake()
    assert "stairs" in wake.lower() or "outdoors" in wake.lower()
    assert "Compress memories" not in wake


def test_optmem_skips_duplicate_landmarks(tmp_path: Path) -> None:
    mem = OptMem(tmp_path / "memory", wake_lines=8, enabled=True)
    first = mem.note("LANDMARK pokeball_table: center table in Oak's Lab")
    second = mem.note("LANDMARK pokeball_table: center table in Oak's Lab")
    anti = mem.note("ANTI do not repeat: walk_up_2")
    anti_again = mem.note("ANTI do not repeat: walk_up_2")
    other = mem.note("LANDMARK oak: back of lab")
    assert first
    assert second == ""
    assert anti
    assert anti_again == ""
    assert other
    wake = mem.wake()
    assert wake.count("LANDMARK pokeball_table") == 1
    assert wake.count("ANTI do not repeat") == 1


def test_optmem_disabled(tmp_path: Path) -> None:
    mem = OptMem(tmp_path / "memory", enabled=False)
    assert mem.wake() == ""
    assert mem.note("should not write") == ""
