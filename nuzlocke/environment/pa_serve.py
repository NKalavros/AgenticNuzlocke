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
W_CUR_MAP_HEIGHT = 0xD368  # in 2x2-tile blocks
W_CUR_MAP_WIDTH = 0xD369
W_MAP_CONNECTIONS = 0xD370  # bit 3 north, 2 south, 1 west, 0 east
_CONNECTION_BITS = {"up": 0x08, "down": 0x04, "left": 0x02, "right": 0x01}
W_STATUS_FLAGS_5 = 0xD730  # bit 7: a script is moving the player (simulated joypad)
W_JOY_IGNORE = 0xCD6B  # buttons the game is ignoring
W_SIMULATED_JOYPAD_INDEX = 0xCD38  # scripted presses still queued
W_WALK_COUNTER = 0xCFC5  # frames left in the current step's animation
W_IS_IN_BATTLE = 0xD057  # 0 none, 1 wild, 2 trainer, 0xFF lost
# pokered's wEnemyMon: the POKéMON on the field in battle. pokemon-agent's battle.enemy reads
# the enemy party instead, which still held the rival's fainted Squirtle in wild battles.
W_ENEMY_MON = 0xCFE5  # +0 species, +1 HP (2, big-endian)
W_ENEMY_MON_LEVEL = 0xCFF3
W_ENEMY_MON_MAX_HP = 0xCFF4
W_TILE_MAP = 0xC3A0  # the 20x18 background tiles on screen
# pret/pokered symbols branch, verified against screen/party in sandbox fixtures.
W_PLAYER_MON_NUMBER = 0xCC2F
W_BATTLE_MON = 0xD014
W_LAST_MAP = 0xD365
W_OPTIONS = 0xD355
_SCREEN_W, _SCREEN_H = 20, 18
# Font tiles pokemon-agent's GEN1_ENCODING leaves out: box borders, the menu
# cursor, the page arrow, and the é in POKéMON.
_EXTRA_GLYPHS = {
    0x79: "┌",
    0x7A: "─",
    0x7B: "┐",
    0x7C: "│",
    0x7D: "└",
    0x7E: "┘",
    0x7F: " ",
    0xBA: "é",
    0xEC: "▷",
    0xED: "▶",
    0xEE: "▼",
}
_MAX_WARPS = 32
_MAX_SIGNS = 16
_MAX_SPRITES = 15


def _glyphs() -> dict[int, str]:
    from pokemon_agent.memory.red import GEN1_ENCODING

    table = {
        code: char
        for code, char in GEN1_ENCODING.items()
        if code >= 0x80 and len(char) == 1 and char != "\n"
    }
    table.update(_EXTRA_GLYPHS)
    return table


def read_screen_rows(emu: Any, glyphs: dict[int, str] | None = None) -> list[str]:
    """The 18 on-screen tile rows as text. Map and sprite tiles read as spaces.

    This is the characters actually drawn, not a dialog flag. The caller
    trusts it only when the pixel check sees a box.
    """
    table = glyphs if glyphs is not None else _glyphs()
    tiles = emu.read_range(W_TILE_MAP, _SCREEN_W * _SCREEN_H)
    return [
        "".join(table.get(tile, " ") for tile in tiles[row * _SCREEN_W : (row + 1) * _SCREEN_W])
        for row in range(_SCREEN_H)
    ]


def read_enemy(emu: Any) -> dict[str, Any] | None:
    """The enemy on the field, or None outside battle."""
    from pokemon_agent.memory.red import species_name_from_index

    if not emu.read_u8(W_IS_IN_BATTLE):
        return None
    data = emu.read_range(W_ENEMY_MON, 3)
    # Types come from the species (referee.type_chart): pokemon-agent's TYPE_NAMES puts Bug at
    # 6 and Ghost at 7, where pokered has the unused bird type at 6, Bug at 7, Ghost at 8.
    return {
        "species": species_name_from_index(data[0]),
        "hp": (data[1] << 8) | data[2],
        "max_hp": (emu.read_u8(W_ENEMY_MON_MAX_HP) << 8) | emu.read_u8(W_ENEMY_MON_MAX_HP + 1),
        "level": emu.read_u8(W_ENEMY_MON_LEVEL),
    }


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
        "size": {"w": 2 * emu.read_u8(W_CUR_MAP_WIDTH), "h": 2 * emu.read_u8(W_CUR_MAP_HEIGHT)},
        "connections": [
            side for side, bit in _CONNECTION_BITS.items() if emu.read_u8(W_MAP_CONNECTIONS) & bit
        ],
        "input": {
            "status5": emu.read_u8(W_STATUS_FLAGS_5),
            "joy_ignore": emu.read_u8(W_JOY_IGNORE),
            "simulated": emu.read_u8(W_SIMULATED_JOYPAD_INDEX),
            "walking": emu.read_u8(W_WALK_COUNTER),
            "battle": emu.read_u8(W_IS_IN_BATTLE),
        },
        "enemy": read_enemy(emu),
        "active_party_slot": emu.read_u8(W_PLAYER_MON_NUMBER),
        "active_mon": read_active(emu),
        "return_map": emu.read_u8(W_LAST_MAP),
        "battle_result": emu.read_u8(0xCF0B),
        "battle_style": "SET" if emu.read_u8(W_OPTIONS) & 0x40 else "SHIFT",
        "menu_index": emu.read_u8(0xCC26),
        "menu_scroll": emu.read_u8(0xCC36),
        "screen": read_screen_rows(emu),
        "grass_tiles": read_grass(emu),
    }


def read_grass(emu: Any) -> list[dict[str, int]]:
    from pokemon_agent.collision import read_block_tile_ids

    if emu.read_u8(W_IS_IN_BATTLE) or not emu.read_u8(0xD887):
        return []
    grass = emu.read_u8(0xD535)
    x, y = emu.read_u8(W_X_COORD), emu.read_u8(W_Y_COORD)
    return [
        {"x": x + c - 4, "y": y + r - 4}
        for r, row in enumerate(read_block_tile_ids(emu))
        for c, tile in enumerate(row)
        if tile == grass
    ]


def read_active(emu: Any) -> dict[str, Any]:
    from pokemon_agent.memory.red import MOVE_NAMES, species_name_from_index

    if emu.read_u8(W_IS_IN_BATTLE) not in (1, 2):
        return {}
    d = emu.read_range(W_BATTLE_MON, 29)
    return {
        "species": species_name_from_index(d[0]),
        "hp": (d[1] << 8) | d[2],
        "max_hp": (d[15] << 8) | d[16],
        "level": d[14],
        "status": "PSN" if d[4] & 8 else ("OK" if d[4] == 0 else "STATUS"),
        "moves": [
            {"id": d[8 + i], "name": MOVE_NAMES.get(d[8 + i], "UNKNOWN"), "pp": d[25 + i] & 63}
            for i in range(4)
            if d[8 + i]
        ],
    }


def correct_type_decoder() -> None:
    """Repair upstream type IDs for REST, WebSocket, and referee party reads."""
    from pokemon_agent.memory.red import TYPE_NAMES

    TYPE_NAMES.update({6: "Bird", 7: "Bug", 8: "Ghost", 24: "Psychic", 25: "Ice"})


def _mount() -> None:
    import asyncio
    import base64
    import os
    import secrets

    from fastapi import HTTPException
    from fastapi.responses import JSONResponse
    from pokemon_agent import server

    correct_type_decoder()

    lock = asyncio.Lock()
    writer = os.environ.get("NUZLOCKE_WRITER_TOKEN")

    @server.app.middleware("http")
    async def serialized_emulator(request, call_next):
        path = request.url.path
        mutation = request.method == "POST" and (
            path in {"/action", "/load", "/nuzlocke/prepare", "/nuzlocke/navigation", "/games/new"}
            or (path.startswith("/games/") and path.endswith("/load"))
        )
        if (
            writer
            and mutation
            and not secrets.compare_digest(request.headers.get("X-Nuzlocke-Writer", ""), writer)
        ):
            return JSONResponse(
                status_code=409,
                content={"detail": "This emulator is owned by the Nuzlocke controller"},
            )
        if (
            request.url.path
            in {
                "/action",
                "/save",
                "/load",
                "/snapshot",
                "/map/objects",
                "/state",
                "/screenshot",
                "/screenshot/grid",
                "/screenshot/base64",
                "/nuzlocke/prepare",
            }
            or mutation
        ):
            async with lock:
                return await call_next(request)
        return await call_next(request)

    navigation = {"status": "Waiting for the controller"}

    @server.app.post("/nuzlocke/navigation")
    async def publish_navigation(payload: dict):
        nonlocal navigation
        navigation = payload
        return {"ok": True}

    @server.app.get("/nuzlocke/navigation")
    async def read_navigation():
        return navigation

    @server.app.get("/navigation")
    async def navigation_dashboard():
        from pathlib import Path

        from fastapi.responses import HTMLResponse

        return HTMLResponse(Path(__file__).with_name("navigation.html").read_text())

    def snapshot_data():
        from pokemon_agent.collision import build_collision_grid, render_ascii_map

        state = server._get_state_dict()
        state.setdefault("metadata", {})["frame_count"] = server._emulator.frame_count
        return {
            "state": state,
            "objects": read_map_objects(server._reader.emu),
            "screenshot": base64.b64encode(server._get_screenshot_bytes()).decode(),
            "collision": render_ascii_map(build_collision_grid(server._reader.emu), legend=True),
        }

    @server.app.get("/snapshot")
    async def snapshot():
        server._ensure_emulator()
        return await server._run_sync(snapshot_data)

    @server.app.post("/nuzlocke/prepare")
    async def prepare(request: dict):
        server._ensure_emulator()
        try:
            return await server._run_sync(prepare_items, server._reader, request)
        except ValueError as err:
            raise HTTPException(status_code=409, detail=str(err)) from err

    @server.app.get("/map/objects")
    async def map_objects() -> dict[str, Any]:
        server._ensure_emulator()
        try:
            return await server._run_sync(read_map_objects, server._reader.emu)
        except Exception as err:
            raise HTTPException(status_code=500, detail=f"map objects error: {err}") from err


def prepare_items(reader: Any, request: dict) -> dict:
    """Narrow audited exception: SET configuration, or exact candy deficit at a Center."""
    emu = reader.emu
    memory = emu._pyboy.memory
    if emu.read_u8(W_IS_IN_BATTLE):
        raise ValueError("preparation forbidden in battle")
    if request.get("set_style") is True:
        memory[W_OPTIONS] = emu.read_u8(W_OPTIONS) | 0x40
        return {"battle_style": "SET"}
    target = request.get("target")
    if (
        not isinstance(target, int)
        or not 1 <= target <= 14
        or emu.read_u8(W_CUR_MAP) not in {40, 41, 58}
    ):
        raise ValueError("candy grants require a Center and a target at or below 14")
    party = reader.read_party()
    if emu.read_u8(W_CUR_MAP) == 40 and (
        target > 8 or len(party) != 1 or party[0].get("species") != "Bulbasaur"
    ):
        raise ValueError("lab preparation is limited to a lone Bulbasaur through level 8")
    if not party or any(m["hp"] != m["max_hp"] or m["status"] != "OK" for m in party):
        raise ValueError("heal the whole party before preparing")
    need = sum(max(0, target - m["level"]) for m in party)
    count = emu.read_u8(0xD31D)
    if count > 20:
        raise ValueError("unverified bag layout")
    rows = [list(emu.read_range(0xD31E + 2 * i, 2)) for i in range(count)]
    row = next((r for r in rows if r[0] == 0x28), None)
    held = row[1] if row else 0
    grant = max(0, need - held)
    if grant:
        if held + grant > 99 or (row is None and count == 20):
            raise ValueError("bag has no room for audited candies")
        if row is None:
            rows.append([0x28, grant])
        else:
            row[1] += grant
        memory[0xD31D] = len(rows)
        for i, (item, quantity) in enumerate(rows):
            memory[0xD31E + i * 2] = item
            memory[0xD31F + i * 2] = quantity
        memory[0xD31E + 2 * len(rows)] = 0xFF
    return {"item": "Rare Candy", "granted": grant, "held_before": held, "target": target}


def main() -> None:
    _mount()
    from pokemon_agent.cli import main as cli_main

    sys.argv[0] = "pokemon-agent"
    cli_main()


if __name__ == "__main__":
    main()
