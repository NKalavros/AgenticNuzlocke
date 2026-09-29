"""System 3: the Nuzlocke controller. Deterministic rules, checked before System 1 and 2.

No items in this Nuzlocke except Poké Balls. Run 20260929-030330-de1d51 blacked out twice with
one Charmander that walked through grass at 3/23 and 1/29 HP and chose FIGHT there, and never
caught anything. The rules:

- Below 25% HP in a wild battle, RUN is pressed without asking Jev.
- Below 50% HP, poisoned, or with anyone fainted, outside battle, the objective is healing: the
  nearest Pokémon Center and its nurse, or Mom in Red's House before the first Center.
- The first wild encounter in each area (once the player has Poké Balls) gets a Poké Ball;
  at "give a nickname?" the answer is NO.

A wipe is detected in ``orchestration.ledger`` and ends the run.
"""

from __future__ import annotations

from nuzlocke.knowledge import beats, trainers
from nuzlocke.knowledge.beats import Beat
from nuzlocke.state.models import PlayerObservation

_RULES = (
    "Nuzlocke: no items except POKé BALLs; a fainted POKéMON is dead; the first wild encounter "
    "in each area is the only one that may be caught; never let the party wipe."
)
RUN_BELOW = 0.25
HEAL_BELOW = 0.5
# Map ids are pokered's (environment.maps).
POKECENTERS = {41, 58, 64, 68}
# pokered's Pokémon Center: the nurse at (3,1) behind the counter, answered from (3,3) facing up.
_NURSE = Beat(
    id="heal_nurse",
    text="Heal: talk to the nurse at the counter and answer YES.",
    hint="Stand below the counter in front of the nurse, face up, press A, then YES.",
    target={"kind": "face", "x": 3, "y": 3, "dir": "up"},
)
_MOM = Beat(
    id="heal_mom",
    text="Heal: talk to Mom in Red's House.",
    hint="Mom sits at the table; talking to her heals the party.",
    target={"kind": "npc", "picture": 51},
)


def _toward(beat_id: str, text: str, target: dict) -> Beat:
    return Beat(id=beat_id, text=f"Heal first: {text}", hint=text, target=target)


# Where to go to heal from each early map.
_ROUTE: dict[int, Beat] = {
    0: _toward("heal_pallet", "go home to Mom.", {"kind": "warp", "dest_map": 37}),
    37: _MOM,
    12: _toward(
        "heal_route1", "go north to Viridian's Pokémon Center.", {"kind": "edge", "dir": "up"}
    ),
    1: _toward("heal_viridian", "enter the Pokémon Center.", {"kind": "warp", "dest_map": 41}),
    50: _toward(
        "heal_gate_s", "leave the gate south toward Viridian.", {"kind": "warp", "dest_map": 255}
    ),
    47: _toward(
        "heal_gate_n", "leave the gate north toward Pewter.", {"kind": "warp", "dest_map": 255}
    ),
    2: _toward("heal_pewter", "enter the Pokémon Center.", {"kind": "warp", "dest_map": 58}),
}


def lead_fraction(obs: PlayerObservation) -> float | None:
    """HP left of the first POKéMON that can still fight, as a fraction."""
    for mon in obs.party:
        if mon.get("max_hp") and mon.get("hp"):
            return mon["hp"] / mon["max_hp"]
    return None


def needs_heal(obs: PlayerObservation) -> bool:
    party = [mon for mon in obs.party if mon.get("max_hp")]
    if not party or obs.in_battle:
        return False
    fraction = lead_fraction(obs)
    # Poison drains 1 HP every 4 steps outside battle and can faint (run 20260929-095253-004c14
    # died walking at 3/24 HP). No items in this Nuzlocke: the only cure is a Pokémon Center.
    poisoned = any(str(mon.get("status") or "").upper().startswith("PSN") for mon in party)
    return (
        fraction is None
        or fraction < HEAL_BELOW
        or poisoned
        or any(not mon.get("hp") for mon in party)
    )


def heal_beat(obs: PlayerObservation) -> Beat | None:
    """Where healing is from here, or None when healthy or no route is known."""
    if not needs_heal(obs) or obs.map_id is None:
        return None
    if obs.map_id in POKECENTERS:
        return _NURSE
    if obs.map_id == 13:  # Route 2: the north section past the forest is nearer Pewter
        up = obs.y is not None and obs.y < 12
        return _toward(
            "heal_route2",
            "head for the nearest Pokémon Center.",
            {"kind": "edge", "dir": "up" if up else "down"},
        )
    if obs.map_id == 51:  # Viridian Forest: whichever gate is nearer
        north = obs.y is not None and obs.y < 24
        gate = 47 if north else 50
        return _toward(
            "heal_forest",
            "leave the forest by the nearer gate.",
            {"kind": "warp", "dest_map": gate},
        )
    return _ROUTE.get(obs.map_id)


def current_beat(obs: PlayerObservation) -> Beat | None:
    """Healing outranks the story."""
    return heal_beat(obs) or beats.current_beat(obs)


def objective_window(obs: PlayerObservation) -> dict[str, str] | None:
    heal = heal_beat(obs)
    story = beats.objective_window(obs)
    if heal is None:
        return story
    return {"primary": heal.text, **({"secondary": story["primary"]} if story else {})}


def has_balls(obs: PlayerObservation) -> bool:
    return any("ball" in str(item.get("item") or "").casefold() for item in obs.bag)


def forced_battle_choice(obs: PlayerObservation, first_encounter: bool = False) -> str | None:
    """System 3's battle rules, before Jev is asked. Survival first, then the catch.

    - RUN from a wild battle when the lead is about to faint (a trainer battle cannot be fled).
    - ITEM (a Poké Ball) at the area's first encounter: the Nuzlocke catch rule. No other item
      is ever used.
    """
    fraction = lead_fraction(obs)
    wild = (obs.battle or {}).get("type") == "wild"
    if wild and fraction is not None and fraction < RUN_BELOW:
        return "run"
    if wild and first_encounter and has_balls(obs):
        return "item"
    return None


def constraints(obs: PlayerObservation, cap: int | None, dead: list[str]) -> list[str]:
    """What System 1 and 2 must obey and know: the rules, the cap, the next boss, trainers here."""
    lines = [_RULES]
    if cap:
        over = [m.get("species") for m in obs.party if (m.get("level") or 0) >= cap]
        lines.append(
            f"level cap {cap}" + (f"; at the cap, avoid extra fights: {over}" if over else "")
        )
    if dead:
        lines.append("dead, never use: " + ", ".join(str(name) for name in dead))
    boss = trainers.next_boss(len(obs.badges))
    if boss:
        lines.append(boss)
    lines += [f"trainer here: {line}" for line in trainers.on_map(obs.map_id)]
    return lines
