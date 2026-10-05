"""System 1 in battle: the FIGHT / PKMN / ITEM / RUN menu and the move list, read from the tilemap.

Both are ▶ menus in boxes that overlap the text box, so they are read from their rows rather
than as frames (``environment.screen_text``). Read on Red Star in run 20260929-022135-035cb9:

    │       │▶FIGHT PM │        (PkMn is two ligature tiles that decode as "PM")
    │       │ ITEM  RUN│

    │TYPE/    │                 (the highlighted move's type and PP)
    │ NORMAL  │ 20/ 20
    │   │▶SCRATCH      │
    │   │ GROWL        │
    │   │ -            │

Jev picks an option whose description carries the facts (HP, type matchup, PP, whether running
is allowed); code moves the cursor and presses A.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from nuzlocke.environment.status import normalize_status
from nuzlocke.referee.type_chart import effectiveness, types_for_species
from nuzlocke.state.models import GameAction, PlayerObservation

# Menu option -> (column, row) of the 2x2 grid.
_GRID = {"fight": (0, 0), "pkmn": (1, 0), "item": (0, 1), "run": (1, 1)}
_TOKENS = {"FIGHT": "fight", "PM": "pkmn", "ITEM": "item", "RUN": "run"}


def move_facts(obs: PlayerObservation, name: str, move_types=None, plan=None) -> dict[str, Any]:
    """One shared move description for the planner, actor, and its fallback."""
    from nuzlocke.agents.move_learning import move_data, normalized

    mon_move = next((m for m in active_mon(obs).get("moves", []) if normalized(m.get("name")) == normalized(name)), {})
    data = move_data().get(mon_move.get("id")) or next(
        (m for m in move_data().values() if normalized(m["name"]) == normalized(name)), {}
    )
    result = {**data, "name": name, "pp": mon_move.get("pp")}
    result["source"] = "vanilla Red baseline; observed type/PP override; ROM may differ"
    kind = (move_types or {}).get(name) or data.get("type", "UNKNOWN")
    result["type"] = kind.replace("_TYPE", "").title()
    effect, power = data.get("effect", ""), data.get("power")
    special = effect in {"SPECIAL_DAMAGE_EFFECT", "OHKO_EFFECT", "SUPER_FANG_EFFECT"} or power == 1
    result["category"] = "special damage" if special else ("status" if power == 0 else "damage" if power is not None else "unknown")
    status_effect = {"SLEEP_EFFECT": "SLP", "POISON_EFFECT": "PSN", "PARALYZE_EFFECT": "PAR"}
    enemy = (obs.battle or {}).get("enemy") or {}
    status = normalize_status(enemy.get("status"))
    result["enemy_status"] = status
    result["effect_description"] = {
        "SLEEP_EFFECT": "puts the opponent to sleep; no direct damage",
        "POISON_EFFECT": "poisons the opponent; no direct damage",
        "PARALYZE_EFFECT": "paralyzes the opponent; no direct damage",
        "CONFUSION_EFFECT": "confuses the opponent; no direct damage",
    }.get(effect, effect.removesuffix("_EFFECT").replace("_", " ").lower() or "unknown")
    blocked = None
    if result["pp"] == 0:
        blocked = "out of PP"
    elif effect in status_effect and status not in {"OK", "UNKNOWN"}:
        blocked = f"opponent already has {status}; cannot apply another major status"
    elif effect == "DREAM_EATER_EFFECT" and status not in {"SLP", "UNKNOWN"}:
        blocked = "Dream Eater requires a sleeping opponent"
    plan = plan or {}
    repeatable = plan.get("moves") or []
    if repeatable and normalized(name) not in {normalized(m) for m in [*repeatable, *(plan.get("opening_moves") or [])]}:
        blocked = "not in System 2's remaining opening or repeatable moves"
    if normalized(name) in {normalized(m) for m in plan.get("avoid_moves", [])}:
        blocked = "System 2 forbids this move"
    rules = [r for r in plan.get("move_rules", []) if normalized(r["move"]) == normalized(name)]
    if rules:
        result["conditions"] = rules
        if any(status not in r["enemy_status"] for r in rules):
            blocked = f"System 2's condition is not met: enemy status is {status}"
    result["unavailable_reason"] = blocked
    return result


@dataclass(frozen=True)
class BattleScreen:
    kind: str | None = None  # menu | moves
    options: tuple[str, ...] = ()
    cursor: int | None = None
    highlighted_type: str | None = None


def parse_battle(rows: list[str]) -> BattleScreen:
    fight = next((i for i, row in enumerate(rows) if "FIGHT" in row), None)
    if fight is not None and any("RUN" in row for row in rows[fight : fight + 3]):
        cursor = None
        for row in rows[fight : fight + 3]:
            after = row.partition("▶")[2].split()
            if after and after[0] in _TOKENS:
                cursor = list(_GRID).index(_TOKENS[after[0]])
        return BattleScreen("menu", tuple(_GRID), cursor)
    header = next((i for i, row in enumerate(rows) if "TYPE/" in row), None)
    if header is None:
        return BattleScreen()
    kind_cell = rows[header + 1].split("│") if header + 1 < len(rows) else []
    highlighted = kind_cell[1].strip() if len(kind_cell) > 1 else None
    moves: list[str] = []
    cursor = None
    for row in rows[header + 2 :]:
        cells = row.split("│")
        if len(cells) < 4:
            continue
        label = cells[2].strip()
        if label.startswith("▶"):
            cursor = len(moves)
            label = label[1:].strip()
        if label and label != "-":
            moves.append(label)
    return BattleScreen("moves", tuple(moves), cursor, highlighted or None)


def menu_questions(obs: PlayerObservation, plan: dict[str, Any] | None = None) -> dict[str, Any]:
    enemy = (obs.battle or {}).get("enemy") or {}
    lead = active_mon(obs)
    from nuzlocke.agents.level_buffer import reserved, threshold

    trainer = (obs.battle or {}).get("type") == "trainer"
    criteria = {
        "fight": (
            f"attack: our {lead.get('species', '?')} {lead.get('hp', '?')}/{lead.get('max_hp', '?')} "
            f"HP vs {enemy.get('species', '?')} lv{enemy.get('level', '?')} "
            f"{enemy.get('hp', '?')}/{enemy.get('max_hp', '?')} HP; "
            f"our status {normalize_status(lead.get('status'))}; "
            f"opponent status {normalize_status(enemy.get('status'))}"
        )
    }
    others = [
        mon
        for i, mon in enumerate(obs.party)
        if i != (obs.active_party_slot or 0) and mon.get("hp") and not mon.get("dead") and not mon.get("ineligible")
    ]
    if others:
        names = ", ".join(
            f"{m.get('species')} lv{m.get('level', '?')} {m.get('hp')}/{m.get('max_hp')}"
            + (" (reserve XP)" if reserved(obs, m) else "")
            for m in others
        )
        criteria["pkmn"] = f"switch POKéMON: {names}"
    if reserved(obs, lead):
        criteria["fight"] += f"; reserve XP at level {threshold(obs)}+: switch to a healthy suitable alternative unless needed"
    # No ITEM: this Nuzlocke allows no items; System 3 throws Poké Balls itself.
    if not trainer:
        criteria["run"] = "run from this wild POKéMON"
    plan = plan or {}
    lead_hp = (lead.get("hp") or 0) / (lead.get("max_hp") or 1)
    if "pkmn" in criteria and plan.get("switch_to") and lead_hp < plan.get("switch_below", 0):
        criteria["pkmn"] += f"; System 2's plan: switch to {plan['switch_to']} now"
    elif plan.get("moves"):
        criteria["fight"] += f"; System 2's plan: {', '.join(plan['moves'][:2])}"
    moves = active_mon(obs).get("moves") or []
    if (
        moves
        and any(m.get("pp", 1) for m in moves)
        and all(move_facts(obs, m["name"], plan=plan)["unavailable_reason"] for m in moves)
    ):
        del criteria["fight"]
    return {
        "action": {
            "type": "choice",
            "instructions": (
                "A battle turn. Pick what to do. `constraints` are Nuzlocke rules that override "
                "everything else. Fight unless our POKéMON is about to faint or the rules say "
                "to catch or run. Consult system2's strategy, notes, do_not, and switch conditions "
                "against the current HP and status before choosing."
            ),
            "criteria": criteria,
        }
    }


def move_questions(
    obs: PlayerObservation, moves: tuple[str, ...], move_types: dict[str, str], plan: dict[str, Any] | None = None
) -> dict[str, Any]:
    enemy = (obs.battle or {}).get("enemy") or {}
    defender = list(types_for_species(str(enemy.get("species") or "")))
    criteria = {}
    for index, move in enumerate(moves):
        info = move_facts(obs, move, move_types, plan)
        if info["unavailable_reason"]:
            continue
        facts = [move]
        kind = info["type"]
        facts.append(f"{info['category']}; {info['effect_description']}")
        if info["category"] == "status":
            facts.append("no direct damage")
        elif info.get("power") is not None:
            facts.append(f"baseline power {info['power']}" if info["category"] == "damage" else "special damage formula")
        if info.get("accuracy") is not None:
            facts.append(f"baseline accuracy {info['accuracy']}%")
        if kind != "Unknown":
            facts.append(kind.lower())
            if defender and info["category"] == "damage":
                facts.append(_verdict(effectiveness(kind.title(), defender), enemy.get("species")))
        else:
            facts.append("type not seen yet")
        facts.append(f"opponent status: {info['enemy_status']}")
        if info["pp"] is not None:
            facts.append(f"{info['pp']} PP left")
        for rule in info.get("conditions", []):
            facts.append(f"System 2 condition met: enemy status in {rule['enemy_status']}; {rule['reason']}")
        ranked = (plan or {}).get("moves") or []
        if move.upper() in ranked:
            facts.append(f"System 2's plan: choice {ranked.index(move.upper()) + 1}")
        criteria[f"move_{index}"] = "; ".join(facts)
    return {
        "action": {
            "type": "choice",
            "instructions": (
                "Pick the move using system2's strategy, notes, do_not, and the current battle facts. "
                "Nuzlocke constraints override strategy. Status moves do no direct damage; damage "
                "type effectiveness does not measure their usefulness. Attack while the enemy "
                "is asleep. Only offered moves satisfy observed status and System 2's move rules."
            ),
            "criteria": criteria,
        }
    }


def _pp(obs: PlayerObservation) -> dict[str, Any]:
    """PP left per move of the lead POKéMON, from the party RAM the referee already reads."""
    moves = active_mon(obs).get("moves") or []
    return {str(move.get("name")).upper(): move.get("pp") for move in moves if isinstance(move, dict)}


def party_cursor(obs: PlayerObservation) -> int | None:
    """The unframed party list: its solid cursor sits on an HP fraction row."""
    for index, row in enumerate(obs.screen_rows):
        if "▶" not in row or not re.search(r"\d+\s*/\s*\d+", row):
            continue
        slot = index // 2
        if slot < len(obs.party) and index:
            name = str(obs.party[slot].get("nickname") or obs.party[slot].get("species") or "")
            # RAM nicknames can use '?' for Nidoran's gender glyph while the
            # tilemap omits it. Position + HP row identify the slot; compare the
            # visible letters/digits without treating that glyph mismatch as no cursor.
            name = re.sub(r"[^A-Z0-9]", "", name.upper())
            label = re.sub(r"[^A-Z0-9]", "", obs.screen_rows[index - 1].upper())
            if name and name in label:
                return slot
    return None


def _verdict(multiplier: float, species: Any) -> str:
    if multiplier == 0:
        return f"no effect on {species}"
    if multiplier >= 2:
        return f"super effective on {species}"
    if multiplier < 1:
        return f"not very effective on {species}"
    return f"normal damage on {species}"


def actions_for(screen: BattleScreen, choice: str) -> list[GameAction]:
    """Cursor moves from the highlight to the choice, then A."""
    if screen.kind == "menu":
        col, row = _GRID[choice]
        here = list(_GRID)[screen.cursor or 0]
        cur_col, cur_row = _GRID[here]
        walks = [GameAction.WALK_RIGHT if col > cur_col else GameAction.WALK_LEFT] * abs(col - cur_col)
        walks += [GameAction.WALK_DOWN if row > cur_row else GameAction.WALK_UP] * abs(row - cur_row)
        return [*walks, GameAction.PRESS_A]
    moves = int(choice.removeprefix("move_")) - (screen.cursor or 0)
    step = GameAction.WALK_DOWN if moves > 0 else GameAction.WALK_UP
    return [step] * abs(moves) + [GameAction.PRESS_A]


def fallback(screen: BattleScreen, obs: PlayerObservation, criteria=None, plan=None) -> str:
    """Stay within the same conditions as Jev, including when Jev returns a blocked move."""
    if criteria is None:
        questions = menu_questions(obs, plan) if screen.kind == "menu" else move_questions(obs, screen.options, {}, plan)
        criteria = questions["action"]["criteria"]
    if screen.kind == "menu":
        return "fight" if "fight" in criteria else next(iter(criteria))
    from nuzlocke.agents.move_learning import normalized

    for name in (plan or {}).get("moves", []):
        for index, move in enumerate(screen.options):
            if normalized(name) == normalized(move) and f"move_{index}" in criteria:
                return f"move_{index}"
    for key in criteria:
        move = screen.options[int(key.removeprefix("move_"))]
        if move_facts(obs, move)["category"] in {"damage", "special damage"}:
            return key
    return next(iter(criteria))


def active_mon(obs: PlayerObservation) -> dict[str, Any]:
    slot = obs.active_party_slot if obs.active_party_slot is not None else 0
    mon = dict(obs.party[slot]) if 0 <= slot < len(obs.party) else {}
    if obs.in_battle and obs.active_mon:
        mon.update(obs.active_mon)
    return mon
