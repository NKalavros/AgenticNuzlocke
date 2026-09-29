"""Map names by map id, correcting pokemon-agent where its table is shifted.

pokemon-agent's MAP_NAMES leaves out pokered's VIRIDIAN_FOREST_SOUTH_GATE (0x32), so from 50 on
every name is one off, and more further along: it calls the gate "Viridian Forest", the forest
"Pewter Museum 1F", and Pewter Gym (0x36) "Pewter House". Run 20260929-030330-de1d51 confirms
the pokered ids: 50 is a 10x8 gate between Route 2 and 51, and 51 is the 34x48 forest with a
gate at each end. The names below follow pokered's map_constants for 0x2E-0x49.
"""

from __future__ import annotations

from pokemon_agent.memory.red import MAP_NAMES

POKERED_NAMES = {
    46: "Diglett's Cave (Route 2)",
    47: "Viridian Forest North Gate",
    48: "Route 2 Trade House",
    49: "Route 2 Gate",
    50: "Viridian Forest South Gate",
    51: "Viridian Forest",
    52: "Pewter Museum 1F",
    53: "Pewter Museum 2F",
    54: "Pewter Gym",
    55: "Pewter Nidoran House",
    56: "Pewter Mart",
    57: "Pewter Speech House",
    58: "Pewter Pokecenter",
    59: "Mt Moon 1F",
    60: "Mt Moon B1F",
    61: "Mt Moon B2F",
    62: "Cerulean Trashed House",
    63: "Cerulean Trade House",
    64: "Cerulean Pokecenter",
    65: "Cerulean Gym",
    66: "Bike Shop",
    67: "Cerulean Mart",
    68: "Mt Moon Pokecenter",
    69: "Cerulean Trashed House",
    70: "Route 5 Gate",
    71: "Underground Path (Route 5)",
    72: "Daycare",
    73: "Route 6 Gate",
}
LAST_MAP = 255


def map_name(map_id: int | None, fallback: str | None = None) -> str | None:
    """The map's name; 255 is "back outside" (the map the player came from)."""
    if map_id is None:
        return fallback
    if map_id == LAST_MAP:
        return "back outside"
    return POKERED_NAMES.get(map_id) or MAP_NAMES.get(map_id) or fallback or f"map {map_id}"
