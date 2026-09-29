"""Code-owned early-game objectives.

The vision planner may describe the screen and name one button. It does not get to replace the
current beat. Completion is a map name and an empty-or-not party, which the model cannot talk its
way out of.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from nuzlocke.state.models import PlayerObservation


@dataclass(frozen=True)
class Beat:
    id: str
    text: str
    hint: str
    # Compass direction to hold while that tile is open. None means search.
    heading: str | None = None
    # What System 1's goal menu marks as the objective (see ``agents.goals``):
    # {"kind": "warp", "dest_map": id} | {"kind": "edge", "dir": d} | {"kind": "npc", "picture": id}
    # | {"kind": "wait"}. Map ids and sprite pictures are pokered's, as read on Red Star.
    target: dict[str, Any] = field(default_factory=dict)


BEDROOM = Beat(
    id="leave_bedroom",
    text="Leave Red's bedroom via the stairs.",
    hint=(
        "The stairs are in the top-right corner of the bedroom: the far-right column, top row. "
        "Walk right to the right wall, then up onto the stairs."
    ),
    heading="right",
    target={"kind": "warp", "dest_map": 37},
)
LIVING = Beat(
    id="exit_house",
    text="Walk south out of Red's house into Pallet Town.",
    hint=(
        "The exit is the door mat in the bottom wall, third and fourth tiles from the left. Walk "
        "down to the bottom row, left onto the mat, then walk_down once more — the mat reads as # "
        "on the grid but that step leaves the house."
    ),
    heading="down",
    target={"kind": "warp", "dest_map": 255},
)
PALLET_TO_OAK = Beat(
    id="pallet_to_oak",
    text=(
        "Go north through the Route 1 grass gap so Oak escorts you to the lab. Do not walk south "
        "into the water."
    ),
    hint=(
        "With no Pokémon, the way forward is north onto Route 1, not into the lab on your own. The "
        "exit is a two-tile gap in the top tree line, north of the open ground between your house "
        "and the rival's house to the east (from your door: about five tiles right, then straight "
        "up). Stepping into the gap makes Oak stop you. Do not walk south into the shore."
    ),
    heading="up",
    target={"kind": "edge", "dir": "up"},
)
LAB_STARTER = Beat(
    id="get_starter",
    text="Face a starter ball from the south and confirm it.",
    hint=(
        "The three Poké Balls sit on the table just right of Oak. Stand on the tile directly below "
        "a ball, walk_up once to face it, then press_a. After its Pokédex page, press_a at YES — "
        "press_b at that YES/NO turns the Pokémon down."
    ),
    target={"kind": "npc", "picture": 74},
)
LEAVE_LAB = Beat(
    id="leave_lab",
    text="Leave Oak's Lab south.",
    hint=(
        "The exit mat is in the middle of the bottom wall. Walk down onto it and walk_down once "
        "more. The rival challenges you on the way out; that battle is expected."
    ),
    heading="down",
    target={"kind": "warp", "dest_map": 255},
)
PALLET_NORTH = Beat(
    id="leave_pallet",
    text="Leave Pallet Town north onto Route 1.",
    hint=(
        "The north exit is a two-tile gap in the top tree line, north of the open ground between "
        "the two houses. Walk to it, then straight up. Do not walk south into the water."
    ),
    heading="up",
    target={"kind": "edge", "dir": "up"},
)
ROUTE_OAK = Beat(
    id="oak_on_route_1",
    text="Let Oak walk you from Route 1 to the lab. Do not walk back south.",
    hint=(
        "Stepping onto Route 1 with no Pokémon starts Oak's escort. Advance his dialogue. Do not "
        "walk south back into the water."
    ),
    heading="up",
    target={"kind": "wait"},
)

# Oak's Parcel: the old man blocks Viridian's north exit until it is delivered (pitfall #24).
TO_VIRIDIAN = Beat(
    id="to_viridian",
    text="Walk north through Route 1 to Viridian City.",
    hint="Route 1 runs straight north to Viridian City. Ledges only drop south.",
    heading="up",
    target={"kind": "edge", "dir": "up"},
)
GET_PARCEL = Beat(
    id="get_parcel",
    text="Enter the Viridian Poké Mart; the clerk has a parcel for Oak.",
    hint=(
        "The Mart is the building with the blue roof. The old man blocks the north road until "
        "Oak's Parcel is delivered, so do not go north yet."
    ),
    target={"kind": "warp", "dest_map": 42},
)
LEAVE_MART = Beat(
    id="leave_mart",
    text="Take the parcel out of the Mart, back toward Pallet Town.",
    hint="The exit mat is at the bottom of the Mart.",
    heading="down",
    target={"kind": "warp", "dest_map": 255},
)
PARCEL_SOUTH = Beat(
    id="parcel_south",
    text="Carry Oak's Parcel south to Pallet Town.",
    hint="Viridian City's south exit leads to Route 1, which leads south to Pallet Town.",
    heading="down",
    target={"kind": "edge", "dir": "down"},
)
PARCEL_LAB = Beat(
    id="parcel_lab",
    text="Enter Oak's Lab with the parcel.",
    hint="Oak's Lab is the large building in the south of Pallet Town.",
    target={"kind": "warp", "dest_map": 40},
)
DELIVER_PARCEL = Beat(
    id="deliver_parcel",
    text="Talk to Prof. Oak to hand over the parcel.",
    hint="Oak stands at the top of the lab. Face him and press A.",
    target={"kind": "npc", "picture": 3},
)
TO_ROUTE_2 = Beat(
    id="to_route_2",
    text="Head north through Viridian City onto Route 2.",
    hint="With the Pokédex the old man steps aside. Viridian's north exit leads to Route 2.",
    heading="up",
    target={"kind": "edge", "dir": "up"},
)

# Route 2 to Brock. Map ids are pokered's (environment.maps): 50 and 47 are the forest's gates.
TO_FOREST = Beat(
    id="to_forest",
    text="Walk north on Route 2 into the Viridian Forest gate.",
    hint="The gate is the building at the north end of Route 2's first stretch.",
    heading="up",
    target={"kind": "warp", "dest_map": 50},
)
INTO_FOREST = Beat(
    id="into_forest",
    text="Walk through the gate into Viridian Forest.",
    hint="The forest door is at the top of the gate.",
    heading="up",
    target={"kind": "warp", "dest_map": 51},
)
THROUGH_FOREST = Beat(
    id="through_forest",
    text="Cross Viridian Forest to its north gate.",
    hint=(
        "The forest is a maze. The exit is at the top-left corner; go up the east side first, "
        "then west along the top."
    ),
    heading="up",
    target={"kind": "warp", "dest_map": 47},
)
OUT_OF_FOREST = Beat(
    id="out_of_forest",
    text="Leave the north gate onto Route 2.",
    hint="The exit is at the top of the gate.",
    heading="up",
    target={"kind": "warp", "dest_map": 255},
)
TO_PEWTER = Beat(
    id="to_pewter",
    text="Walk north on Route 2 into Pewter City.",
    hint="Pewter City is straight north.",
    heading="up",
    target={"kind": "edge", "dir": "up"},
)
TO_GYM = Beat(
    id="to_gym",
    text="Enter Pewter Gym.",
    hint="The gym is the large building in the middle of the city.",
    target={"kind": "warp", "dest_map": 54},
)
FACE_BROCK = Beat(
    id="face_brock",
    text="Walk up to Brock and challenge him.",
    hint="Brock stands at the top of the gym. Face him and press A.",
    heading="up",
    target={"kind": "face", "x": 4, "y": 2, "dir": "up"},
)
# Poké Balls are the one item this Nuzlocke allows; the catch rule needs them.
BUY_BALLS_CITY = Beat(
    id="buy_balls_city",
    text="Enter the Viridian Mart to buy POKé BALLs.",
    hint="The Mart is the building with the blue roof.",
    target={"kind": "warp", "dest_map": 42},
)
BUY_BALLS = Beat(
    id="buy_balls",
    text="Buy POKé BALLs only: talk to the clerk, BUY, POKé BALL, then YES. Nothing else.",
    hint="The clerk stands behind the counter on the left. Face him across it and press A.",
    target={"kind": "face", "x": 2, "y": 5, "dir": "left"},
)
BACK_FOR_BALLS = Beat(
    id="back_for_balls",
    text="Go back to Viridian City for POKé BALLs.",
    hint="Viridian City is south.",
    heading="down",
    target={"kind": "edge", "dir": "down"},
)
_SHOP_ROUTE = {
    0: PALLET_NORTH,
    12: TO_VIRIDIAN,
    1: BUY_BALLS_CITY,
    42: BUY_BALLS,
    50: Beat(
        id="gate_for_balls",
        text="Leave the gate south, back toward Viridian for POKé BALLs.",
        hint="The exit is at the bottom of the gate.",
        target={"kind": "warp", "dest_map": 255},
    ),
    51: Beat(
        id="forest_for_balls",
        text="Leave the forest by the south gate, back toward Viridian for POKé BALLs.",
        hint="The south gate is at the bottom right.",
        target={"kind": "warp", "dest_map": 50},
    ),
}
LEAVE_SHOP = Beat(
    id="leave_shop",
    text="Leave the Mart: back out of the shop list with B, choose QUIT, then walk out.",
    hint="The exit mat is at the bottom of the Mart.",
    heading="down",
    target={"kind": "warp", "dest_map": 255},
)
_BROCK_ROUTE = {
    0: PALLET_NORTH,
    12: TO_VIRIDIAN,
    1: TO_ROUTE_2,
    42: LEAVE_SHOP,
    50: INTO_FOREST,
    51: THROUGH_FOREST,
    47: OUT_OF_FOREST,
    2: TO_GYM,
    54: FACE_BROCK,
}

_TIERS = ("primary", "secondary", "tertiary")


# What the game holds before Oak's naming lists: blank, or the debug names NINTEN and SONY.
_UNNAMED = {"", "NINTEN", "SONY"}


def is_intro_boot(obs: PlayerObservation) -> bool:
    """Title, Oak's speech, and both name lists: nobody is named yet, or we are on Pallet (0, 0)."""
    player = str(obs.raw_player.get("name") or "").strip("?")
    rival = obs.raw_player.get("rival_name")
    return (
        not obs.map_name
        or player in _UNNAMED
        or (rival is not None and str(rival).strip("?") in _UNNAMED)
        or ((obs.map_name, obs.x, obs.y) == ("Pallet Town", 0, 0) and not obs.party)
    )


def script(obs: PlayerObservation) -> list[Beat]:
    """Remaining early-game beats, current first. Empty once the script is done."""
    if is_intro_boot(obs) or obs.in_battle:
        return []
    name = (obs.map_name or "").casefold()
    party = bool(obs.party)
    if "2f" in name:
        return [BEDROOM, LIVING, PALLET_TO_OAK]
    if "1f" in name:
        return [LIVING, PALLET_TO_OAK, LAB_STARTER]
    if not party:
        if "lab" in name:
            return [LAB_STARTER, LEAVE_LAB, PALLET_NORTH]
        if "route 1" in name:
            return [ROUTE_OAK, LAB_STARTER, LEAVE_LAB]
        return [PALLET_TO_OAK, LAB_STARTER, LEAVE_LAB] if "pallet" in name else []
    return _parcel_errand(obs, name)


# The errand's legs in order, keyed by a piece of the map name. A map can appear twice
# (Route 1 both ways); the first match from the start of the leg wins.
_FETCH = [
    ("lab", LEAVE_LAB),
    ("pallet", PALLET_NORTH),
    ("route 1", TO_VIRIDIAN),
    ("viridian city", GET_PARCEL),
]
_DELIVER = [
    ("mart", LEAVE_MART),
    ("viridian city", PARCEL_SOUTH),
    ("route 1", PARCEL_SOUTH),
    ("pallet", PARCEL_LAB),
    ("lab", DELIVER_PARCEL),
]


def _parcel_errand(obs: PlayerObservation, name: str) -> list[Beat]:
    """Starter in hand: fetch Oak's Parcel in Viridian, bring it back, then go north."""
    if obs.flags.get("has_pokedex"):
        if "lab" in name:
            return [LEAVE_LAB]
        balls = any("ball" in str(item.get("item") or "").casefold() for item in obs.bag)
        if not balls and (obs.money or 0) >= 200 and obs.map_id in (*_SHOP_ROUTE, 13):
            if obs.map_id == 13:
                return [BACK_FOR_BALLS] if (obs.y or 0) >= 12 else [TO_PEWTER]
            return [_SHOP_ROUTE[obs.map_id]]
        if obs.map_id == 13:  # Route 2: the stretch north of the forest leads to Pewter
            return [TO_PEWTER if (obs.y or 0) < 12 else TO_FOREST]
        beat = _BROCK_ROUTE.get(obs.map_id) if obs.map_id is not None else None
        return [beat] if beat else []
    if any("parcel" in str(item.get("item") or "").casefold() for item in obs.bag):
        leg = _DELIVER
    else:
        leg = _FETCH
    start = next((i for i, (key, _beat) in enumerate(leg) if key in name), None)
    if start is None:
        return []
    beats: list[Beat] = []
    for _key, beat in leg[start:]:
        if beat not in beats:
            beats.append(beat)
    return beats


def current_beat(obs: PlayerObservation) -> Beat | None:
    beats = script(obs)
    return beats[0] if beats else None


def objective_window(obs: PlayerObservation) -> dict[str, str] | None:
    """Current beat plus the next two, for the dashboard's three slots."""
    window = {tier: beat.text for tier, beat in zip(_TIERS, script(obs))}
    return window or None
