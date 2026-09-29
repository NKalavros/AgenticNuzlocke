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


def test_a_map_change_waits_for_the_new_map_to_load(tmp_path):
    from unittest.mock import MagicMock

    from nuzlocke.environment.nous_red import NousRedEnvironment

    env = NousRedEnvironment(base_url="http://127.0.0.1:1", run_dir=tmp_path, auto_start=False)
    reads = iter(
        [
            {"map": {"map_id": 0}, "player": {"position": {"x": 5, "y": 6}}},
            # Just through the door: the map id is new, x/y are still Pallet's.
            {"map": {"map_id": 37}, "player": {"position": {"x": 5, "y": 5}}},
            {"map": {"map_id": 37}, "player": {"position": {"x": 2, "y": 7}}},
        ]
    )
    posted: list = []
    env._get = lambda path, **kw: MagicMock(json=lambda: next(reads) if path == "/state" else {})
    env._post_json = lambda path, payload: posted.append(payload)
    env.screenshot = lambda path: None
    env._collision_ascii = lambda: None
    env._map_objects = lambda: None
    first = env.observe()
    assert (first.x, first.y) == (5, 6)
    second = env.observe()
    assert (second.map_id, second.x, second.y) == (37, 2, 7)
    assert posted == [{"actions": ["wait_60"]}]


def test_cutscene_flags_as_read_through_oaks_escort():
    from nuzlocke.environment.nous_red import _cutscene

    assert not _cutscene({"status5": 0, "joy_ignore": 0})
    assert _cutscene({"status5": 0, "joy_ignore": 0xFC})  # Oak talking: only A/B work
    assert _cutscene({"status5": 0x80, "joy_ignore": 0xFC})  # Oak walking you to the lab
    assert not _cutscene(None)
