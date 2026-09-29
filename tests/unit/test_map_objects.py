"""WRAM map objects: the route's reader and the adapter's map check."""

from __future__ import annotations

from nuzlocke.environment import pa_serve
from nuzlocke.environment.nous_red import _objects_on_map


class _Emu:
    def __init__(self, memory: dict[int, int]) -> None:
        self.memory = memory

    def read_u8(self, addr: int) -> int:
        return self.memory.get(addr, 0)

    def read_range(self, addr: int, size: int) -> bytes:
        return bytes(self.read_u8(addr + offset) for offset in range(size))


def test_reads_oaks_lab_layout():
    # Oak's Lab on Red Star, as read from run 20260928-205856-f65040's savestate.
    memory = {pa_serve.W_CUR_MAP: 40, pa_serve.W_X_COORD: 5, pa_serve.W_Y_COORD: 3}
    memory[pa_serve.W_NUMBER_OF_WARPS] = 2
    for index, x in enumerate((4, 5)):
        base = pa_serve.W_WARP_ENTRIES + 4 * index
        memory.update({base: 11, base + 1: x, base + 2: 2, base + 3: 255})
    memory[pa_serve.W_NUM_SPRITES] = 2
    memory[pa_serve.W_SPRITE_STATE_DATA_1 + 16] = 74  # a Poke Ball
    memory[pa_serve.W_SPRITE_STATE_DATA_2 + 16 + 4] = 3 + 4
    memory[pa_serve.W_SPRITE_STATE_DATA_2 + 16 + 5] = 6 + 4
    memory[pa_serve.W_SPRITE_STATE_DATA_1 + 32 + 2] = 0xFF  # empty slot 2

    objects = pa_serve.read_map_objects(_Emu(memory))

    assert objects["map_id"] == 40
    assert objects["player"] == {"x": 5, "y": 3}
    assert objects["warps"] == [
        {"x": 4, "y": 11, "dest_map": 255, "dest_warp": 2},
        {"x": 5, "y": 11, "dest_map": 255, "dest_warp": 2},
    ]
    assert objects["npcs"] == [{"slot": 1, "picture": 74, "x": 6, "y": 3, "on_screen": True}]
    assert objects["signs"] == []


def test_objects_from_another_map_are_dropped():
    objects = {"map_id": 0, "warps": [{"x": 5, "y": 5}], "signs": [], "npcs": []}
    assert _objects_on_map(objects, 40) == {}
    assert _objects_on_map(objects, 0)["warps"] == [{"x": 5, "y": 5}]
    assert _objects_on_map(None, 0) == {}
