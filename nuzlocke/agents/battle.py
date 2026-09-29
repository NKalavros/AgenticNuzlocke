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

from dataclasses import dataclass
from typing import Any

from nuzlocke.referee.type_chart import effectiveness, types_for_species
from nuzlocke.state.models import GameAction, PlayerObservation

# Menu option -> (column, row) of the 2x2 grid.
_GRID = {"fight": (0, 0), "pkmn": (1, 0), "item": (0, 1), "run": (1, 1)}
_TOKENS = {"FIGHT": "fight", "PM": "pkmn", "ITEM": "item", "RUN": "run"}


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
    lead = obs.party[0] if obs.party else {}
    trainer = (obs.battle or {}).get("type") == "trainer"
    criteria = {
        "fight": (
            f"attack: our {lead.get('species', '?')} {lead.get('hp', '?')}/{lead.get('max_hp', '?')} "
            f"HP vs {enemy.get('species', '?')} lv{enemy.get('level', '?')} "
            f"{enemy.get('hp', '?')}/{enemy.get('max_hp', '?')} HP"
        )
    }
    others = [mon for mon in obs.party[1:] if mon.get("hp")]
    if others:
        names = ", ".join(f"{m.get('species')} {m.get('hp')}/{m.get('max_hp')}" for m in others)
        criteria["pkmn"] = f"switch POKéMON: {names}"
    # No ITEM: this Nuzlocke allows no items; System 3 throws Poké Balls itself.
    if not trainer:
        criteria["run"] = "run from this wild POKéMON"
    plan = plan or {}
    lead_hp = (lead.get("hp") or 0) / (lead.get("max_hp") or 1)
    if "pkmn" in criteria and plan.get("switch_to") and lead_hp < plan.get("switch_below", 0):
        criteria["pkmn"] += f"; System 2's plan: switch to {plan['switch_to']} now"
    elif plan.get("moves"):
        criteria["fight"] += f"; System 2's plan: {', '.join(plan['moves'][:2])}"
    return {
        "action": {
            "type": "choice",
            "instructions": (
                "A battle turn. Pick what to do. `constraints` are Nuzlocke rules that override "
                "everything else. Fight unless our POKéMON is about to faint or the rules say "
                "to catch or run."
            ),
            "criteria": criteria,
        }
    }


def move_questions(
    obs: PlayerObservation,
    moves: tuple[str, ...],
    move_types: dict[str, str],
    plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    enemy = (obs.battle or {}).get("enemy") or {}
    defender = list(types_for_species(str(enemy.get("species") or "")))
    pp = _pp(obs)
    criteria = {}
    for index, move in enumerate(moves):
        facts = [move]
        kind = move_types.get(move)
        if kind:
            facts.append(kind.lower())
            if defender:
                facts.append(_verdict(effectiveness(kind.title(), defender), enemy.get("species")))
        else:
            facts.append("type not seen yet")
        if pp.get(move) is not None:
            facts.append(f"{pp[move]} PP left" if pp[move] else "OUT OF PP")
        ranked = (plan or {}).get("moves") or []
        if move.upper() in ranked:
            facts.append(f"System 2's plan: choice {ranked.index(move.upper()) + 1}")
        criteria[f"move_{index}"] = "; ".join(facts)
    return {
        "action": {
            "type": "choice",
            "instructions": (
                "Pick the move. Prefer super effective ones and damage over stat moves when the "
                "enemy is healthy. Never pick a move that is out of PP or has no effect."
            ),
            "criteria": criteria,
        }
    }


def _pp(obs: PlayerObservation) -> dict[str, Any]:
    """PP left per move of the lead POKéMON, from the party RAM the referee already reads."""
    moves = (obs.party[0].get("moves") if obs.party else None) or []
    return {str(move.get("name")): move.get("pp") for move in moves if isinstance(move, dict)}


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
        walks = [GameAction.WALK_RIGHT if col > cur_col else GameAction.WALK_LEFT] * abs(
            col - cur_col
        )
        walks += [GameAction.WALK_DOWN if row > cur_row else GameAction.WALK_UP] * abs(
            row - cur_row
        )
        return [*walks, GameAction.PRESS_A]
    moves = int(choice.removeprefix("move_")) - (screen.cursor or 0)
    step = GameAction.WALK_DOWN if moves > 0 else GameAction.WALK_UP
    return [step] * abs(moves) + [GameAction.PRESS_A]


def fallback(screen: BattleScreen, obs: PlayerObservation) -> str:
    """When Jev is unsure: FIGHT, and the first move that still has PP."""
    if screen.kind == "menu":
        return "fight"
    pp = _pp(obs)
    for index, move in enumerate(screen.options):
        if pp.get(move, 1):
            return f"move_{index}"
    return "move_0"
