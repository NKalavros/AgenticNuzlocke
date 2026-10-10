"""Map names by map id, correcting pokemon-agent where its table is shifted.

pokemon-agent's MAP_NAMES leaves out pokered's VIRIDIAN_FOREST_SOUTH_GATE (0x32), so from 50 on
every name is one off, and more further along: it calls the gate "Viridian Forest", the forest
"Pewter Museum 1F", and Pewter Gym (0x36) "Pewter House". Run 20260929-030330-de1d51 confirms
the pokered ids: 50 is a 10x8 gate between Route 2 and 51, and 51 is the 34x48 forest with a
gate at each end. The names below follow pokered's map_constants for 0x2E-0x49.
"""

from __future__ import annotations

from pokemon_agent.memory.red import MAP_NAMES

from nuzlocke.assets import data

POKERED_NAMES = {int(key): value for key, value in data("maps-pokered_names.json").items()}
LAST_MAP = 255


def map_id_for_name(name: str) -> int | None:
    """Corrected names take precedence over shifted upstream aliases."""
    wanted = name.casefold()
    return next(
        (
            mid
            for table in (POKERED_NAMES, MAP_NAMES)
            for mid, label in table.items()
            if mid != LAST_MAP and label.casefold() == wanted
        ),
        None,
    )


def map_name(map_id: int | None, fallback: str | None = None) -> str | None:
    """The map's name; 255 is "back outside" (the map the player came from)."""
    if map_id is None:
        return fallback
    if map_id == LAST_MAP:
        return "back outside"
    return POKERED_NAMES.get(map_id) or MAP_NAMES.get(map_id) or fallback or f"map {map_id}"
