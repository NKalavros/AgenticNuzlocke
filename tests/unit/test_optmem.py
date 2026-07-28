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


def test_optmem_disabled(tmp_path: Path) -> None:
    mem = OptMem(tmp_path / "memory", enabled=False)
    assert mem.wake() == ""
    assert mem.note("should not write") == ""
