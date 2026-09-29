"""Legal menus and replan gates for the Jev fast actor.

Jev picks one key from a menu this module builds. It never invents buttons,
and it never sees the screenshot — the planner's text card is the perception.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from itertools import takewhile
from typing import Any

from nuzlocke.agents.locomotion import heading_run, neighbors_from_ascii, next_tile
from nuzlocke.agents.targets import Target, build_targets, facing_target
from nuzlocke.environment.joypad import is_naming_lock
from nuzlocke.llm.jev import JevAnswers, JevDecisionError
from nuzlocke.orchestration.stuck import _phrase_affirmed, perpendicular_sidestep
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
_TILE_LOOK_CYCLES = 6
_TILE_LOOK_MIN_S = 8.0


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
    if is_naming_lock(obs.joy_ignore):
        return PlanScene.NAMING.value
    if obs.in_battle:
        return PlanScene.BATTLE.value
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
    if is_naming_lock(obs.joy_ignore) != (plan.scene == PlanScene.NAMING):
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
    same_tile_streak: int = 0,
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
    if (
        plan.scene == PlanScene.OVERWORLD
        and same_tile_streak >= _TILE_LOOK_CYCLES
        and age >= _TILE_LOOK_MIN_S
    ):
        return "same tile"
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
    if not signals.text_box or signals.prompt_box or is_naming_lock(obs.joy_ignore):
        return False
    return plan.scene != PlanScene.MENU or bool(plan.prompt_digest)


def reconcile_plan(plan: PlanCard, obs: PlayerObservation) -> PlanCard:
    """Naming lock and battle are mechanical. Don't spend another vision call to notice them."""
    if is_naming_lock(obs.joy_ignore):
        plan.scene = PlanScene.NAMING
    elif obs.in_battle:
        plan.scene = PlanScene.BATTLE
    return plan


def action_menu(
    scene: str,
    blocked_on_tile: list[str] | None = None,
    *,
    obs: PlayerObservation | None = None,
    targets: list[Target] | None = None,
    press_counts: dict[str, int] | None = None,
    heading: str | None = None,
) -> dict[str, str]:
    """Choice criteria keyed by ``GameAction`` value, with this cycle's facts on each option.

    Jev cannot combine a grid, a target list, and a press history across the
    state, so each overworld option says what pressing it leads to. Only this
    tile's ``blocked_on_tile`` is removed; a walk that failed elsewhere stays.
    """
    menu = dict(_MENUS.get(scene, _MENUS[PlanScene.OVERWORLD.value]))
    if scene != PlanScene.OVERWORLD.value:
        return menu
    for label in blocked_on_tile or []:
        menu.pop(label, None)
    if obs is None:
        return menu
    tiles = neighbors_from_ascii(obs.collision_ascii)
    counts = press_counts or {}
    for label in list(menu):
        facts: list[str] = [menu[label]]
        if label.startswith("walk_"):
            direction = label.removeprefix("walk_")
            if direction in tiles:
                facts.append("open tile" if tiles[direction] else "grid shows a wall there")
            toward = [t for t in targets or [] if t.first_step == direction]
            for target in toward[:2]:
                steps = target.path_len or target.distance
                facts.append(f"first step toward {target.label} ({steps} tiles)")
            if heading == direction:
                facts.append("the story heading")
        elif label == GameAction.PRESS_A.value and targets is not None:
            front = facing_target(obs, targets)
            facts.append(f"talks to the {front.label} in front" if front else "nothing in front")
        if counts.get(label):
            facts.append(f"already pressed {counts[label]}x on this tile with no move")
        menu[label] = "; ".join(facts)
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


def _battle_facts(obs: PlayerObservation) -> dict[str, Any] | None:
    """The two mons on the field, their HP, and the type matchup from the type chart."""
    enemy = (obs.battle or {}).get("enemy") or {}
    lead = obs.party[0] if obs.party else {}
    if not enemy and not lead:
        return None
    facts: dict[str, Any] = {}
    if enemy:
        facts["enemy"] = {
            "species": enemy.get("species"),
            "level": enemy.get("level"),
            "hp": f"{enemy.get('hp')}/{enemy.get('max_hp')}",
            "types": list(types_for_species(str(enemy.get("species") or ""))),
        }
    if lead:
        facts["ours"] = {
            "species": lead.get("species"),
            "level": lead.get("level"),
            "hp": f"{lead.get('hp')}/{lead.get('max_hp')}",
            "types": list(lead.get("types") or []),
            "moves": [
                f"{move.get('name')} (pp {move.get('pp')})"
                for move in lead.get("moves") or []
                if isinstance(move, dict)
            ],
        }
    if enemy and lead:
        facts["our_types_vs_enemy"] = matchup_hint(
            list(lead.get("types") or []), list(types_for_species(str(enemy.get("species") or "")))
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
    blocked_on_tile: list[str] | None = None,
    beat: str | None = None,
    targets: list[Target] | None = None,
    **_planner_only: Any,
) -> dict[str, Any]:
    """Only what this scene's button choice needs. Memory and bookkeeping stay with the planner."""
    naming = is_naming_lock(obs.joy_ignore)
    state: dict[str, Any] = {
        "plan": {
            "scene": plan.scene.value,
            "see": plan.see,
            "plan": plan.plan,
            "do_not": list(plan.do_not),
        },
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
    if overworld:
        where: dict[str, Any] = {"map": obs.map_name, "x": obs.x, "y": obs.y}
        if obs.facing:
            where["facing"] = obs.facing
        if (obs.collision_ascii or "").strip():
            where["grid"] = obs.collision_ascii.strip()
        optional["where"] = where
        optional["targets"] = [target.as_state() for target in targets or []]
        optional["blocked_on_tile"] = list(blocked_on_tile or [])
        if no_progress and no_progress.get("streak"):
            optional["no_progress"] = no_progress
    if battle:
        optional["battle"] = _battle_facts(obs)
    state.update({key: value for key, value in optional.items() if value})
    if naming:
        state["hard_signal"] = (
            "Instant-text mode: the NAMING KEYBOARD or a Pokédex page. On the "
            "keyboard walk_* moves the letter cursor and press_a types; on a "
            "Pokédex page press_a turns the page. Never skip_dialog."
        )
    elif scene == PlanScene.MENU.value:
        state["hard_signal"] = (
            "A menu is open. walk_up and walk_down move the highlight, "
            "not the player. press_a confirms that row. press_b backs out."
        )
    return state


_INSTRUCTIONS = {
    PlanScene.OVERWORLD.value: (
        "Pick the button that carries out `plan`. Each option lists what pressing it "
        "leads to: the grid tile that way, the first step toward each target, and "
        "presses already spent here. `where.grid` is the walk grid, @ the player, "
        ". open, # blocked (a door mat or stairs also reads #). Prefer the first step "
        "toward the planner target or the goal. Avoid an option already pressed here "
        "with no move."
    ),
    PlanScene.BATTLE.value: (
        "Pick the button that carries out `plan` in this battle. walk_* move the cursor "
        "on FIGHT / PKMN / ITEM / RUN or the move list, press_a confirms the highlight, "
        "skip_dialog pages battle text."
    ),
    PlanScene.MENU.value: (
        "Move the highlight to the row `plan` names, then press_a. press_b backs out."
    ),
    PlanScene.NAMING.value: (
        "Follow `plan` on the letter grid: walks move the cursor, press_a types the letter."
    ),
    PlanScene.DIALOG.value: "Page the text unless `plan` says to answer something.",
    PlanScene.TITLE.value: "Get past the title and intro screens the way `plan` says.",
}
# Scenes where the plan's goal can go stale or finish under Jev.
_JUDGED_SCENES = (PlanScene.OVERWORLD.value, PlanScene.DIALOG.value)


def build_jev_questions(
    menu: dict[str, str], scene: str = PlanScene.OVERWORLD.value
) -> dict[str, Any]:
    questions: dict[str, Any] = {
        "action": {
            "type": "choice",
            "instructions": _INSTRUCTIONS.get(scene, _INSTRUCTIONS[PlanScene.OVERWORLD.value]),
            "criteria": menu,
        }
    }
    if scene not in _JUDGED_SCENES:
        return questions
    questions["plan_stale"] = {
        "type": "noul",
        "instructions": "Recent outcomes show this plan is no longer the right thing to follow.",
        "criteria": {
            "true": "The plan no longer matches what is happening",
            "false": "The plan still fits the recent outcomes",
        },
    }
    questions["objective_done"] = {
        "type": "noul",
        "instructions": "The plan's objective is already complete.",
        "criteria": {
            "true": "The goal in the plan has already been achieved",
            "false": "The goal is still ahead",
        },
    }
    return questions


def plan_from_recovery(
    advice: RecoveryAdvice, *, scene: str, world_digest: str, now: float
) -> PlanCard:
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
    failed_approaches: list[list[str]] | None = None,
    memory: str | None = None,
    recent: list[dict[str, Any]] | None = None,
    objectives: dict[str, str] | None = None,
    nuzlocke: dict[str, Any] | None = None,
    no_progress: dict[str, Any] | None = None,
    same_tile_streak: int = 0,
    blocked_on_tile: list[str] | None = None,
    beat: str | None = None,
    heading: str | None = None,
    mash_stalled: bool = False,
    press_counts: dict[str, int] | None = None,
    jev_decide: Callable[[dict[str, Any], dict[str, Any]], JevAnswers],
    refresh_plan: Callable[[], PlanCard],
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
        actions: GameAction | list[GameAction],
        reason: str,
        *,
        spent: bool = False,
        agent: AgentRole | None = None,
        streak: int = 0,
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
        targets = (
            build_targets(obs, plan_target=plan.target)
            if current_scene == PlanScene.OVERWORLD.value
            else []
        )
        menu = action_menu(
            current_scene,
            blocked_on_tile,
            obs=obs,
            targets=targets,
            press_counts=press_counts,
            heading=heading,
        )
        state = build_jev_state(
            plan=plan,
            scene=current_scene,
            obs=obs,
            signals=signals,
            recent=recent,
            objectives=objectives,
            no_progress=no_progress,
            blocked_on_tile=blocked_on_tile,
            beat=beat,
            targets=targets,
        )
        try:
            return jev_decide(state, build_jev_questions(menu, current_scene))
        except JevDecisionError:
            return JevAnswers(
                action="", confidence=0.0, plan_stale=0.0, objective_done=0.0, model=""
            )

    def overworld_press(current_scene: str) -> FastTurn | None:
        """The plan's named button or the beat heading, pressed in code, never replaced with B.

        The heading is held as a run of open tiles only when the plan does not
        name a different walk. A named button or a sidestep is one press, then
        another look: holding it walks off the map.
        """
        if current_scene != PlanScene.OVERWORLD.value:
            return None
        grid = obs.collision_ascii
        named = named_overworld_action(plan.plan)
        if named == GameAction.PRESS_A:
            return finish(named, "plan named press_a", spent=True)
        is_walk = named is not None and named.value.startswith("walk_")
        if is_walk:
            direction = named.value.removeprefix("walk_")
            if named.value not in blocked:
                if direction != heading:
                    return finish(named, f"plan {named.value}", spent=True)
                run = heading_run(heading, grid, blocked)
                if run is not None:
                    return finish(run, f"heading {run.value}")
                # No grid: one tile, and keep holding. A grid that shows the
                # heading shut falls through to the sidestep.
                if not (grid or "").strip():
                    return finish(named, f"plan {named.value}")
            step = next_tile(heading=direction, grid=grid, blocked=blocked)
            if step is not None and step.action is not None:
                return finish(step.action, step.reason, spent=True)
            if step is not None and step.choices:
                return finish(step.choices[0], f"{direction} blocked; sidestep", spent=True)
        if heading:
            run = heading_run(heading, grid, blocked)
            if run is not None:
                return finish(run, f"heading {run.value}")
            step = next_tile(heading=heading, grid=grid, blocked=blocked)
            if step is None:
                return None
            if step.choices:
                return finish(step.choices[0], f"{heading} blocked; sidestep", spent=True)
            # A sidestep is one press. The heading itself is held.
            return finish(step.action, step.reason, spent=step.action.value != f"walk_{heading}")
        if named is None:
            return None
        if not is_walk:
            return finish(named, f"plan named {named.value}", spent=True)
        for alternate in (0, 1):
            side = perpendicular_sidestep([named.value], alternate=alternate)
            if side.value not in blocked:
                reason = f"plan named {named.value}, blocked on this tile; sidestep {side.value}"
                return finish(side, reason, spent=True)
        return None

    if (
        plan is not None
        and not force_replan
        and not mash_stalled
        and pages_without_a_look(plan, obs, signals)
    ):
        # A box that just opened is paged first; the look waits until it closes.
        return mash()
    why = replan_reason(
        plan,
        obs,
        signals,
        now=now,
        plan_every_s=plan_every_s,
        force=force_replan,
        same_tile_streak=same_tile_streak,
    )
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
        return finish(
            named, f"naming grid; {named.value} once", spent=True, agent=AgentRole.OVERWORLD
        )
    if turn := overworld_press(scene):
        return turn
    read = ask(scene)
    if not replanned and (read.plan_stale >= stale_noul or read.objective_done >= stale_noul):
        pull("jev: plan stale or done")
        scene = classify_scene(obs, plan, signals)
        if turn := overworld_press(scene):
            return turn
        read = ask(scene)

    streak = 0
    unsure = "jev low confidence"
    if not accepts(read, confidence_floor):
        streak = low_confidence_streak + 1
        if streak >= 2 and not replanned:
            pull("low confidence twice")
            scene = classify_scene(obs, plan, signals)
            read = ask(scene)
            streak = 0
            unsure = "jev still unsure after a new plan"
    if accepts(read, confidence_floor):
        action = GameAction(read.action)
        brief = " ".join(plan.plan.split())[:80]
        reason = f"jev {read.action} (conf {read.confidence:.2f}) following: {brief}"
    else:
        action = safe_action(scene)
        reason = f"{unsure} ({read.confidence:.2f}); safe action"
    # B does not travel. An unsure answer must not cancel the planned step.
    if action == GameAction.PRESS_B and not signals.text_box and (turn := overworld_press(scene)):
        return turn
    agent = AgentRole.BATTLE if scene == PlanScene.BATTLE.value else AgentRole.OVERWORLD
    return finish(action, reason, spent=scene == PlanScene.NAMING.value, agent=agent, streak=streak)


def named_overworld_action(text: str) -> GameAction | None:
    """The single overworld button named in a plan, if it named exactly one."""
    lowered = text.lower().replace("_", " ")
    buttons = (
        GameAction.WALK_UP,
        GameAction.WALK_DOWN,
        GameAction.WALK_LEFT,
        GameAction.WALK_RIGHT,
        GameAction.PRESS_A,
        GameAction.PRESS_B,
    )
    found = [
        button for button in buttons if _phrase_affirmed(lowered, button.value.replace("_", " "))
    ]
    return found[0] if len(found) == 1 else None


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


def accepts(read: JevAnswers, floor: float) -> bool:
    """Whether this answer is pressed as Jev's choice rather than the scene's safe action."""
    return read.confidence >= floor and read.action in GameAction


_PRESS_B = "cancel or back out; does not start a conversation"
_SKIP = "advance narrative text; B-only, does not press A"
_A = "confirm, talk, or interact with the tile in front"

_MENUS: dict[str, dict[str, str]] = {
    PlanScene.NAMING.value: {
        "walk_up": "move the letter cursor up",
        "walk_down": "move the letter cursor down",
        "walk_left": "move the letter cursor left",
        "walk_right": "move the letter cursor right",
        "press_a": "type the highlighted glyph, or confirm END",
    },
    PlanScene.BATTLE.value: {
        "press_a": "confirm the highlighted battle command or move",
        "press_b": "back out of a battle submenu",
        "walk_up": "move the battle cursor up",
        "walk_down": "move the battle cursor down",
        "walk_left": "move the battle cursor left",
        "walk_right": "move the battle cursor right",
        "skip_dialog": _SKIP,
        "wait_60": "wait one moment",
    },
    PlanScene.DIALOG.value: {"skip_dialog": _SKIP, "press_b": _PRESS_B},
    PlanScene.TITLE.value: {
        "press_start": "leave the title splash",
        "press_a": "confirm NEW GAME or a menu item",
        "press_b": _PRESS_B,
        "skip_dialog": _SKIP,
    },
    PlanScene.MENU.value: {
        "press_a": "select the highlighted menu row",
        "press_b": "close the menu",
        "press_start": "close the START menu",
        "walk_up": "move the menu cursor up",
        "walk_down": "move the menu cursor down",
    },
    PlanScene.OVERWORLD.value: {
        "walk_up": "joystick up, one tile",
        "walk_down": "joystick down, one tile",
        "walk_left": "joystick left, one tile",
        "walk_right": "joystick right, one tile",
        "press_a": _A,
        "press_b": _PRESS_B,
    },
}
