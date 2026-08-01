"""Gen-1 type effectiveness — a lean strategic hint for the Battle role.

Not a damage calculator: no power/accuracy/stat-stage math, just the
attack-type-vs-defend-type multiplier Gen 1 actually used (including its two
well-known quirks: Bug is super effective against Poison, and the
Ghost-vs-Psychic "CATCH_23" bug makes Ghost moves do nothing to Psychic
types instead of the intended super-effective hit).
"""

from __future__ import annotations

from typing import Any

# attacker type -> {defender type: multiplier}. Omitted pairs default to 1.0.
TYPE_CHART: dict[str, dict[str, float]] = {
    "Normal": {"Rock": 0.5, "Ghost": 0.0},
    "Fire": {"Grass": 2.0, "Ice": 2.0, "Bug": 2.0, "Fire": 0.5, "Water": 0.5, "Rock": 0.5, "Dragon": 0.5},
    "Water": {"Fire": 2.0, "Ground": 2.0, "Rock": 2.0, "Water": 0.5, "Grass": 0.5, "Dragon": 0.5},
    "Electric": {"Water": 2.0, "Flying": 2.0, "Electric": 0.5, "Grass": 0.5, "Dragon": 0.5, "Ground": 0.0},
    "Grass": {
        "Water": 2.0, "Ground": 2.0, "Rock": 2.0,
        "Fire": 0.5, "Grass": 0.5, "Poison": 0.5, "Flying": 0.5, "Bug": 0.5, "Dragon": 0.5,
    },
    "Ice": {"Grass": 2.0, "Ground": 2.0, "Flying": 2.0, "Dragon": 2.0, "Fire": 0.5, "Water": 0.5, "Ice": 0.5},
    "Fighting": {
        "Normal": 2.0, "Ice": 2.0, "Rock": 2.0,
        "Poison": 0.5, "Flying": 0.5, "Psychic": 0.5, "Bug": 0.5, "Ghost": 0.0,
    },
    "Poison": {"Grass": 2.0, "Bug": 2.0, "Poison": 0.5, "Ground": 0.5, "Rock": 0.5, "Ghost": 0.5},
    "Ground": {"Fire": 2.0, "Electric": 2.0, "Poison": 2.0, "Rock": 2.0, "Grass": 0.5, "Bug": 0.5, "Flying": 0.0},
    "Flying": {"Fighting": 2.0, "Bug": 2.0, "Grass": 2.0, "Electric": 0.5, "Rock": 0.5},
    "Psychic": {"Fighting": 2.0, "Poison": 2.0, "Psychic": 0.5},
    # Gen 1: Bug is super effective against Poison (nerfed to 0.5x from Gen 2 on).
    "Bug": {"Grass": 2.0, "Psychic": 2.0, "Poison": 2.0, "Fire": 0.5, "Fighting": 0.5, "Flying": 0.5, "Ghost": 0.5},
    "Rock": {"Fire": 2.0, "Ice": 2.0, "Flying": 2.0, "Bug": 2.0, "Fighting": 0.5, "Ground": 0.5},
    # Gen 1 CATCH_23 bug: Ghost has no effect on Psychic (intended super effective).
    "Ghost": {"Ghost": 2.0, "Psychic": 0.0, "Normal": 0.0},
    "Dragon": {"Dragon": 2.0},
}

# battle.enemy from pokemon-agent's /state has species/level/hp/moves/status
# but no `types` field (unlike the player's own party[i].types), so the
# enemy's types must be resolved from species name via this static table.
SPECIES_TYPES: dict[str, tuple[str, ...]] = {
    "Bulbasaur": ("Grass", "Poison"), "Ivysaur": ("Grass", "Poison"), "Venusaur": ("Grass", "Poison"),
    "Charmander": ("Fire",), "Charmeleon": ("Fire",), "Charizard": ("Fire", "Flying"),
    "Squirtle": ("Water",), "Wartortle": ("Water",), "Blastoise": ("Water",),
    "Caterpie": ("Bug",), "Metapod": ("Bug",), "Butterfree": ("Bug", "Flying"),
    "Weedle": ("Bug", "Poison"), "Kakuna": ("Bug", "Poison"), "Beedrill": ("Bug", "Poison"),
    "Pidgey": ("Normal", "Flying"), "Pidgeotto": ("Normal", "Flying"), "Pidgeot": ("Normal", "Flying"),
    "Rattata": ("Normal",), "Raticate": ("Normal",),
    "Spearow": ("Normal", "Flying"), "Fearow": ("Normal", "Flying"),
    "Ekans": ("Poison",), "Arbok": ("Poison",),
    "Pikachu": ("Electric",), "Raichu": ("Electric",),
    "Sandshrew": ("Ground",), "Sandslash": ("Ground",),
    "Nidoran♀": ("Poison",), "Nidorina": ("Poison",), "Nidoqueen": ("Poison", "Ground"),
    "Nidoran♂": ("Poison",), "Nidorino": ("Poison",), "Nidoking": ("Poison", "Ground"),
    "Clefairy": ("Normal",), "Clefable": ("Normal",),
    "Vulpix": ("Fire",), "Ninetales": ("Fire",),
    "Jigglypuff": ("Normal",), "Wigglytuff": ("Normal",),
    "Zubat": ("Poison", "Flying"), "Golbat": ("Poison", "Flying"),
    "Oddish": ("Grass", "Poison"), "Gloom": ("Grass", "Poison"), "Vileplume": ("Grass", "Poison"),
    "Paras": ("Bug", "Grass"), "Parasect": ("Bug", "Grass"),
    "Venonat": ("Bug", "Poison"), "Venomoth": ("Bug", "Poison"),
    "Diglett": ("Ground",), "Dugtrio": ("Ground",),
    "Meowth": ("Normal",), "Persian": ("Normal",),
    "Psyduck": ("Water",), "Golduck": ("Water",),
    "Mankey": ("Fighting",), "Primeape": ("Fighting",),
    "Growlithe": ("Fire",), "Arcanine": ("Fire",),
    "Poliwag": ("Water",), "Poliwhirl": ("Water",), "Poliwrath": ("Water", "Fighting"),
    "Abra": ("Psychic",), "Kadabra": ("Psychic",), "Alakazam": ("Psychic",),
    "Machop": ("Fighting",), "Machoke": ("Fighting",), "Machamp": ("Fighting",),
    "Bellsprout": ("Grass", "Poison"), "Weepinbell": ("Grass", "Poison"), "Victreebel": ("Grass", "Poison"),
    "Tentacool": ("Water", "Poison"), "Tentacruel": ("Water", "Poison"),
    "Geodude": ("Rock", "Ground"), "Graveler": ("Rock", "Ground"), "Golem": ("Rock", "Ground"),
    "Ponyta": ("Fire",), "Rapidash": ("Fire",),
    "Slowpoke": ("Water", "Psychic"), "Slowbro": ("Water", "Psychic"),
    "Magnemite": ("Electric",), "Magneton": ("Electric",),
    "Farfetch'd": ("Normal", "Flying"),
    "Doduo": ("Normal", "Flying"), "Dodrio": ("Normal", "Flying"),
    "Seel": ("Water",), "Dewgong": ("Water", "Ice"),
    "Grimer": ("Poison",), "Muk": ("Poison",),
    "Shellder": ("Water",), "Cloyster": ("Water", "Ice"),
    "Gastly": ("Ghost", "Poison"), "Haunter": ("Ghost", "Poison"), "Gengar": ("Ghost", "Poison"),
    "Onix": ("Rock", "Ground"),
    "Drowzee": ("Psychic",), "Hypno": ("Psychic",),
    "Krabby": ("Water",), "Kingler": ("Water",),
    "Voltorb": ("Electric",), "Electrode": ("Electric",),
    "Exeggcute": ("Grass", "Psychic"), "Exeggutor": ("Grass", "Psychic"),
    "Cubone": ("Ground",), "Marowak": ("Ground",),
    "Hitmonlee": ("Fighting",), "Hitmonchan": ("Fighting",),
    "Lickitung": ("Normal",),
    "Koffing": ("Poison",), "Weezing": ("Poison",),
    "Rhyhorn": ("Ground", "Rock"), "Rhydon": ("Ground", "Rock"),
    "Chansey": ("Normal",),
    "Tangela": ("Grass",),
    "Kangaskhan": ("Normal",),
    "Horsea": ("Water",), "Seadra": ("Water",),
    "Goldeen": ("Water",), "Seaking": ("Water",),
    "Staryu": ("Water",), "Starmie": ("Water", "Psychic"),
    "Mr. Mime": ("Psychic",),
    "Scyther": ("Bug", "Flying"),
    "Jynx": ("Ice", "Psychic"),
    "Electabuzz": ("Electric",),
    "Magmar": ("Fire",),
    "Pinsir": ("Bug",),
    "Tauros": ("Normal",),
    "Magikarp": ("Water",), "Gyarados": ("Water", "Flying"),
    "Lapras": ("Water", "Ice"),
    "Ditto": ("Normal",),
    "Eevee": ("Normal",),
    "Vaporeon": ("Water",), "Jolteon": ("Electric",), "Flareon": ("Fire",),
    "Porygon": ("Normal",),
    "Omanyte": ("Rock", "Water"), "Omastar": ("Rock", "Water"),
    "Kabuto": ("Rock", "Water"), "Kabutops": ("Rock", "Water"),
    "Aerodactyl": ("Rock", "Flying"),
    "Snorlax": ("Normal",),
    "Articuno": ("Ice", "Flying"), "Zapdos": ("Electric", "Flying"), "Moltres": ("Fire", "Flying"),
    "Dratini": ("Dragon",), "Dragonair": ("Dragon",), "Dragonite": ("Dragon", "Flying"),
    "Mewtwo": ("Psychic",), "Mew": ("Psychic",),
}


def types_for_species(species: str) -> tuple[str, ...]:
    return SPECIES_TYPES.get(species, ())


def effectiveness(attacker_type: str, defender_types: list[str]) -> float:
    mult = 1.0
    for defender_type in defender_types:
        mult *= TYPE_CHART.get(attacker_type, {}).get(defender_type, 1.0)
    return mult


def matchup_hint(attacker_types: list[str], defender_types: list[str]) -> str:
    """Best-case matchup across attacker_types' STAB moves vs defender_types."""
    if not attacker_types or not defender_types:
        return "normal"
    mult = max(effectiveness(t, defender_types) for t in attacker_types)
    if mult == 0.0:
        return "no effect"
    if mult >= 2.0:
        return "super effective"
    if mult < 1.0:
        return "not very effective"
    return "normal"


def battle_matchup(party: list[dict[str, Any]], enemy_species: str) -> dict[str, Any] | None:
    """Per-party-member type-matchup hints against the current enemy species."""
    defender_types = list(types_for_species(enemy_species))
    if not defender_types:
        return None
    party_hints: dict[str, str] = {}
    for mon in party:
        nickname = str(mon.get("nickname") or mon.get("species") or "")
        attacker_types = mon.get("types") or list(types_for_species(str(mon.get("species") or "")))
        if not nickname or not attacker_types:
            continue
        party_hints[nickname] = matchup_hint(list(attacker_types), defender_types)
    if not party_hints:
        return None
    return {"enemy_types": defender_types, "party": party_hints}
