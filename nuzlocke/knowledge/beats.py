"""Code-owned early-game objectives.

The vision planner may describe the screen and name one button. It does not get to replace the
current beat. Completion is a map name and an empty-or-not party, which the model cannot talk its
way out of.
"""

from __future__ import annotations

from dataclasses import dataclass

from nuzlocke.state.models import PlayerObservation


@dataclass(frozen=True)
class Beat:
    id: str
    text: str
    hint: str
    # Compass direction to hold while that tile is open. None means search.
    heading: str | None = None


BEDROOM = Beat(
    id="leave_bedroom",
    text="Leave Red's bedroom via the stairs.",
    hint=(
        "The stairs are in the top-right corner of the bedroom: the far-right column, top row. "
        "Walk right to the right wall, then up onto the stairs."
    ),
    heading="right",
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
)
LAB_STARTER = Beat(
    id="get_starter",
    text="Face a starter ball from the south and confirm it.",
    hint=(
        "The three Poké Balls sit on the table just right of Oak. Stand on the tile directly below "
        "a ball, walk_up once to face it, then press_a. After its Pokédex page, press_a at YES — "
        "press_b at that YES/NO turns the Pokémon down."
    ),
)
LEAVE_LAB = Beat(
    id="leave_lab",
    text="Leave Oak's Lab south.",
    hint=(
        "The exit mat is in the middle of the bottom wall. Walk down onto it and walk_down once "
        "more. The rival challenges you on the way out; that battle is expected."
    ),
    heading="down",
)
PALLET_NORTH = Beat(
    id="leave_pallet",
    text="Leave Pallet Town north onto Route 1.",
    hint=(
        "The north exit is a two-tile gap in the top tree line, north of the open ground between "
        "the two houses. Walk to it, then straight up. Do not walk south into the water."
    ),
    heading="up",
)
ROUTE_OAK = Beat(
    id="oak_on_route_1",
    text="Let Oak walk you from Route 1 to the lab. Do not walk back south.",
    hint=(
        "Stepping onto Route 1 with no Pokémon starts Oak's escort. Advance his dialogue. Do not "
        "walk south back into the water."
    ),
    heading="up",
)

_TIERS = ("primary", "secondary", "tertiary")


def is_intro_boot(obs: PlayerObservation) -> bool:
    """Title and the pre-name house sit on Pallet (0, 0) with an empty party."""
    player_name = obs.raw_player.get("name") or ""
    return (
        not obs.map_name
        or not player_name.strip("?")
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
    if "lab" in name:
        return [LEAVE_LAB, PALLET_NORTH] if party else [LAB_STARTER, LEAVE_LAB, PALLET_NORTH]
    if "route 1" in name:
        return [] if party else [ROUTE_OAK, LAB_STARTER, LEAVE_LAB]
    if "pallet" in name:
        return [PALLET_NORTH] if party else [PALLET_TO_OAK, LAB_STARTER, LEAVE_LAB]
    return []


def current_beat(obs: PlayerObservation) -> Beat | None:
    beats = script(obs)
    return beats[0] if beats else None


def objective_window(obs: PlayerObservation) -> dict[str, str] | None:
    """Current beat plus the next two, for the dashboard's three slots."""
    window = {tier: beat.text for tier, beat in zip(_TIERS, script(obs))}
    return window or None
