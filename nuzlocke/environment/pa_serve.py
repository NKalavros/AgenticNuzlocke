"""pokemon-agent's server plus ``GET /map/objects``: warps, signs, and NPC sprites from WRAM.

pokemon-agent reads the collision tilemap but not the map's objects. Doors and
stairs read ``#`` on its walk grid, so the warp table is what says where they
are. Addresses are pokered's (Red/Blue US). Red Star is a Red hack, and
``ObjectTrust`` withholds a map's objects when a walk contradicts them.

Run exactly like ``pokemon-agent``: ``python -m nuzlocke.environment.pa_serve serve --rom …``.
"""

from __future__ import annotations

import sys
from typing import Any

W_Y_COORD = 0xD361
W_X_COORD = 0xD362
W_CUR_MAP = 0xD35E
W_NUMBER_OF_WARPS = 0xD3AE
W_WARP_ENTRIES = 0xD3AF  # y, x, destination warp, destination map
W_NUM_SIGNS = 0xD4B0
W_SIGN_COORDS = 0xD4B1  # y, x
W_NUM_SPRITES = 0xD4E1
W_SPRITE_STATE_DATA_1 = 0xC100  # +0 picture id, +2 image index (0xFF: off screen)
W_SPRITE_STATE_DATA_2 = 0xC200  # +4 map y + 4, +5 map x + 4
_MAX_WARPS = 32
_MAX_SIGNS = 16
_MAX_SPRITES = 15


def read_map_objects(emu: Any) -> dict[str, Any]:
    """The current map's warps, signs, and NPC sprites, in map tile coordinates."""
    warps = []
    for index in range(min(emu.read_u8(W_NUMBER_OF_WARPS), _MAX_WARPS)):
        y, x, dest_warp, dest_map = emu.read_range(W_WARP_ENTRIES + 4 * index, 4)
        warps.append({"x": x, "y": y, "dest_map": dest_map, "dest_warp": dest_warp})
    signs = []
    for index in range(min(emu.read_u8(W_NUM_SIGNS), _MAX_SIGNS)):
        y, x = emu.read_range(W_SIGN_COORDS + 2 * index, 2)
        signs.append({"x": x, "y": y})
    npcs = []
    for slot in range(1, min(emu.read_u8(W_NUM_SPRITES), _MAX_SPRITES) + 1):
        picture = emu.read_u8(W_SPRITE_STATE_DATA_1 + 16 * slot)
        if picture == 0:
            continue
        on_screen = emu.read_u8(W_SPRITE_STATE_DATA_1 + 16 * slot + 2) != 0xFF
        y = emu.read_u8(W_SPRITE_STATE_DATA_2 + 16 * slot + 4) - 4
        x = emu.read_u8(W_SPRITE_STATE_DATA_2 + 16 * slot + 5) - 4
        npcs.append({"slot": slot, "picture": picture, "x": x, "y": y, "on_screen": on_screen})
    return {
        "map_id": emu.read_u8(W_CUR_MAP),
        "player": {"x": emu.read_u8(W_X_COORD), "y": emu.read_u8(W_Y_COORD)},
        "warps": warps,
        "signs": signs,
        "npcs": npcs,
    }


def _mount() -> None:
    from fastapi import HTTPException
    from pokemon_agent import server

    @server.app.get("/map/objects")
    async def map_objects() -> dict[str, Any]:
        server._ensure_emulator()
        try:
            return await server._run_sync(read_map_objects, server._reader.emu)
        except Exception as err:
            raise HTTPException(status_code=500, detail=f"map objects error: {err}") from err


def main() -> None:
    _mount()
    from pokemon_agent.cli import main as cli_main

    sys.argv[0] = "pokemon-agent"
    cli_main()


if __name__ == "__main__":
    main()
