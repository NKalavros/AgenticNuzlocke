"""ROM collision lists must replace vanilla tables without leaking across ROMs."""

from types import SimpleNamespace

import pytest

from nuzlocke.environment.pa_serve import build_collision_grid


@pytest.mark.parametrize("pointer,data,open_", [(0x17FD, b"\x01\x13\xff", True), (0x17FD, b"\x13\xff", False), (0, b"", False)])
def test_custom_tileset_reads_the_active_fixed_rom_collision_list(monkeypatch, pointer, data, open_):
    from pokemon_agent import collision

    monkeypatch.setattr(collision, "read_block_tile_ids", lambda emu: [[1] * 10 for _ in range(9)])
    emu = SimpleNamespace(read_u8=lambda addr: 24, read_u16=lambda addr: pointer, read_range=lambda addr, size: data)
    grid = build_collision_grid(emu)
    assert grid["tileset"] == 24 and grid["player_cell"] == "E5"
    assert grid["walkable"][0][0] is open_
    assert grid["walkable"][4][4] is True
    assert 24 not in collision.TILESET_WALKABLE


def test_invalid_collision_pointer_uses_existing_vanilla_fallback(monkeypatch):
    from pokemon_agent import collision

    monkeypatch.setattr(collision, "read_block_tile_ids", lambda emu: [[0x1E] * 10 for _ in range(9)])
    emu = SimpleNamespace(read_u8=lambda addr: 3, read_u16=lambda addr: 0xD000)
    assert build_collision_grid(emu)["walkable"][0][0] is True
