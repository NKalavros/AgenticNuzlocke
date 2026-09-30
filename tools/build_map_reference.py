"""Build the early-game atlas from a local pret/pokered checkout (no ROM required).

Usage: uv run python tools/build_map_reference.py /path/to/pokered
Source: https://github.com/pret/pokered — headers, objects, blocks and collision lists.
The output is advisory vanilla geometry; live Red Star observations take precedence.
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(sys.argv[1])
OUTPUT = Path(__file__).resolve().parents[1] / "nuzlocke/knowledge/maps_red.json"
SUPPORTED = {
    0,
    1,
    2,
    3,
    12,
    13,
    14,
    15,
    33,
    35,
    36,
    37,
    38,
    39,
    40,
    41,
    42,
    47,
    49,
    50,
    51,
    54,
    56,
    58,
    59,
    60,
    61,
    62,
    63,
    64,
    65,
}


def read(path):
    return (ROOT / path).read_text()


constants = {
    name: {"id": i, "w": int(w) * 2, "h": int(h) * 2}
    for i, (name, w, h) in enumerate(
        re.findall(
            r"^\s*map_const\s+(\w+),\s*(\d+),\s*(\d+)",
            read("constants/map_constants.asm"),
            re.MULTILINE,
        )
    )
}
tileset_names = re.findall(
    r"^\s*const (\w+)", read("constants/tileset_constants.asm"), re.MULTILINE
)
tileset_rows = re.findall(
    r"^\s*tileset (\w+),.*", read("data/tilesets/tileset_headers.asm"), re.MULTILINE
)
tilesets = dict(zip(tileset_names, tileset_rows, strict=True))
collision, pending = {}, []
for line in read("data/tilesets/collision_tile_ids.asm").splitlines():
    match = re.match(r"(\w+)_Coll::", line)
    if match:
        pending.append(match[1])
    elif line.strip().startswith("coll_tiles"):
        values = {int(x, 16) for x in re.findall(r"\$([0-9a-fA-F]+)", line)}
        for name in pending:
            collision[name] = values
        pending = []
blocksets, pending = {}, []
for line in read("gfx/tilesets.asm").splitlines():
    match = re.match(r"(\w+)_Block::", line)
    if match:
        pending.append(match[1])
    inc = re.search(r'INCBIN "(gfx/blocksets/[^\"]+)"', line)
    if inc:
        for name in pending:
            blocksets[name] = (ROOT / inc[1]).read_bytes()
        pending = []

maps = {}
for file in sorted((ROOT / "data/maps/headers").glob("*.asm")):
    header = file.read_text()
    match = re.search(r"map_header (\w+), (\w+), (\w+)", header)
    if not match:
        continue
    name, symbol, tileset = match.groups()
    dims = constants[symbol]
    if dims["id"] not in SUPPORTED:
        continue
    width, height = dims["w"], dims["h"]
    blocks = (ROOT / f"maps/{name}.blk").read_bytes()
    assert len(blocks) == width * height // 4, name
    bst, allowed = blocksets[tilesets[tileset]], collision[tilesets[tileset]]
    tile_ids = [
        [
            bst[blocks[(y // 2) * (width // 2) + x // 2] * 16 + (y % 2 * 2 + 1) * 4 + x % 2 * 2]
            for x in range(width)
        ]
        for y in range(height)
    ]
    rows = ["".join("." if t in allowed else "#" for t in row) for row in tile_ids]
    grass_id = re.search(
        r"tileset " + tilesets[tileset] + r",\s*[^,]+,\s*[^,]+,\s*[^,]+,\s*\$([0-9A-Fa-f]+)",
        read("data/tilesets/tileset_headers.asm"),
    )
    grass = [
        [x, y]
        for y in range(height)
        for x in range(width)
        if grass_id and tile_ids[y][x] == int(grass_id[1], 16)
    ]
    ledge_rules = re.findall(
        r"SPRITE_FACING_(\w+),\s*\$([0-9A-Fa-f]+),\s*\$([0-9A-Fa-f]+)",
        read("data/tilesets/ledge_tiles.asm"),
    )
    ledges = []
    if tileset == "OVERWORLD":
        for y in range(height):
            for x in range(width):
                for direction, first, second in ledge_rules:
                    d = direction.lower()
                    dx, dy = {"down": (0, 1), "left": (-1, 0), "right": (1, 0)}[d]
                    if (
                        0 <= x + 2 * dx < width
                        and 0 <= y + 2 * dy < height
                        and tile_ids[y][x] == int(first, 16)
                        and tile_ids[y + dy][x + dx] == int(second, 16)
                        and tile_ids[y + 2 * dy][x + 2 * dx] in allowed
                    ):
                        ledges.append([x, y, d, int(first, 16), int(second, 16)])
    objects = read(f"data/maps/objects/{name}.asm")
    warps = [
        {
            "x": int(x),
            "y": int(y),
            "dest_map": constants.get(dest, {"id": 255})["id"],
            "dest_warp": int(warp) - 1,
        }
        for x, y, dest, warp in re.findall(
            r"warp_event\s+(\d+),\s*(\d+),\s*(\w+),\s*(\d+)", objects
        )
    ]
    connections = []
    for side, dest_name, dest, offset in re.findall(
        r"connection (\w+), (\w+), (\w+), (-?\d+)", header
    ):
        connections.append(
            {
                "dir": {"north": "up", "south": "down", "west": "left", "east": "right"}[side],
                "dest_map": constants[dest]["id"],
                "offset": int(offset) * 2,
            }
        )
    pairs = re.findall(
        r"db " + tileset + r", \$([0-9A-Fa-f]+), \$([0-9A-Fa-f]+)",
        read("data/tilesets/pair_collision_tile_ids.asm").split("TilePairCollisionsWater")[0],
    )
    pairs = {frozenset((int(a, 16), int(b, 16))) for a, b in pairs}
    blocked = []
    for y in range(height):
        for x in range(width):
            for side, dx, dy in (("up", 0, -1), ("down", 0, 1), ("left", -1, 0), ("right", 1, 0)):
                if (
                    0 <= x + dx < width
                    and 0 <= y + dy < height
                    and frozenset((tile_ids[y][x], tile_ids[y + dy][x + dx])) in pairs
                ):
                    blocked.append([x, y, side])
    maps[str(dims["id"])] = {
        "name": name,
        "size": {"w": width, "h": height},
        "rows": rows,
        "warps": warps,
        "connections": connections,
        "blocked_edges": blocked,
        "grass": grass,
        "ledges": ledges,
    }

# Match open boundary tiles on BOTH maps, accounting for their header alignment.
for data in maps.values():
    w, h = data["size"]["w"], data["size"]["h"]
    for connection in data["connections"]:
        dest = maps.get(str(connection["dest_map"]))
        if not dest:
            connection["tiles"] = []
            continue
        dw, dh = dest["size"]["w"], dest["size"]["h"]
        side, offset = connection["dir"], connection["offset"]
        tiles = []
        for i in range(w if side in {"up", "down"} else h):
            j = i - offset
            x, y, tx, ty = {
                "up": (i, 0, j, dh - 1),
                "down": (i, h - 1, j, 0),
                "left": (0, i, dw - 1, j),
                "right": (w - 1, i, 0, j),
            }[side]
            if (
                0 <= tx < dw
                and 0 <= ty < dh
                and data["rows"][y][x] == "."
                and dest["rows"][ty][tx] == "."
            ):
                tiles.append([x, y])
        connection["tiles"] = tiles

OUTPUT.write_text(
    json.dumps({"source": "https://github.com/pret/pokered", "maps": maps}, indent=2) + "\n"
)
print(f"Wrote {len(maps)} reference maps to {OUTPUT}")
