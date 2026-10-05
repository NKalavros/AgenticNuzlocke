"""Code-owned early-game objectives.

The vision planner may describe the screen and name one button. It does not get to replace the
current beat. Completion is a map name and an empty-or-not party, which the model cannot talk its
way out of.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from nuzlocke.assets import data
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


def load_beat(name: str, **overrides) -> Beat:
    return Beat(**{**data("walkthrough/beats.json")[name], **overrides})


_SHOP_ROUTE = {int(key): Beat(**row) for key, row in data("walkthrough/shop_route.json").items()}
_BROCK_ROUTE = {int(key): Beat(**row) for key, row in data("walkthrough/brock_route.json").items()}

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
    if "Boulder" in obs.badges:
        return _after_brock(obs)
    name = (obs.map_name or "").casefold()
    party = bool(obs.party)
    if obs.map_id == 38:
        return [load_beat("BEDROOM"), load_beat("LIVING"), load_beat("PALLET_TO_OAK")]
    if obs.map_id == 37:
        return [load_beat("LIVING"), load_beat("PALLET_TO_OAK"), load_beat("LAB_STARTER")]
    if not party:
        if "lab" in name:
            return [load_beat("LAB_STARTER"), load_beat("LEAVE_LAB"), load_beat("PALLET_NORTH")]
        if "route 1" in name:
            return [load_beat("ROUTE_OAK"), load_beat("LAB_STARTER"), load_beat("LEAVE_LAB")]
        return [load_beat("PALLET_TO_OAK"), load_beat("LAB_STARTER"), load_beat("LEAVE_LAB")] if "pallet" in name else []
    return _parcel_errand(obs, name)


def _after_brock(obs: PlayerObservation) -> list[Beat]:
    if "Cascade" in obs.badges:
        return []
    mid = obs.map_id
    if mid == 61:
        from nuzlocke.knowledge.objects import has_fossil

        fossils = [n for n in obs.npcs if n.get("picture") == 75]
        if fossils and not has_fossil(obs):
            fossil = min(fossils, key=lambda n: (n.get("x") != 13, n.get("slot", 0)))
            return [load_beat("MOON_CHOOSE_FOSSIL", target={"kind": "npc", "slot": fossil["slot"], "picture": 75})]
    if mid in {1, 2, 3}:
        target = obs.policy.get("preparation_target", 18 if mid != 3 else 21)
        if any(m.get("level", target) < target and not m.get("dead") for m in obs.party):
            return [load_beat("PREPARE_CENTER", target={"kind": "warp", "dest_map": {1: 41, 2: 58, 3: 64}[mid]})]
    if mid in {40, 41, 42, 54, 56, 58, 64, 67, 68}:
        return [load_beat("LEAVE_INTERIOR")]
    if mid in {0, 12, 1, 13, 33, 47, 50, 51}:
        if mid == 13:
            return [load_beat("TO_PEWTER") if (obs.y or 0) < 12 else load_beat("TO_FOREST")]
        if mid == 33:
            return [load_beat("LEAVE_ROUTE22")]
        return [_BROCK_ROUTE[mid]]
    routes = {int(key): row for key, row in data("walkthrough/after_brock.json").items()}
    # The disconnected exit passage has a separate B1F ladder and Route 4 door.
    if mid == 60 and (obs.y or 0) < 6 and (obs.x or 0) > 20:
        routes[60] = ("moon_exit", "Leave Mt. Moon for eastern Route 4.", {"kind": "warp", "dest_map": 255})
    from nuzlocke.knowledge.map_reference import route4_east

    if mid == 15 and route4_east(obs):
        routes[15] = ("cerulean", "Resolve Route 4's encounter, then continue east to Cerulean.", {"kind": "edge", "dir": "right"})
    if mid not in routes:
        return []
    key, text, target = routes[mid]
    return [Beat(key, text, text + " Trust visible terrain if the ROM differs from this route.", target=target)]


# The errand's legs in order, keyed by a piece of the map name. A map can appear twice
# (Route 1 both ways); the first match from the start of the leg wins.
_FETCH = [(key, Beat(**row)) for key, row in data("walkthrough/fetch.json")]
_DELIVER = [(key, Beat(**row)) for key, row in data("walkthrough/deliver.json")]


def _parcel_errand(obs: PlayerObservation, name: str) -> list[Beat]:
    """Starter in hand: fetch Oak's Parcel in Viridian, bring it back, then go north."""
    if obs.map_id in {1, 2}:
        target_level = obs.policy.get("preparation_target", 12 if obs.map_id == 1 else 14)
        if any((m.get("level") or target_level) < target_level and not m.get("dead") for m in obs.party):
            return [load_beat("PREPARE_CENTER_EARLY", target={"kind": "warp", "dest_map": 41 if obs.map_id == 1 else 58})]
    if obs.map_id in {39, 41, 58, 64, 68}:
        return [load_beat("LEAVE_INTERIOR_EARLY")]
    if obs.flags.get("has_pokedex"):
        if "lab" in name:
            return [load_beat("LEAVE_LAB")]
        balls = any("ball" in str(item.get("item") or "").casefold() for item in obs.bag)
        if not balls and (obs.money or 0) >= 200 and obs.map_id in (*_SHOP_ROUTE, 13):
            if obs.map_id == 13:
                return [load_beat("BACK_FOR_BALLS")] if (obs.y or 0) >= 12 else [load_beat("TO_PEWTER")]
            return [_SHOP_ROUTE[obs.map_id]]
        if obs.map_id == 13:  # Route 2: the stretch north of the forest leads to Pewter
            return [load_beat("TO_PEWTER") if (obs.y or 0) < 12 else load_beat("TO_FOREST")]
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
