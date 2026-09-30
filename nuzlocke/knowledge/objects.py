"""Names and interactions for live map objects; vanilla identities are explicit priors."""

PICTURES = {
    2: "rival",
    3: "Prof. Oak",
    12: "Super Nerd",
    13: "girl",
    24: "Team Rocket trainer",
    32: "scientist",
    38: "clerk",
    41: "nurse",
    51: "Mom",
    74: "item ball",
    75: "fossil",
    78: "Pokédex",
}


def object_facts(obs, npc):
    picture = int(npc.get("picture", 0))
    facts = {
        **npc,
        "name": PICTURES.get(picture, "person"),
        "source": "live object table; sprite label",
    }
    if obs.map_id == 61 and picture == 75:
        name = {(12, 6): "Dome Fossil", (13, 6): "Helix Fossil"}.get((npc["x"], npc["y"]))
        if name:
            facts.update(name=name, source="live coordinates/sprite; vanilla Mt. Moon identity")
        facts["interaction"] = (
            "Stand below, face up, press A, then YES; taking one opens the exit passage."
        )
    elif picture in {74, 75}:
        facts["interaction"] = "Stand below, face up and press A."
    else:
        facts["interaction"] = "Face the object from an adjacent tile and press A."
    # on_screen is visibility, not proof that a hidden or collected object still exists.
    facts["visibility"] = (
        "on screen" if npc.get("on_screen", True) else "off screen or hidden; verify on arrival"
    )
    return facts


def has_fossil(obs):
    return any(
        str(item.get("item", "")).upper().replace("_", " ") in {"HELIX FOSSIL", "DOME FOSSIL"}
        and item.get("quantity", 0) > 0
        for item in obs.bag
    )


def fossil_question(map_id, rows):
    import re

    text = re.sub(r"[^A-Z]", "", " ".join(rows).upper())
    return map_id == 61 and "YOUWANTTHE" in text
