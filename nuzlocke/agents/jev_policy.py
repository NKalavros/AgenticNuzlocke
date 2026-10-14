"""The fallback fast path: battle, the naming keyboard, and steps System 2 wrote.

System 1 (``agents.system1``) handles the overworld, menus, and text. What it
hands back comes here: page text, press the planner's steps, or ask Jev for one
button from a fixed menu, with a replan gate for when the card is stale.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from itertools import takewhile
from typing import Any

from nuzlocke.assets import data
from nuzlocke.environment.screen_text import is_naming_screen, parse_screen
from nuzlocke.llm.jev import JevAnswers, JevDecisionError
from nuzlocke.referee.type_chart import matchup_hint, types_for_species
from nuzlocke.state.models import (
    AgentRole,
    GameAction,
    LandmarkNote,
    ObjectivesUpdate,
    PlanCard,
    PlanScene,
    PlayerObservation,
    RecoveryAdvice,
)

# Text-driven screens: the card holds while their text box is up.
_HELD_SCENES = (PlanScene.DIALOG, PlanScene.TITLE)
# Scenes whose text box is narration, paged with B rather than answered.
_PAGED_SCENES = (PlanScene.DIALOG.value, PlanScene.TITLE.value, PlanScene.OVERWORLD.value)
# The emulator only advances inside /action. A menu confirm is one press; this
# wait lets the next line finish printing before the following look.
_PAGE_WAIT = GameAction.WAIT_60


@dataclass(frozen=True)
class FrameSignals:
    """Pixel digests for the frame the fast actor is about to act on."""

    world_digest: str
    dialog_digest: str
    world_changed: bool
    dialog_changed: bool
    # Narrative box is on screen. Sprite animation above it is not a new scene.
    text_box: bool = False
    # A menu box (YES/NO, a name list) above that text box. B would answer it.
    prompt_box: bool = False


@dataclass
class FastTurn:
    actions: list[GameAction]
    reason: str
    plan: PlanCard
    low_confidence_streak: int
    replanned: bool
    agent: AgentRole = AgentRole.OVERWORLD
    objectives: ObjectivesUpdate | None = None
    landmarks: list[LandmarkNote] = field(default_factory=list)
    # Why each planner look this cycle happened, in order.
    looks: list[str] = field(default_factory=list)


def classify_scene(obs: PlayerObservation, plan: PlanCard | None, signals: FrameSignals) -> str:
    """Menu to show Jev. Hard signals win; a held dialog plan survives text animation."""
    if is_naming_screen(obs.screen_rows):
        return PlanScene.NAMING.value
    if obs.in_battle:
        return PlanScene.BATTLE.value
    if parse_screen(obs.screen_rows).cursor_row is not None:
        return PlanScene.MENU.value
    if plan is not None:
        same_world = signals.world_digest == plan.world_digest
        if plan.scene in _HELD_SCENES and signals.text_box:
            # The picture above the box moves while text is up. Stay on this card.
            return plan.scene.value
        if plan.scene == PlanScene.MENU and (same_world or not signals.dialog_changed):
            # The highlight moving changes the world digest. That is still the menu.
            return PlanScene.MENU.value
        if plan.scene == PlanScene.TITLE and plan.world_digest and same_world:
            return PlanScene.TITLE.value
    # A box that just closed changes the text rows and not the world above
    # them. That is the overworld again, so a planned path is one burst.
    if signals.text_box and signals.dialog_changed and not signals.world_changed:
        return PlanScene.DIALOG.value
    return PlanScene.OVERWORLD.value


def scene_changed(plan: PlanCard, obs: PlayerObservation, signals: FrameSignals) -> bool:
    """Naming, battle, or walking out of a menu, dialog, or title plan."""
    if is_naming_screen(obs.screen_rows) != (plan.scene == PlanScene.NAMING):
        return True
    if bool(obs.in_battle) != (plan.scene == PlanScene.BATTLE):
        return True
    if plan.scene == PlanScene.MENU:
        return signals.world_digest != plan.world_digest and signals.dialog_changed
    if plan.scene not in _HELD_SCENES or signals.text_box:
        return False
    # The box this card was written against has closed, or the picture
    # above a box-less screen (the title splash) actually changed.
    return plan.text_box or signals.world_digest != plan.world_digest


def replan_reason(
    plan: PlanCard | None,
    obs: PlayerObservation,
    signals: FrameSignals,
    *,
    now: float,
    plan_every_s: float,
    force: bool | str = False,
) -> str | None:
    """Why the planner should look at this frame, or None. A string ``force`` is its reason."""
    if force:
        return force if isinstance(force, str) else "forced"
    if plan is None:
        return "no plan"
    if plan.spent:
        return "plan spent"
    if signals.prompt_box and plan.prompt_digest != signals.dialog_digest:
        # B answers a YES/NO, so a prompt this card was not written against is read first.
        return "new prompt"
    if scene_changed(plan, obs, signals):
        return "scene changed"
    age = now - plan.created_at
    if plan_every_s > 0 and age >= plan_every_s:
        return "plan old"
    return None


def pages_without_a_look(plan: PlanCard, obs: PlayerObservation, signals: FrameSignals) -> bool:
    """Narrative text is paged with B before any look.

    A menu's own text box is not: the party list draws one, and B there leaves
    the menu. A box after an answered YES/NO is speech again. Battle narration
    is paged too: the FIGHT menu and the move list do not read as a text box,
    so the mash stops at them.
    """
    if not signals.text_box or signals.prompt_box or is_naming_screen(obs.screen_rows):
        return False
    return plan.scene != PlanScene.MENU or bool(plan.prompt_digest)


def reconcile_plan(plan: PlanCard, obs: PlayerObservation) -> PlanCard:
    """Recognize the visible naming grid, battle, and active menus without another vision call."""
    if is_naming_screen(obs.screen_rows):
        plan.scene = PlanScene.NAMING
    elif obs.in_battle:
        plan.scene = PlanScene.BATTLE
    elif parse_screen(obs.screen_rows).cursor_row is not None:
        plan.scene = PlanScene.MENU
    return plan


def action_menu(scene: str, blocked_on_tile: list[str] | None = None) -> dict[str, str]:
    """Choice criteria keyed by ``GameAction`` value. Walks that failed on this tile are left out."""
    menu = dict(_MENUS.get(scene, _MENUS[PlanScene.OVERWORLD.value]))
    if scene == PlanScene.OVERWORLD.value:
        for label in blocked_on_tile or []:
            menu.pop(label, None)
    return menu


def safe_action(scene: str) -> GameAction:
    """What to press when Jev is unsure. B-side, except on the naming grid."""
    if scene == PlanScene.DIALOG.value:
        return GameAction.SKIP_DIALOG
    if scene == PlanScene.MENU.value:
        # Backing out with B reopens the same list. Confirm the highlight.
        return GameAction.PRESS_A
    if scene == PlanScene.NAMING.value:
        # B on the letter grid deletes a glyph. Waiting is the safe press.
        return GameAction.WAIT_60
    return GameAction.PRESS_B


def _recent_lines(recent: list[dict[str, Any]] | None, keep: int) -> list[str]:
    """Oldest first, one ``actions -> outcome`` line each."""
    lines = []
    for item in (recent or [])[-keep:]:
        actions = ",".join(str(action) for action in item.get("actions") or []) or "-"
        lines.append(f"{actions} -> {item.get('outcome') or 'ok'}")
    return lines


def battle_facts(obs: PlayerObservation) -> dict[str, Any] | None:
    """The two mons on the field, their HP, and the type matchup from the type chart."""
    enemy = (obs.battle or {}).get("enemy") or {}
    from nuzlocke.agents.battle import active_mon
    from nuzlocke.environment.status import normalize_status

    lead = active_mon(obs)
    if not enemy and not lead:
        return None
    facts: dict[str, Any] = {}
    for side, mon in (("enemy", enemy), ("ours", lead)):
        if mon:
            facts[side] = {
                "species": mon.get("species"),
                "level": mon.get("level"),
                "hp": f"{mon.get('hp')}/{mon.get('max_hp')}",
                "types": list(types_for_species(str(mon.get("species") or ""))),
                "status": normalize_status(mon.get("status")),
            }
    if lead:
        facts["ours"]["moves"] = [
            f"{move.get('name')} (pp {move.get('pp')})" for move in lead.get("moves") or [] if isinstance(move, dict)
        ]
    if enemy and lead:
        facts["our_types_vs_enemy"] = matchup_hint(
            list(types_for_species(str(lead.get("species") or ""))), list(types_for_species(str(enemy.get("species") or "")))
        )
    return facts


def build_jev_state(
    *,
    plan: PlanCard,
    scene: str,
    obs: PlayerObservation,
    signals: FrameSignals,
    recent: list[dict[str, Any]] | None = None,
    objectives: dict[str, str] | None = None,
    no_progress: dict[str, Any] | None = None,
    beat: str | None = None,
    **_planner_only: Any,
) -> dict[str, Any]:
    """Only what this scene's button choice needs. Memory and bookkeeping stay with the planner."""
    naming = is_naming_screen(obs.screen_rows)
    state: dict[str, Any] = {
        "plan": {"scene": plan.scene.value, "see": plan.see, "plan": plan.plan, "do_not": list(plan.do_not)},
        "scene": scene,
        "signals": {
            "world_changed": signals.world_changed,
            "text_region_changed": signals.dialog_changed,
            "world_unchanged_since_plan": signals.world_digest == plan.world_digest,
        },
    }
    overworld = scene == PlanScene.OVERWORLD.value
    battle = scene == PlanScene.BATTLE.value
    goal = beat or (objectives or {}).get("primary")
    optional: dict[str, Any] = {
        "goal": goal if overworld else None,
        "recent": _recent_lines(recent, 4 if overworld or battle else 2),
    }
    if battle:
        optional["battle"] = battle_facts(obs)
    state.update({key: value for key, value in optional.items() if value})
    if naming:
        state["hard_signal"] = (
            "The visible letter grid is the NAMING KEYBOARD. On the "
            "keyboard walk_* moves the letter cursor and press_a types; on a "
            "Pokédex page press_a turns the page. Never skip_dialog."
        )
    elif scene == PlanScene.MENU.value:
        state["hard_signal"] = (
            "A menu is open. walk_up and walk_down move the highlight, "
            "not the player. press_a confirms that row. press_b backs out."
        )
    return state


_INSTRUCTIONS = data("prompts/fast_instructions.json")
# Scenes where the plan's goal can go stale or finish under Jev.
_JUDGED_SCENES = (PlanScene.OVERWORLD.value, PlanScene.DIALOG.value)


def build_jev_questions(menu: dict[str, str], scene: str = PlanScene.OVERWORLD.value) -> dict[str, Any]:
    questions: dict[str, Any] = {
        "action": {
            "type": "choice",
            "instructions": _INSTRUCTIONS.get(scene, _INSTRUCTIONS[PlanScene.OVERWORLD.value]),
            "criteria": menu,
        }
    }
    if scene not in _JUDGED_SCENES:
        return questions
    questions.update(data("prompts/fast_questions.json"))
    return questions


def plan_from_recovery(advice: RecoveryAdvice, *, scene: str, world_digest: str, now: float) -> PlanCard:
    """Recovery still presses the buttons this cycle; Jev follows the text after that."""
    try:
        parsed = PlanScene(scene)
    except ValueError:
        parsed = PlanScene.OVERWORLD
    text = (advice.reason or advice.diagnosis or "Leave this tile.").strip()
    return PlanCard(
        scene=parsed,
        see=(advice.diagnosis or "stuck").strip()[:300],
        plan=text[:500],
        objectives=advice.objectives,
        landmarks=list(advice.landmarks),
        world_digest=world_digest,
        created_at=now,
    )


def choose_fast_action(
    *,
    plan: PlanCard | None,
    obs: PlayerObservation,
    signals: FrameSignals,
    now: float,
    plan_every_s: float,
    stale_noul: float,
    confidence_floor: float,
    low_confidence_streak: int,
    force_replan: bool | str = False,
    recent: list[dict[str, Any]] | None = None,
    objectives: dict[str, str] | None = None,
    blocked_on_tile: list[str] | None = None,
    beat: str | None = None,
    mash_stalled: bool = False,
    jev_decide: Callable[[dict[str, Any], dict[str, Any]], JevAnswers],
    refresh_plan: Callable[[], PlanCard],
    **_planner_only: Any,
) -> FastTurn:
    """One prompt cycle: maybe refresh the plan, then press a path or one button.

    Narrative text is mashed before any look, unless the last mash left the box
    unchanged (``mash_stalled``); then the plan's buttons decide. Jev is asked
    only when neither decides the press. A stale or finished plan is refreshed
    once before that. A second consecutive low-confidence answer also refreshes
    once; otherwise the unsure cycle presses a safe B-side action and does not
    spend a vision call. A string ``force_replan`` is logged as the reason.
    """
    replanned = False
    looks: list[str] = []
    blocked = set(blocked_on_tile or [])

    def finish(
        actions: GameAction | list[GameAction], reason: str, *, spent: bool = False, agent: AgentRole | None = None, streak: int = 0
    ) -> FastTurn:
        if spent:
            plan.spent = True
        if agent is None:
            # The director gives a battle to the battle agent; the arbiter
            # rejects anyone else's buttons.
            agent = AgentRole.BATTLE if obs.in_battle else AgentRole.OVERWORLD
        return FastTurn(
            actions=actions if isinstance(actions, list) else [actions],
            reason=reason,
            plan=plan,
            low_confidence_streak=streak,
            replanned=replanned,
            agent=agent,
            objectives=plan.objectives if replanned else None,
            landmarks=list(plan.landmarks) if replanned else [],
            looks=looks,
        )

    def pull(why: str) -> None:
        nonlocal plan, replanned
        looks.append(why)
        plan = reconcile_plan(refresh_plan(), obs)
        replanned = True

    def mash() -> FastTurn:
        # No walk is pressed while the box is up — the game ignores the D-pad
        # until it closes.
        plan.steps.clear()
        plan.scene = PlanScene.DIALOG
        plan.text_box = True
        return finish(GameAction.SKIP_DIALOG, "speech on screen; skip_dialog")

    def ask(current_scene: str) -> JevAnswers:
        menu = action_menu(current_scene, blocked_on_tile)
        state = build_jev_state(
            plan=plan, scene=current_scene, obs=obs, signals=signals, recent=recent, objectives=objectives, beat=beat
        )
        try:
            return jev_decide(state, build_jev_questions(menu, current_scene))
        except JevDecisionError:
            return JevAnswers(action="", confidence=0.0, plan_stale=0.0, objective_done=0.0, model="")

    if plan is not None and not force_replan and not mash_stalled and pages_without_a_look(plan, obs, signals):
        # A box that just opened is paged first; the look waits until it closes.
        return mash()
    why = replan_reason(plan, obs, signals, now=now, plan_every_s=plan_every_s, force=force_replan)
    if why is not None:
        pull(why)
    assert plan is not None

    scene = classify_scene(obs, plan, signals)
    if signals.prompt_box and scene in _PAGED_SCENES:
        # A YES/NO or a name list is answered, never paged.
        scene = PlanScene.MENU.value
    if signals.text_box and not mash_stalled and scene in _PAGED_SCENES:
        return mash()

    if plan.steps and scene != PlanScene.OVERWORLD.value:
        # A menu or the naming grid takes one button a cycle: those walks move a cursor.
        step = plan.steps.pop(0)
        left = len(plan.steps)
        paged = signals.text_box and step in (GameAction.PRESS_A, GameAction.PRESS_B)
        return finish(
            [step, _PAGE_WAIT] if paged else step,
            f"planned step {step.value}" + (f" ({left} left)" if left else " (last)"),
            spent=left == 0,
        )
    if plan.steps and signals.text_box != plan.text_box:
        # A text box opened or closed under the path.
        plan.steps.clear()
    elif plan.steps:
        # One burst, cut before a walk that already failed on this tile.
        path = list(takewhile(lambda step: step.value not in blocked, plan.steps))
        plan.steps.clear()
        plan.spent = True
        if path:
            return finish(path, "planned path " + ", ".join(step.value for step in path))

    named = _named_press(plan) if scene == PlanScene.NAMING.value else None
    if named is not None:
        return finish(named, f"naming grid; {named.value} once", spent=True, agent=AgentRole.OVERWORLD)
    read = ask(scene)
    if not replanned and (read.plan_stale >= stale_noul or read.objective_done >= stale_noul):
        pull("jev: plan stale or done")
        scene = classify_scene(obs, plan, signals)
        read = ask(scene)

    streak = 0
    if not accepts(read, confidence_floor):
        streak = low_confidence_streak + 1
        if streak >= 2 and not replanned:
            pull("low confidence twice")
            scene = classify_scene(obs, plan, signals)
            read = ask(scene)
            streak = 0
    if accepts(read, confidence_floor):
        action = GameAction(read.action)
        brief = " ".join(plan.plan.split())[:80]
        reason = f"{getattr(read, 'provider', 'jev')} {read.action}{confidence_note(read)} following: {brief}"
    else:
        action = safe_action(scene)
        reason = f"actor unsure{confidence_note(read)}; safe action"
    agent = AgentRole.BATTLE if scene == PlanScene.BATTLE.value else AgentRole.OVERWORLD
    return finish(action, reason, spent=scene == PlanScene.NAMING.value, agent=agent, streak=streak)


def _named_press(plan: PlanCard) -> GameAction | None:
    """The first button a naming plan asked for, if it named one."""
    text = plan.plan.lower()
    presses = (
        ("press down", GameAction.WALK_DOWN),
        ("press up", GameAction.WALK_UP),
        ("press left", GameAction.WALK_LEFT),
        ("press right", GameAction.WALK_RIGHT),
        ("press start", GameAction.PRESS_START),
        ("press a", GameAction.PRESS_A),
        ("press b", GameAction.PRESS_B),
    )
    return next((action for label, action in presses if label in text), None)


# The top option leads the runner-up by this much. TypeSafe's confidence is the spread over
# every option, so a clear 0.66 / 0.29 pick on a three-row menu scores only 0.48.
MIN_MARGIN = 0.25


def confidence_note(read: JevAnswers) -> str:
    if getattr(read, "decision_mode", "probabilities") == "choice":
        return ""
    return f" (conf {read.confidence:.2f})"


def accepts(read: JevAnswers | None, floor: float) -> bool:
    """Accept a validated API choice, or Jev's confidence/margin-qualified pick."""
    if read is None or not read.action:
        return False
    if getattr(read, "decision_mode", "probabilities") == "choice":
        return not read.abstain
    ranked = sorted(read.probabilities.values(), reverse=True)
    margin = ranked[0] - ranked[1] if len(ranked) > 1 else 0.0
    return read.confidence >= floor or margin >= MIN_MARGIN


_MENUS = data("prompts/fast_menus.json")
