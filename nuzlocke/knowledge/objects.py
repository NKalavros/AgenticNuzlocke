"""Names and interactions for live map objects; vanilla identities are explicit priors."""

from nuzlocke.assets import data as asset_data

PICTURES = {int(key): value for key, value in asset_data("objects.json").items()}


def object_available(obs, npc):
    """Keep real off-screen targets, exclude script-hidden/collected objects."""
    if npc.get("on_screen", True):
        return True  # Drawing contradicts a stale hidden flag.
    if "hidden" in npc:
        return not npc["hidden"]
    # Older servers: an invisible object well inside the viewport is absent here.
    return not (obs.x is not None and obs.y is not None and abs(npc["x"] - obs.x) <= 3 and abs(npc["y"] - obs.y) <= 3)


def object_facts(obs, npc):
    picture = int(npc.get("picture", 0))
    facts = {**npc, "name": PICTURES.get(picture, "person"), "source": "live object table; sprite label"}
    if nurse_interaction(obs, npc):
        facts["interaction"] = "Stand at (3,3), face up across the counter, press A and select HEAL or YES."
    elif field_item(npc):
        facts.update(name=npc["item_name"], source="live map item ID", collectible=True, available=object_available(obs, npc))
        facts["interaction"] = "Face the item from any reachable adjacent tile and press A."
    elif obs.map_id == 61 and picture == 75:
        name = {(12, 6): "Dome Fossil", (13, 6): "Helix Fossil"}.get((npc["x"], npc["y"]))
        if name:
            facts.update(name=name, source="live coordinates/sprite; vanilla Mt. Moon identity")
        facts["interaction"] = "Stand below, face up, press A, then YES; taking one opens the exit passage."
    elif picture in {74, 75}:
        facts["interaction"] = "Stand below, face up and press A."
    else:
        facts["interaction"] = "Face the object from an adjacent tile and press A."
    facts["visibility"] = (
        "hidden or absent; not an interaction target"
        if not object_available(obs, npc)
        else "on screen"
        if npc.get("on_screen", True)
        else "off screen; verify on arrival"
    )
    return facts


def nurse_interaction(obs, npc):
    from nuzlocke.agents.system3 import HEALING_CENTERS

    return (3, 3) if obs.map_id in HEALING_CENTERS and npc.get("picture") == 41 and (npc["x"], npc["y"]) == (3, 1) else None


def field_item(npc):
    """A decoded field item, not a starter, fossil choice, or scripted gift."""
    return npc.get("picture") == 74 and bool(npc.get("item_id") and npc.get("item_name"))


def interaction_sides(npc):
    # Starters and fossils retain their verified below-only script interaction.
    return ("down",) if npc.get("picture") in {74, 75} and not field_item(npc) else ("up", "down", "left", "right")


def has_fossil(obs):
    return any(
        str(item.get("item", "")).upper().replace("_", " ") in {"HELIX FOSSIL", "DOME FOSSIL"} and item.get("quantity", 0) > 0
        for item in obs.bag
    )


def fossil_question(map_id, rows):
    import re

    text = re.sub(r"[^A-Z]", "", " ".join(rows).upper())
    return map_id == 61 and "YOUWANTTHE" in text
