"""Gen-1 restrictions between individually walkable terrain tiles.

Primary source: pret/pokered data/tilesets/pair_collision_tile_ids.asm (land).
These are cliff/room boundaries, not the overworld's two-tile ledge jumps.
"""

LAND_PAIRS = {
    3: {
        (0x30, 0x2E),
        (0x52, 0x2E),
        (0x55, 0x2E),
        (0x56, 0x2E),
        (0x20, 0x2E),
        (0x5E, 0x2E),
        (0x5F, 0x2E),
    },
    17: {(0x20, 0x05), (0x41, 0x05), (0x2A, 0x05), (0x05, 0x21)},
}

# Directed two-tile jumps, from pret/pokered data/tilesets/ledge_tiles.asm.
LEDGE_PAIRS = {
    "down": {(0x2C, 0x37), (0x39, 0x36), (0x39, 0x37)},
    "left": {(0x2C, 0x27), (0x39, 0x27)},
    "right": {(0x2C, 0x0D), (0x2C, 0x1D), (0x39, 0x0D)},
}


def ledge_pair(first, second, direction):
    return first[0] == second[0] == 0 and (first[1], second[1]) in LEDGE_PAIRS.get(direction, set())


def step_delta(step):
    dx, dy = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}[
        step.removeprefix("jump_")
    ]
    scale = 2 if step.startswith("jump_") else 1
    return dx * scale, dy * scale


def pair_blocked(first, second):
    if first[0] != second[0]:
        return False
    pairs = LAND_PAIRS.get(first[0], set())
    return (first[1], second[1]) in pairs or (second[1], first[1]) in pairs


def terrain_tiles(collision, x, y):
    """Convert the native 10×9 tile grid (player E5) into map coordinates."""
    if x is None or y is None or not isinstance(collision, dict):
        return []
    tileset = collision.get("tileset")
    rows = collision.get("tile_ids")
    if not isinstance(tileset, int) or not rows:
        return []
    return [
        {"x": x + col - 4, "y": y + row - 4, "id": tile, "tileset": tileset}
        for row, values in enumerate(rows[:9])
        for col, tile in enumerate(values[:10])
        if isinstance(tile, int)
    ]
