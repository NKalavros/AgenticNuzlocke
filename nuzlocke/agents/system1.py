"""System 1: every cycle's press, decided by Jev and code without a vision call.

- A ▶ menu (NEW GAME, the name lists, YES/NO, START): Jev picks a row from
  the decoded text; code moves the highlight and presses A.
- An open text box with no menu: page it with ``skip_dialog``.
- The title and intro splash: code presses START.
- A cutscene (the game ignores the D-pad or walks the player): wait.
- The overworld: Jev picks a goal from ``agents.goals``; code walks its path.

It returns a ``trigger`` instead of a press when there is a decision System 2
(the vision director) has to make: no objective, an objective this map
cannot reach, Jev unsure twice, a goal that keeps failing, or Jev judging the
objective done. In battle it answers the FIGHT / PKMN / ITEM / RUN menu and the move list
(``agents.battle``). The naming keyboard and battle screens it cannot read are not System 1's
(``None``); the older planner path handles them.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from nuzlocke.agents import battle
from nuzlocke.agents.goals import Goal, RoomMap, build_goals, goal_questions, mark, pick
from nuzlocke.agents.jev_policy import accepts, battle_facts
from nuzlocke.agents.system3 import forced_battle_choice
from nuzlocke.environment.joypad import is_naming_lock
from nuzlocke.environment.screen_text import ScreenText, parse_screen
from nuzlocke.knowledge.beats import is_intro_boot
from nuzlocke.llm.jev import JevAnswers, JevDecisionError
from nuzlocke.state.models import GameAction, PlayerObservation

INTRO_GOAL = "Start a NEW GAME. Name yourself RED and the rival BLUE from the preset lists."
_GOAL_FAILS_FOR_LOOK = 3
# Title, copyright, and Oak's pictures are timed; a lone START (20 frames) mostly lands on nothing.
_TITLE = [GameAction.WAIT_60, GameAction.WAIT_60, GameAction.PRESS_START]

Decide = Callable[[dict[str, Any], dict[str, Any]], JevAnswers]


@dataclass
class S1Turn:
    actions: list[GameAction]
    reason: str
    kind: str  # goal | menu | page | title | cutscene | battle | trigger
    goal: Goal | None = None
    choice: str = ""
    probability: float | None = None
    # Set when System 2 must look before anything is pressed.
    trigger: str | None = None
    low_confidence_streak: int = 0


def _look(why: str) -> S1Turn:
    return S1Turn([], why, "trigger", trigger=why)


def _ask(jev_decide: Decide, state: dict[str, Any], questions: dict[str, Any]) -> JevAnswers | None:
    try:
        return jev_decide({key: value for key, value in state.items() if value}, questions)
    except JevDecisionError:
        return None


def system1_turn(
    *,
    obs: PlayerObservation,
    screen: ScreenText,
    text_box: bool,
    mash_stalled: bool,
    room: RoomMap,
    objective: dict[str, Any] | None,
    objective_text: str | None,
    objective_from_code: bool,
    heading: str | None,
    fails: dict[str, int],
    last_direction: str | None,
    low_confidence_streak: int,
    confidence_floor: float,
    stale_noul: float,
    journal: list[str],
    constraints: list[str],
    jev_decide: Decide,
    move_types: dict[str, str] | None = None,
    last_texts: dict[str, str] | None = None,
    first_encounter: bool = False,
    battle_plan: dict[str, Any] | None = None,
    navigator: Any = None,
    route_plan: dict | None = None,
) -> S1Turn | None:
    if is_naming_lock(obs.joy_ignore):
        # 0xD730 bit 6 is "instant text": the naming keyboard, but also the Pokédex page before
        # the starter's YES/NO (pitfall #4) and the bag list in battle. The screen says which.
        if any("WT" in row for row in obs.screen_rows):
            return S1Turn([GameAction.PRESS_A, GameAction.WAIT_60], "Pokédex page; A", "page")
        if any("A B C D E F G H I" in row for row in obs.screen_rows):
            return None
    if obs.in_battle:
        return _battle_turn(
            obs,
            text_box,
            mash_stalled,
            move_types,
            journal,
            constraints,
            confidence_floor,
            jev_decide,
            first_encounter,
            battle_plan,
        )
    intro = is_intro_boot(obs)
    goal_text = objective_text or (INTRO_GOAL if intro else None)
    if screen.menu_rows and screen.cursor_row is not None:
        return _menu_turn(
            screen, goal_text, journal, low_confidence_streak, confidence_floor, jev_decide
        )
    if text_box:
        special = _special_page(obs.screen_rows)
        if special is not None:
            return special
        if mash_stalled:
            return _look("text did not page")
        return S1Turn([GameAction.SKIP_DIALOG], "speech on screen; skip_dialog", "page")
    if intro:
        return S1Turn(list(_TITLE), "title or intro screen; START", "title")
    if obs.cutscene:
        # Oak's escort, the rival's walk: the game is moving, and the D-pad does nothing.
        return S1Turn([GameAction.WAIT_60], "cutscene; waiting for control", "cutscene")
    if not objective:
        return _look("no objective")

    if navigator is not None:
        navigator.observe(obs, room)
    goals = build_goals(
        obs,
        room,
        objective=objective,
        objective_text=goal_text,
        heading=heading,
        tried=fails,
        last_direction=last_direction,
        last_texts=last_texts,
    )
    if not any(goal.objective for goal in goals):
        # A code-owned beat whose target is not on screen still has its story heading.
        heading_goal = next((g for g in goals if g.kind == "heading"), None)
        if heading_goal is None or not objective_from_code:
            return _look("objective not on this map")
        mark(heading_goal, goal_text)
    routed = None
    if navigator is not None:
        routed = navigator.select(
            obs,
            room,
            goals,
            objective_text=goal_text,
            plan=route_plan,
            failed=any(fails.get(g.key, 0) for g in goals if g.objective),
        )
        if routed is not None:
            goals = [routed, *[g for g in goals if g.key != routed.key]]
            if navigator.reason == "Continuing verified route":
                return S1Turn(
                    routed.actions, f"route: {routed.label}", "goal", goal=routed, choice=routed.key
                )
    if any(goal.objective and not goal.actions for goal in goals):
        return _look("objective path blocked")
    state = {
        "navigation": navigator.brief if navigator else None,
        "goal": goal_text,
        "where": {"map": obs.map_name, "x": obs.x, "y": obs.y, "facing": obs.facing},
        "recent": journal[-6:],
        "constraints": constraints,
    }
    read = _ask(jev_decide, state, goal_questions(goals, judged=not objective_from_code))
    if read is not None and not objective_from_code and read.objective_done >= stale_noul:
        return _look("jev: objective done")
    streak = 0
    if accepts(read, confidence_floor):
        assert read is not None
        chosen = pick(goals, read.action, read.probabilities, fails)
        probability = read.probabilities.get(read.action)
        why = f"jev {read.action} (p {read.confidence:.2f})"
        if chosen is not None and chosen.key != read.action:
            why += f"; failed here, runner-up {chosen.key}"
    else:
        streak = low_confidence_streak + 1
        executable_objective = any(
            g.objective and g.actions and fails.get(g.key, 0) == 0 for g in goals
        )
        if streak >= 2 and not (objective_from_code and executable_objective):
            return _look("jev unsure twice")
        chosen, probability, why = None, None, "jev unsure; objective goal"
    wait = next(g for g in goals if g.key == "wait")
    if routed is not None and objective_from_code and not fails.get(routed.key, 0):
        chosen = routed
        why = "follow verified objective route"
    chosen = chosen or next((g for g in goals if g.objective and g.actions), wait)
    if fails.get(chosen.key, 0) >= _GOAL_FAILS_FOR_LOOK:
        return _look("goal keeps failing")
    return S1Turn(
        chosen.actions,
        f"{why}: {chosen.label}",
        "goal",
        goal=chosen,
        choice=chosen.key,
        probability=probability,
        low_confidence_streak=streak,
    )


def _battle_turn(
    obs: PlayerObservation,
    text_box: bool,
    mash_stalled: bool,
    move_types: dict[str, str] | None,
    journal: list[str],
    constraints: list[str],
    confidence_floor: float,
    jev_decide: Decide,
    first_encounter: bool = False,
    battle_plan: dict[str, Any] | None = None,
) -> S1Turn | None:
    screen = battle.parse_battle(obs.screen_rows)
    if screen.kind == "moves" and (
        battle.active_mon(obs).get("dead")
        or battle.active_mon(obs).get("ineligible")
        or forced_battle_choice(obs, first_encounter) is not None
    ):
        return S1Turn(
            [GameAction.PRESS_B], "System 3: return to battle menu for required action", "battle"
        )
    party_cursor = battle.party_cursor(obs)
    if party_cursor is not None:
        desired = str((battle_plan or {}).get("switch_to") or "").upper()
        from nuzlocke.agents.level_buffer import switch_order

        eligible = switch_order(obs, desired)
        if eligible:
            slot, _ = eligible[0]
            return S1Turn(
                menu_actions(f"choose_{slot}", party_cursor),
                f"select legal party slot {slot}",
                "battle",
            )
        return S1Turn([GameAction.PRESS_B], "no eligible replacement; leave party menu", "battle")
    known = move_types if move_types is not None else {}
    if screen.kind == "moves" and screen.cursor is not None and screen.highlighted_type:
        # The TYPE/ box shows only the highlighted move; each one seen is remembered.
        known[screen.options[screen.cursor]] = screen.highlighted_type
    if screen.kind is None:
        other = parse_screen(obs.screen_rows)
        if other.menu_rows and other.cursor_row is not None:
            return _battle_menu(
                other, first_encounter, journal, confidence_floor, jev_decide, obs, battle_plan
            )
        # Battle paging uses a single A pulse; a still line may be an animation in progress.
        if text_box:
            special = _special_page(obs.screen_rows)
            if special is not None:
                return special
            if mash_stalled:
                # In battle A advances text; allow released frames for a stalled line.
                return S1Turn(
                    [GameAction.PRESS_A, GameAction.WAIT_60], "battle text held; A", "page"
                )
            return S1Turn([GameAction.SKIP_DIALOG], "battle text; skip_dialog", "page")
        return None
    trainer = (obs.battle or {}).get("type") == "trainer"
    if screen.kind == "menu" and trainer and not battle_plan:
        # A trainer battle cannot be fled and a faint is death: System 2 plans it once.
        return _look("trainer battle")
    if screen.kind == "menu":
        questions = battle.menu_questions(obs, battle_plan)
    else:
        questions = battle.move_questions(obs, screen.options, known, battle_plan)
    criteria = questions["action"]["criteria"]
    forced = forced_battle_choice(obs, first_encounter) if screen.kind == "menu" else None
    if forced == "item":
        # System 3: the area's first encounter. ITEM, then the Poké Ball row in the bag.
        return S1Turn(
            battle.actions_for(screen, "item"),
            "System 3: first encounter here; throw a POKé BALL",
            "battle",
            choice="item",
        )
    if forced in criteria:
        if forced == "pkmn":
            reason = "reserve experience headroom; use a suitable alternative"
        elif obs.policy.get("duplicate_encounter"):
            reason = "duplicate encounter"
        elif obs.policy.get("avoid_wild_grinding") and not first_encounter:
            reason = "not an eligible catch; avoid wild grinding"
        else:
            reason = "active Pokémon HP below a quarter"
        return S1Turn(
            battle.actions_for(screen, forced),
            f"System 3: {criteria[forced]} ({reason})",
            "battle",
            choice=forced,
        )
    planned = None
    if screen.kind == "moves" and (battle_plan or {}).get("opening_moves"):
        name = battle_plan["opening_moves"][0].upper()
        planned = next(
            (
                f"move_{i}"
                for i, m in enumerate(screen.options)
                if m.upper() == name and battle._pp(obs).get(name, 1)
            ),
            None,
        )
    elif screen.kind == "menu" and (battle_plan or {}).get("switch_to"):
        lead = battle.active_mon(obs)
        if lead.get("hp", 0) / (lead.get("max_hp") or 1) < battle_plan.get("switch_below", 0):
            planned = "pkmn" if "pkmn" in criteria else None
    if planned in criteria:
        return S1Turn(
            battle.actions_for(screen, planned),
            "execute System 2's conditional plan",
            "battle",
            choice=planned,
        )
    state = {"battle": battle_facts(obs), "constraints": constraints, "recent": journal[-4:]}
    read = _ask(jev_decide, state, questions)
    if accepts(read, confidence_floor) and read is not None and read.action in criteria:
        choice, probability = read.action, read.probabilities.get(read.action)
    else:
        choice, probability = battle.fallback(screen, obs), None
    return S1Turn(
        battle.actions_for(screen, choice),
        f"battle {screen.kind}: {criteria.get(choice, choice)}",
        "battle",
        choice=choice,
        probability=probability,
    )


def _battle_menu(
    screen: ScreenText,
    first_encounter: bool,
    journal: list[str],
    confidence_floor: float,
    jev_decide: Decide,
    obs: PlayerObservation | None = None,
    plan: dict | None = None,
) -> S1Turn:
    """A ▶ menu in battle other than FIGHT/PKMN/ITEM/RUN and the moves: the bag, a YES/NO."""
    rows = [row.upper() for row in screen.menu_rows]
    if first_encounter and any("BALL" in row for row in rows):
        index = next(i for i, row in enumerate(rows) if "BALL" in row)
        return S1Turn(
            menu_actions(f"choose_{index}", screen.cursor_row),
            "System 3: throw the POKé BALL",
            "battle",
            choice=f"choose_{index}",
        )
    if obs:
        desired = str((plan or {}).get("switch_to") or "").upper()
        from nuzlocke.agents.level_buffer import switch_order

        eligible = switch_order(obs, desired)
        for slot, mon in eligible:
            index = next(
                (
                    i
                    for i, row in enumerate(rows)
                    if any(
                        n and str(n).upper() in row
                        for n in (mon.get("species"), mon.get("nickname"))
                    )
                ),
                None,
            )
            if index is not None:
                return S1Turn(
                    menu_actions(f"choose_{index}", screen.cursor_row),
                    f"switch to party slot {slot}",
                    "battle",
                )
        if "SWITCH" in rows or "SEND OUT" in rows:
            label = "SWITCH" if "SWITCH" in rows else "SEND OUT"
            return S1Turn(
                menu_actions(f"choose_{rows.index(label)}", screen.cursor_row),
                "confirm switch",
                "battle",
            )
    if "CANCEL" in rows and any("×" in row for row in rows) and not first_encounter:
        # No items in this Nuzlocke: an open bag is closed.
        index = rows.index("CANCEL")
        return S1Turn(menu_actions(f"choose_{index}", screen.cursor_row), "bag: CANCEL", "battle")
    goal = "In battle: keep the team strong; learn damaging moves, never give up the best one."
    return _menu_turn(screen, goal, journal, 0, confidence_floor, jev_decide)


def _special_page(rows: list[str]) -> S1Turn | None:
    """Text boxes that B does not page: the level-up stats box, and an evolution."""
    text = " ".join(rows)
    if "ATTACK" in text and "SPECIAL" in text and "DEFENSE" in text:
        # "grew to level N!" puts a stats box over the text; B left it up for 70 cycles in
        # run 20260929-095253-004c14 until the stuck ladder took over. A closes it.
        return S1Turn([GameAction.PRESS_A, GameAction.WAIT_60], "level-up stats; A", "page")
    from nuzlocke.environment.evolution import evolution_phase

    phase = evolution_phase(rows)
    if phase == "result":
        return S1Turn([GameAction.PRESS_A, GameAction.WAIT_60], "evolution result; A", "page")
    if phase == "animation":
        # B cancels an evolution (pitfall #17). It needs no input; let it play.
        return S1Turn([GameAction.WAIT_60, GameAction.WAIT_60], "evolving; wait, never B", "page")
    return None


def _menu_turn(
    screen: ScreenText,
    goal_text: str | None,
    journal: list[str],
    low_confidence_streak: int,
    confidence_floor: float,
    jev_decide: Decide,
) -> S1Turn:
    rows, cursor = screen.menu_rows, screen.cursor_row
    yes_no = [row.upper() for row in rows] == ["YES", "NO"]
    if yes_no and "nickname" in " ".join(screen.text_lines).lower():
        # System 3: catches keep their species name.
        return S1Turn(menu_actions("choose_1", cursor), "nickname: NO", "menu", choice="choose_1")
    questions = menu_questions(
        rows, cursor, yes_no=yes_no, goal=goal_text, can_back=screen.menu_title != "NAME"
    )
    state = {"goal": goal_text, **screen.as_state(), "recent": journal[-4:]}
    read = _ask(jev_decide, state, questions)
    if not accepts(read, confidence_floor):
        streak = low_confidence_streak + 1
        if streak >= 2 or yes_no:
            # A wrong YES/NO or name is not undone by the next cycle.
            return _look("jev unsure at a menu")
        return S1Turn(
            [GameAction.WAIT_60],
            "jev unsure at a menu; wait and ask again",
            "menu",
            low_confidence_streak=streak,
        )
    assert read is not None
    label = questions["action"]["criteria"].get(read.action, read.action)
    return S1Turn(
        menu_actions(read.action, cursor),
        f"menu: {label} (p {read.confidence:.2f})",
        "menu",
        choice=read.action,
        probability=read.probabilities.get(read.action),
    )


def menu_questions(
    rows: list[str],
    cursor: int | None,
    *,
    yes_no: bool,
    goal: str | None = None,
    can_back: bool = True,
) -> dict[str, Any]:
    """One option per menu row; a row the goal names says so."""
    criteria = {}
    wanted = (goal or "").casefold()
    for index, row in enumerate(rows):
        notes = ["highlighted now"] if index == cursor else []
        name = row.split("¥")[0].strip()
        if name and name.casefold() in wanted:
            notes.insert(0, "the goal names this row")
        criteria[f"choose_{index}"] = f"choose {row}" + (f" ({'; '.join(notes)})" if notes else "")
    if can_back:
        criteria["back"] = (
            "press B: answers NO at a YES/NO" if yes_no else "press B to back out of this menu"
        )
    return {
        "action": {
            "type": "choice",
            "instructions": (
                "A menu is open. `text` is the question, `menu` the rows. Pick the row that "
                "carries out `goal`. For a name, pick a preset name, not NEW NAME."
            ),
            "criteria": criteria,
        }
    }


def menu_actions(choice: str, cursor: int | None) -> list[GameAction]:
    """Move the highlight to the chosen row and press A, or press B."""
    if choice == "back":
        return [GameAction.PRESS_B]
    moves = int(choice.removeprefix("choose_")) - (cursor or 0)
    step = GameAction.WALK_DOWN if moves > 0 else GameAction.WALK_UP
    return [step] * abs(moves) + [GameAction.PRESS_A]
