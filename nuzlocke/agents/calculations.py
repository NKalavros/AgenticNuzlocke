"""Bounded Gen I reference calculations, not a simulator or hidden-enemy reader."""

from math import ceil

from nuzlocke.agents.move_learning import move_data
from nuzlocke.assets import data
from nuzlocke.referee.type_chart import effectiveness, types_for_species

SPECIAL = {"Fire", "Water", "Grass", "Electric", "Ice", "Psychic", "Dragon"}
STATS = ("hp", "attack", "defense", "speed", "special")


def projected(mon, level=None):
    level = level or mon.get("level")
    if level == mon.get("level") and mon.get("stats") and mon.get("max_hp"):
        return {**mon, "calculation_source": "observed stats; unmodified battle stages assumed"}
    base = data("walkthrough/species_red.json")["species"].get(str(mon.get("species", "")).upper(), {}).get("base")
    if not base or not level:
        return None
    dvs = mon.get("dvs", [15] * 4)
    hp_dv = sum((d & 1) << (3 - i) for i, d in enumerate(dvs))
    effort = mon.get("stat_exp", [0] * 5)
    values = [
        ((2 * (b + dv) + min(255, ceil(e**0.5)) // 4) * level) // 100 + (level + 10 if i == 0 else 5)
        for i, (b, dv, e) in enumerate(zip(base, [hp_dv, *dvs], effort))
    ]
    return {
        **mon,
        "level": level,
        "max_hp": values[0],
        "stats": dict(zip(STATS[1:], values[1:])),
        "types": mon.get("types") or list(types_for_species(mon["species"])),
        "calculation_source": "vanilla base stats; owned DVs/effort" if mon.get("dvs") else "reference enemy: max DVs, zero effort",
    }


def damage(attacker, defender, move, *, critical=False):
    """Inclusive damage bounds; caller exposes accuracy and unknown effects separately."""
    m = move_data().get(move.get("id"), {})
    power, kind = m.get("power"), m.get("type", "Unknown").replace("_TYPE", "").title()
    if not attacker or not defender or power is None:
        return {"unknown": "missing stats or move data"}
    if power == 1 or m.get("effect") in {
        "OHKO_EFFECT",
        "SPECIAL_DAMAGE_EFFECT",
        "SUPER_FANG_EFFECT",
        "COUNTER_EFFECT",
        "BIDE_EFFECT",
    }:
        return {"unknown": "special damage formula is unsupported"}
    if power == 0:
        return {"damage": [0, 0], "effect": m.get("effect"), "source": "reference status move"}
    if m.get("effect") == "DREAM_EATER_EFFECT" and defender.get("status") != "SLP":
        return {"unknown": "Dream Eater requires confirmed sleep"}
    atk, defense = ("special", "special") if kind in SPECIAL else ("attack", "defense")
    a, d = attacker["stats"][atk], defender["stats"][defense]
    if atk == "attack" and attacker.get("status") == "BRN" and not critical:
        a = max(1, a // 2)
    if max(a, d) > 255 and m.get("effect") == "EXPLODE_EFFECT":
        return {"unknown": "explosion with overflowing stats is outside the verified calculation bounds"}
    if max(a, d) > 255:
        a, d = (a // 4) % 256, max(1, (d // 4) % 256)
    if m.get("effect") == "EXPLODE_EFFECT":
        d = max(1, d // 2)
    n = min(997, ((2 * attacker["level"] * (2 if critical else 1) // 5 + 2) * power * a // max(1, d)) // 50) + 2
    if kind in attacker.get("types", types_for_species(attacker.get("species", ""))):
        n += n // 2
    for t in dict.fromkeys(defender.get("types", types_for_species(defender.get("species", "")))):
        n = int(n * effectiveness(kind, [t]))
    hits = (
        [2, 5]
        if m.get("effect") == "TWO_TO_FIVE_ATTACKS_EFFECT"
        else [2, 2]
        if m.get("effect") in {"ATTACK_TWICE_EFFECT", "TWINEEDLE_EFFECT"}
        else [1, 1]
    )
    lo, hi = (max(1, n * 217 // 255), n) if n else (0, 0)
    return {
        "damage": [lo * hits[0], hi * hits[1]],
        "hits_to_ko": [ceil(defender["max_hp"] / (hi * hits[1])), ceil(defender["max_hp"] / (lo * hits[0]))] if lo else None,
        "accuracy": m.get("accuracy"),
        "source": "Gen I baseline; neutral stages, no screens or badge boosts; ROM may differ",
    }


def comparisons(roster, enemies, cap):
    result = []
    for mon in roster:
        if mon.get("dead") or mon.get("ineligible"):
            continue
        own = projected(mon, max(mon.get("level", 1), cap) if cap else None)
        if not own:
            continue
        for enemy in enemies:
            foe = projected(enemy)
            if not foe:
                continue
            incoming = [
                {"move": m.get("name", m.get("id")), **damage(foe, own, m), "critical": damage(foe, own, m, critical=True)}
                for m in enemy.get("moves", [])
            ]
            result.append(
                {
                    "capture_id": mon["capture_id"],
                    "level": own["level"],
                    "enemy": enemy["species"],
                    "speed": [m["stats"]["speed"] // (4 if m.get("status") == "PAR" else 1) for m in (own, foe)],
                    "outgoing": [
                        {"move": m["name"], **damage(own, foe, m), "critical": damage(own, foe, m, critical=True)}
                        for m in mon.get("moves", [])
                    ],
                    "incoming": incoming or "unknown: enemy moves undocumented",
                    "assumptions": [own["calculation_source"], foe["calculation_source"]],
                }
            )
    return result
