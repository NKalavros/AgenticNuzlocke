"""System 3: the Nuzlocke controller. Deterministic rules, checked before System 1 and 2.

Battle items are limited to Poké Balls; audited preparation candies are allowed outside battle. Run 20260929-030330-de1d51 blacked out twice with
one Charmander that walked through grass at 3/23 and 1/29 HP and chose FIGHT there, and never
caught anything. The rules:

- Below 25% HP in a wild battle, switch to a suitable healthy teammate for a legal catch,
  otherwise RUN without asking Jev.
- Below 50% HP, poisoned, or with anyone fainted, outside battle, the objective is healing: the
  nearest Pokémon Center and its nurse, or Mom in Red's House before the first Center.
- The first wild encounter in each area (once the player has Poké Balls) gets a Poké Ball;
  at "give a nickname?" the answer is NO.

A wipe is detected in ``orchestration.ledger`` and ends the run.
"""

from __future__ import annotations

from nuzlocke.assets import data
from nuzlocke.knowledge import beats, trainers
from nuzlocke.knowledge.beats import Beat
from nuzlocke.state.models import PlayerObservation

RUN_BELOW = 0.25
HEAL_BELOW = 0.5
# Map ids are pokered's (environment.maps).
POKECENTERS = {41, 58, 64, 68}
HEALING_CENTERS = POKECENTERS | {81, 89, 133, 141, 154}
# pokered's Pokémon Center: the nurse at (3,1) behind the counter, answered from (3,3) facing up.
_NURSE = Beat(**data("walkthrough/nurse.json"))


def _toward(beat_id: str, text: str, target: dict) -> Beat:
    return Beat(id=beat_id, text=f"Heal first: {text}", hint=text, target=target)


# Where to go to heal from each early map.
_ROUTE = {int(key): Beat(**row) for key, row in data("walkthrough/healing_routes.json").items()}

_UNKNOWN_HEAL = Beat(**data("walkthrough/unknown_heal.json"))


def lead_fraction(obs: PlayerObservation) -> float | None:
    """HP left of the first POKéMON that can still fight, as a fraction."""
    from nuzlocke.agents.battle import active_mon

    candidates = [active_mon(obs)] if obs.in_battle else obs.party
    for mon in candidates:
        if mon.get("max_hp") and mon.get("hp") and not mon.get("dead"):
            return mon["hp"] / mon["max_hp"]
    return None


def needs_heal(obs: PlayerObservation) -> bool:
    party = [mon for mon in obs.party if mon.get("max_hp") and not mon.get("dead")]
    if not party or obs.in_battle:
        return False
    fraction = lead_fraction(obs)
    # Poison drains 1 HP every 4 steps outside battle and can faint (run 20260929-095253-004c14
    # died walking at 3/24 HP). No items in this Nuzlocke: the only cure is a Pokémon Center.
    poisoned = any(str(mon.get("status") or "").upper().startswith("PSN") for mon in party)
    return (
        fraction is None
        or fraction < HEAL_BELOW
        or any(m.get("hp", 0) / m["max_hp"] < HEAL_BELOW for m in party)
        or poisoned
        or any(not mon.get("hp") for mon in party)
        or any(m.get("status", "OK") != "OK" for m in party)
        or any(m.get("moves") and all(not move.get("pp", 1) for move in m["moves"]) for m in party)
    )


def heal_beat(obs: PlayerObservation) -> Beat | None:
    """Keep healing mandatory even when the director must find the route."""
    if obs.in_battle:
        return None
    living = [m for m in obs.party if not m.get("dead")]
    target = obs.policy.get("preparation_target", 12 if obs.map_id == 41 else 14)
    preparing = any((m.get("level") or 14) < target for m in living)
    # The grant requires the whole party healthy, including members already at target.
    preparation_heal = (
        obs.map_id in POKECENTERS
        and preparing
        and any(m.get("hp") != m.get("max_hp") or m.get("status", "OK") != "OK" for m in living)
    )
    if (obs.map_id in {2, 54, 58} and "Boulder" not in obs.badges) or (
        obs.map_id in {3, 64, 65} and "Boulder" in obs.badges and "Cascade" not in obs.badges
    ):
        preparation_heal |= any(
            m.get("hp") != m.get("max_hp")
            or m.get("status", "OK") != "OK"
            or any(move.get("pp", 0) < move.get("observed_max_pp", 0) for move in m.get("moves", []))
            for m in living
        )
    if not needs_heal(obs) and not preparation_heal and not obs.policy.get("gym_heal_pending"):
        return None
    if obs.map_id in HEALING_CENTERS:
        return _NURSE
    if obs.map_id == 13:  # Route 2: the north section past the forest is nearer Pewter
        up = obs.y is not None and obs.y < 12
        return _toward("heal_route2", "head for the nearest Pokémon Center.", {"kind": "edge", "dir": "up" if up else "down"})
    if obs.map_id == 51:  # Viridian Forest: whichever gate is nearer
        north = obs.y is not None and obs.y < 24
        gate = 47 if north else 50
        return _toward("heal_forest", "leave the forest by the nearer gate.", {"kind": "warp", "dest_map": gate})
    if obs.map_id == 15:
        from nuzlocke.knowledge.map_reference import route4_east

        target = {"kind": "warp", "dest_map": 68} if not route4_east(obs) else {"kind": "edge", "dir": "right"}
        return _toward("heal_route4", "reach the nearest Center.", target)
    if obs.map_id == 60:
        target = {"kind": "warp", "dest_map": 255} if (obs.y or 0) < 6 and (obs.x or 0) > 20 else {"kind": "warp", "dest_map": 59}
        return _toward("heal_moon_b1", "return to a Center via the nearest surface exit.", target)
    if obs.map_id == 202:
        destination = 201 if (obs.x or 0) < 20 else 203
        return _toward(
            "heal_hideout_b4",
            "return upstairs to Celadon's Center; use B1F in the elevator.",
            {"kind": "warp", "dest_map": destination},
        )
    return _ROUTE.get(obs.map_id, _UNKNOWN_HEAL)


def current_beat(obs: PlayerObservation) -> Beat | None:
    """Healing outranks the story."""
    from nuzlocke.agents.system4 import team_beat

    if obs.policy.get("system4") and team_beat(obs):
        return heal_beat(obs) or team_beat(obs)
    if any(m.get("dead") for m in obs.party) and not obs.in_battle:
        if obs.map_id in HEALING_CENTERS:
            return Beat(
                "box_dead",
                "Deposit permanently dead Pokémon in storage.",
                "Use the PC, SOMEONE'S PC, DEPOSIT, then the dead Pokémon.",
                target={"kind": "face", "x": 13, "y": 4, "dir": "up"},
            )
        # Route to a Center even if the surviving party is healthy.
        hurt = obs.model_copy(update={"party": [{**m, "hp": 1} for m in obs.party if not m.get("dead")]})
        return heal_beat(hurt)
    from nuzlocke.agents.bag_space import space_beat
    from nuzlocke.agents.gym_preparation import gym_beat

    return heal_beat(obs) or space_beat(obs) or supply_beat(obs) or gym_beat(obs) or beats.current_beat(obs)


def supply_beat(obs: PlayerObservation) -> Beat | None:
    if obs.in_battle or not obs.flags.get("has_pokedex") or (obs.money or 0) < 200:
        return None
    count = sum(i.get("quantity", 0) for i in obs.bag if "ball" in str(i.get("item", "")).lower())
    if count >= 10:
        return None
    if obs.map_id in {1, 2, 3}:
        return Beat(
            "buy_balls_city",
            "Restock Poké Balls before the next encounters.",
            "Enter the Mart.",
            target={"kind": "warp", "dest_map": {1: 42, 2: 56, 3: 67}[obs.map_id]},
        )
    if obs.map_id in {42, 56, 67}:
        return beats.load_beat("BUY_BALLS")
    return None


def objective_window(obs: PlayerObservation) -> dict[str, str] | None:
    from nuzlocke.agents.bag_space import space_beat
    from nuzlocke.agents.gym_preparation import gym_beat
    from nuzlocke.agents.system4 import team_beat

    heal = heal_beat(obs) or team_beat(obs) or space_beat(obs) or supply_beat(obs) or gym_beat(obs)
    story = beats.objective_window(obs)
    if heal is None:
        return story
    job = obs.policy.get("system4")
    if job and job["phase"] != "ready":
        return {"primary": heal.text, "secondary": f"Complete team preparation for {job['name']}; then resume progression."}
    state = obs.policy.get("gym_preparation")
    if state:
        remaining = [heal.text]
        if state["phase"] == "heal":
            remaining.append(f"Prepare living Pokémon with audited Rare Candies to level {state['cap']} before {state['name']}.")
        remaining.append(f"Defeat {state['name']} and verify the {state['badge']} Badge.")
        return dict(zip(("primary", "secondary", "tertiary"), remaining))
    return {"primary": heal.text, **({"secondary": story["primary"]} if story else {})}


def has_balls(obs: PlayerObservation) -> bool:
    from nuzlocke.agents.inventory import is_capture_ball

    return any(is_capture_ball(item) for item in obs.bag)


def forced_battle_choice(obs: PlayerObservation, first_encounter: bool = False) -> str | None:
    """System 3's battle rules, before Jev is asked. Survival first, then the catch.

    - RUN from a wild battle when the lead is about to faint (a trainer battle cannot be fled).
    - ITEM (a Poké Ball) at the area's first encounter: the Nuzlocke catch rule. No other item
      is ever used.
    """
    from nuzlocke.knowledge.walkthrough import story_battle

    mandatory = story_battle(obs)
    fraction = lead_fraction(obs)
    wild = (obs.battle or {}).get("type") == "wild"
    from nuzlocke.agents.battle import active_mon
    from nuzlocke.agents.level_buffer import eligible, switch_target

    active = active_mon(obs)
    if active.get("dead") or active.get("ineligible"):
        if any(i != (obs.active_party_slot or 0) and eligible(m) for i, m in enumerate(obs.party)):
            return "pkmn"
        return "run" if wild else None
    if wild and not mandatory and obs.policy.get("duplicate_encounter"):
        return "run"
    if wild and not mandatory and obs.policy.get("avoid_wild_grinding") and not first_encounter:
        return "run"
    if wild and fraction is not None and fraction < RUN_BELOW:
        if (mandatory or (first_encounter and has_balls(obs))) and switch_target(obs, first_encounter=first_encounter) is not None:
            return "pkmn"
        return "run"
    if wild and not mandatory and first_encounter and has_balls(obs):
        return "item"
    if switch_target(obs) is not None:
        return "pkmn"
    return None


def constraints(obs: PlayerObservation, cap: int | None, dead: list[str]) -> list[str]:
    """What System 1 and 2 must obey and know: the rules, the cap, the next boss, trainers here."""
    from nuzlocke.knowledge.walkthrough import story_battle

    lines = [data("rule_briefing.json")]
    lines.append(
        "Observed complete bag (including off-screen items): "
        + str(obs.bag)
        + ". Use these quantities as evidence; do not open PACK just to verify ownership. Close inspection menus and continue the objective."
    )
    if encounter := story_battle(obs):
        lines.append(encounter["notes"])
    from nuzlocke.agents.gym_preparation import party_ready

    if obs.map_id in HEALING_CENTERS and party_ready(obs):
        lines.append(
            "Observed party recovery: every living member has full HP, OK status and restored observed PP. "
            "Finish any mandatory nurse-acceptance stage and close healing text/menus, then resume the destination. "
            "Use these supplied facts; opening party STATS to recheck recovery is unnecessary."
        )
    lines += [
        f"Living field-move user: {mon.get('nickname') or mon.get('species')} knows {move['name']}; verify field permission."
        for mon in obs.party
        if mon.get("hp", 0) > 0 and not mon.get("dead")
        for move in mon.get("moves", [])
        if move.get("name", "").upper() in {"CUT", "STRENGTH", "ROCK SMASH"}
    ]
    if cap:
        buffer = int(obs.policy.get("level_cap_buffer", 1))
        over = [m.get("species") for m in obs.party if (m.get("level") or 0) >= cap - buffer]
        lines.append(
            f"level cap {cap}; reserve level {cap - buffer}+ Pokémon from routine XP when a healthy suitable alternative exists"
            + (f"; reserve: {over}" if over else "")
        )
        lines.append(
            "Use a reserved but legal Pokémon only when alternatives are unsafe or unavailable; over-cap Pokémon remain ineligible for new battles. Switch before fights when possible, as switching after entry can still share XP."
        )
    lines += ["dead, never use: " + ", ".join(str(name) for name in dead)] if dead else []
    lines.extend(filter(None, [trainers.next_boss(len(obs.badges))]))
    lines += [f"trainer here: {line}" for line in trainers.on_map(obs.map_id)]
    return lines
