"""Opt-in puzzle assistance: read switch indices, never change game memory.

pret/pokered: engine/events/hidden_events/vermilion_gym_trash.asm and
data/events/hidden_events.asm. Addresses and coordinates are verified on Red Star.
The second index is selected only after opening the first lock; it need not be
adjacent (the original game's random-index calculation has an underflow bug).
"""

import hashlib
from functools import cache
from pathlib import Path

RED_STAR_SHA256 = "8428b4944f7b93dd25cd6d9a8811bef2211125aa61efca607bfd56ced676e1ea"


@cache
def supported_rom(path: str) -> bool:
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest() == RED_STAR_SHA256
    except OSError:
        return False


def read_surge_puzzle(emu) -> dict | None:
    """Map-scoped, frozen RAM evidence; unknown ROMs/layouts get no assistance."""
    mid = emu.read_u8(0xD35E)
    if mid not in {5, 89, 92} or not supported_rom(str(getattr(emu, "rom_path", ""))):
        return None
    if mid == 92 and (emu.read_u8(0xD369), emu.read_u8(0xD368)) != (5, 9):
        return None
    flags = emu.read_u8(0xD773)  # EVENT_2ND_LOCK_OPENED = $160, first = $161
    if flags & 1:
        return {"phase": "open", "source": "RAM assist"}
    if mid != 92:
        return None  # Carry only completion evidence outside the gym, never hidden can positions.
    second = bool(flags & 2)
    index = emu.read_u8(0xD744 if second else 0xD743)
    if index >= 15:
        return None
    return {
        "phase": "second" if second else "first",
        "index": index,
        "x": 1 + 2 * (index // 3),
        "y": 7 + 2 * (index % 3),
        "source": "RAM assist",
    }
