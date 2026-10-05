"""Gen-1 type effectiveness — a strategic hint for the Battle role, not a damage calculator."""

from __future__ import annotations

from typing import Any

from nuzlocke.assets import data

# fmt: off
# attacker type -> {defender type: multiplier}. Omitted pairs default to 1.0.
TYPE_CHART = data('type_chart-type_chart.json')

# battle.enemy from pokemon-agent's /state has no `types` field (unlike party[i].types), so the
# enemy's types are resolved from its species name.
SPECIES_TYPES = {key: tuple(value) for key, value in data('type_chart-species_types.json').items()}
# fmt: on


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
        attacker_types = mon.get("types") or types_for_species(str(mon.get("species") or ""))
        if nickname and attacker_types:
            party_hints[nickname] = matchup_hint(list(attacker_types), defender_types)
    return {"enemy_types": defender_types, "party": party_hints} if party_hints else None
