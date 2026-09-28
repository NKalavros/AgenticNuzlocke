"""Legal menus and replan gates for the Jev fast actor.

Jev picks one key from a menu this module builds. It never invents buttons,
and it never sees the screenshot — the planner's text card is the perception.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from nuzlocke.environment.joypad import is_naming_lock
from nuzlocke.llm.jev import JevAnswers, JevDecisionError
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

# Scenes whose plan is "standing still in a text-driven screen". Leaving that
# screen (the world region changes) is a reason to look again.
_HELD_SCENES = (PlanScene.DIALOG, PlanScene.TITLE)


@dataclass(frozen=True)
class FrameSignals:
    """Pixel digests for the frame the fast actor is about to act on."""

    world_digest: str
    dialog_digest: str
    world_changed: bool
    dialog_changed: bool
    # Narrative box is on screen. Sprite animation above it is not a new scene.
    text_box: bool = False


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


def classify_scene(
    obs: PlayerObservation,
    plan: PlanCard | None,
    signals: FrameSignals,
) -> str:
    """Menu to show Jev. Hard signals win; a held dialog plan survives text animation."""
    if is_naming_lock(obs.joy_ignore):
        return PlanScene.NAMING.value
    if obs.in_battle:
        return PlanScene.BATTLE.value
    same_world = (
        plan is not None
        and bool(plan.world_digest)
        and signals.world_digest == plan.world_digest
    )
    if (
        plan is not None
        and signals.text_box
        and plan.scene in (PlanScene.DIALOG, PlanScene.TITLE)
    ):
        # The picture above the box moves while text is up. Stay on this card.
        return plan.scene.value
    if plan is not None and plan.scene == PlanScene.MENU:
        # The highlight moving changes the world digest. That is still the menu.
        left_menu = (
            signals.world_digest != plan.world_digest and signals.dialog_changed
        )
        if not left_menu:
            return PlanScene.MENU.value
    if plan is not None and same_world and plan.scene in (
        PlanScene.DIALOG,
        PlanScene.TITLE,
        PlanScene.MENU,
    ):
        return plan.scene.value
    if signals.dialog_changed and not signals.world_changed:
        return PlanScene.DIALOG.value
    return PlanScene.OVERWORLD.value


def scene_changed(
    plan: PlanCard | None,
    obs: PlayerObservation,
    signals: FrameSignals,
) -> bool:
    """Naming, battle, or walking out of a dialog/title plan."""
    if plan is None:
        return True
    if is_naming_lock(obs.joy_ignore) != (plan.scene == PlanScene.NAMING):
        return True
    if bool(obs.in_battle) != (plan.scene == PlanScene.BATTLE):
        return True
    if (
        plan.scene == PlanScene.MENU
        and signals.world_digest != plan.world_digest
        and signals.dialog_changed
    ):
        return True
    if plan.scene in _HELD_SCENES:
        if signals.text_box:
            return False
        # The box this card was written against has closed, or the picture
        # above a box-less screen (the title splash) actually changed.
        if plan.text_box:
            return True
        return signals.world_digest != plan.world_digest
    return False


# An open speech is still one conversation. Look again every few seconds so a
# slow line ("Hello there!") is not mashed blind while the RAM map says bedroom.
_SPEECH_LOOK_S = 5.0
_TILE_LOOK_CYCLES = 6
_TILE_LOOK_MIN_S = 8.0


def needs_replan(
    plan: PlanCard | None,
    obs: PlayerObservation,
    signals: FrameSignals,
    *,
    now: float,
    plan_every_s: float,
    force: bool = False,
    same_tile_streak: int = 0,
) -> bool:
    if force or plan is None:
        return True
    if plan.scene == PlanScene.NAMING and plan.spent:
        # "Press DOWN once" was already pressed. Look before moving again.
        return True
    if scene_changed(plan, obs, signals):
        return True
    if (
        signals.text_box
        and plan.scene in (PlanScene.DIALOG, PlanScene.TITLE)
        and (now - plan.created_at) >= _SPEECH_LOOK_S
    ):
        return True
    if (
        plan.scene == PlanScene.OVERWORLD
        and same_tile_streak >= _TILE_LOOK_CYCLES
        and (now - plan.created_at) >= _TILE_LOOK_MIN_S
    ):
        return True
    return plan_every_s > 0 and (now - plan.created_at) >= plan_every_s


def reconcile_plan(plan: PlanCard, obs: PlayerObservation) -> PlanCard:
    """Naming lock and battle are mechanical. Don't spend another vision call to notice them."""
    if is_naming_lock(obs.joy_ignore):
        plan.scene = PlanScene.NAMING
    elif obs.in_battle:
        plan.scene = PlanScene.BATTLE
    return plan


def action_menu(
    scene: str,
    failed_approaches: list[list[str]] | None = None,
) -> dict[str, str]:
    """Choice criteria. Keys are ``GameAction`` values."""
    menu = dict(_MENUS.get(scene) or _MENUS[PlanScene.OVERWORLD.value])
    if scene == PlanScene.OVERWORLD.value:
        for label in _failed_walks(failed_approaches):
            menu.pop(label, None)
    if not menu:
        menu = {"press_b": _PRESS_B}
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


def build_jev_state(
    *,
    plan: PlanCard,
    scene: str,
    obs: PlayerObservation,
    signals: FrameSignals,
    memory: str | None = None,
    recent: list[dict[str, Any]] | None = None,
    objectives: dict[str, str] | None = None,
    nuzlocke: dict[str, Any] | None = None,
    failed_approaches: list[list[str]] | None = None,
    no_progress: dict[str, Any] | None = None,
) -> dict[str, Any]:
    state: dict[str, Any] = {
        "plan": {
            "scene": plan.scene.value,
            "see": plan.see,
            "plan": plan.plan,
            "do_not": list(plan.do_not),
        },
        "scene": scene,
        "objectives": objectives or {},
        "signals": {
            "naming_keyboard": is_naming_lock(obs.joy_ignore),
            "in_battle": bool(obs.in_battle),
            "world_changed": signals.world_changed,
            "dialog_region_changed": signals.dialog_changed,
            "world_unchanged_since_plan": signals.world_digest == plan.world_digest,
        },
    }
    if memory and memory.strip():
        state["memory"] = memory.strip()
    if recent:
        state["recent"] = recent
    if failed_approaches:
        state["failed_approaches"] = failed_approaches
    if nuzlocke:
        state["nuzlocke"] = nuzlocke
    if no_progress and no_progress.get("streak"):
        state["no_progress"] = no_progress
    if is_naming_lock(obs.joy_ignore):
        state["hard_signal"] = (
            "A NAMING KEYBOARD is on screen. walk_* moves the letter cursor "
            "and press_a types the highlighted glyph. Never skip_dialog."
        )
    elif scene == PlanScene.MENU.value:
        state["hard_signal"] = (
            "A menu is open. walk_up and walk_down move the highlight, "
            "not the player. press_a confirms that row. press_b backs out."
        )
    return state


def build_jev_questions(menu: dict[str, str]) -> dict[str, Any]:
    return {
        "action": {
            "type": "choice",
            "instructions": (
                "Pick the single next action that follows `plan` in the state. "
                "Do not repeat a recent outcome that failed."
            ),
            "criteria": menu,
        },
        "plan_stale": {
            "type": "noul",
            "instructions": (
                "Recent outcomes show this plan is no longer the right thing to follow."
            ),
            "criteria": {
                "true": "The plan no longer matches what is happening",
                "false": "The plan still fits the recent outcomes",
            },
        },
        "objective_done": {
            "type": "noul",
            "instructions": "The plan's objective is already complete.",
            "criteria": {
                "true": "The goal in the plan has already been achieved",
                "false": "The goal is still ahead",
            },
        },
    }


def plan_from_recovery(
    advice: RecoveryAdvice,
    *,
    scene: str,
    world_digest: str,
    now: float,
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
    force_replan: bool = False,
    failed_approaches: list[list[str]] | None = None,
    memory: str | None = None,
    recent: list[dict[str, Any]] | None = None,
    objectives: dict[str, str] | None = None,
    nuzlocke: dict[str, Any] | None = None,
    no_progress: dict[str, Any] | None = None,
    same_tile_streak: int = 0,
    jev_decide: Callable[[dict[str, Any], dict[str, Any]], JevAnswers],
    refresh_plan: Callable[[], PlanCard],
) -> FastTurn:
    """One prompt cycle: maybe refresh the plan, then ask Jev for one button.

    A stale or finished plan is refreshed once before the press. A second
    consecutive low-confidence answer also refreshes once; otherwise the
    unsure cycle presses a safe B-side action and does not spend a vision call.
    """
    replanned = False
    turned_objectives: ObjectivesUpdate | None = None
    turned_landmarks: list[LandmarkNote] = []

    def pull() -> PlanCard:
        nonlocal plan, replanned, turned_objectives, turned_landmarks
        plan = reconcile_plan(refresh_plan(), obs)
        replanned = True
        turned_objectives = plan.objectives
        turned_landmarks = list(plan.landmarks)
        return plan

    if needs_replan(
        plan,
        obs,
        signals,
        now=now,
        plan_every_s=plan_every_s,
        force=force_replan,
        same_tile_streak=same_tile_streak,
    ):
        pull()
    assert plan is not None

    scene = classify_scene(obs, plan, signals)
    if scene == PlanScene.NAMING.value:
        named = _named_press(plan)
        if named is not None:
            plan.spent = True
            return FastTurn(
                actions=[named],
                reason=f"naming grid; {named.value} once",
                plan=plan,
                low_confidence_streak=0,
                replanned=replanned,
                objectives=turned_objectives,
                landmarks=turned_landmarks,
            )
    if signals.text_box and scene in (PlanScene.DIALOG.value, PlanScene.TITLE.value):
        # One press. A hold-mash stops between printed characters and never
        # pages the line, which left Oak on "Hello there!" for the whole run.
        action = _speech_press(plan)
        return FastTurn(
            actions=[action],
            reason=f"speech on screen; {action.value} once",
            plan=plan,
            low_confidence_streak=0,
            replanned=replanned,
            objectives=turned_objectives,
            landmarks=turned_landmarks,
        )
    read = _ask(
        plan,
        scene,
        obs=obs,
        signals=signals,
        memory=memory,
        recent=recent,
        objectives=objectives,
        nuzlocke=nuzlocke,
        failed_approaches=failed_approaches,
        no_progress=no_progress,
        jev_decide=jev_decide,
    )
    if _should_refresh(read, stale_noul) and not replanned:
        pull()
        scene = classify_scene(obs, plan, signals)
        read = _ask(
            plan,
            scene,
            obs=obs,
            signals=signals,
            memory=memory,
            recent=recent,
            objectives=objectives,
            nuzlocke=nuzlocke,
            failed_approaches=failed_approaches,
            no_progress=no_progress,
            jev_decide=jev_decide,
        )

    action, reason, low_confidence_streak, scene = _apply_confidence(
        read,
        scene=scene,
        plan=plan,
        floor=confidence_floor,
        streak=low_confidence_streak,
        replanned=replanned,
        pull=pull,
        reclassify=lambda card: classify_scene(obs, card, signals),
        ask=lambda current, current_scene: _ask(
            current,
            current_scene,
            obs=obs,
            signals=signals,
            memory=memory,
            recent=recent,
            objectives=objectives,
            nuzlocke=nuzlocke,
            failed_approaches=failed_approaches,
            no_progress=no_progress,
            jev_decide=jev_decide,
        ),
    )
    agent = AgentRole.BATTLE if scene == PlanScene.BATTLE.value else AgentRole.OVERWORLD
    if scene == PlanScene.NAMING.value:
        plan.spent = True
    return FastTurn(
        actions=[action],
        reason=reason,
        plan=plan,
        low_confidence_streak=low_confidence_streak,
        replanned=replanned,
        agent=agent,
        objectives=turned_objectives,
        landmarks=turned_landmarks,
    )


def _named_press(plan: PlanCard) -> GameAction | None:
    """The single button a naming plan asked for, if it named one."""
    text = plan.plan.lower()
    for label, action in (
        ("press down", GameAction.WALK_DOWN),
        ("press up", GameAction.WALK_UP),
        ("press left", GameAction.WALK_LEFT),
        ("press right", GameAction.WALK_RIGHT),
        ("press start", GameAction.PRESS_START),
        ("press a", GameAction.PRESS_A),
        ("press b", GameAction.PRESS_B),
    ):
        if label in text:
            return action
    return None


def _speech_press(plan: PlanCard) -> GameAction:
    """The button the planner named for this line. Default is one B."""
    text = f"{plan.plan}\n{plan.see}".lower()
    if "press a" in text and "do not press a" not in text and "don't press a" not in text:
        return GameAction.PRESS_A
    return GameAction.PRESS_B


def _should_refresh(read: JevAnswers, stale_noul: float) -> bool:
    return read.plan_stale >= stale_noul or read.objective_done >= stale_noul


def _apply_confidence(
    read: JevAnswers,
    *,
    scene: str,
    plan: PlanCard,
    floor: float,
    streak: int,
    replanned: bool,
    pull: Callable[[], PlanCard],
    reclassify: Callable[[PlanCard], str],
    ask: Callable[[PlanCard, str], JevAnswers],
) -> tuple[GameAction, str, int, str]:
    if _confident(read, floor):
        return _action(read), _reason(read, plan), 0, scene
    streak += 1
    if streak >= 2 and not replanned:
        plan = pull()
        scene = reclassify(plan)
        read = ask(plan, scene)
        if _confident(read, floor):
            return _action(read), _reason(read, plan), 0, scene
        streak = 0
        return (
            safe_action(scene),
            f"jev still unsure after a new plan ({read.confidence:.2f}); safe action",
            streak,
            scene,
        )
    return (
        safe_action(scene),
        f"jev low confidence ({read.confidence:.2f}); safe action",
        streak,
        scene,
    )


def _confident(read: JevAnswers, floor: float) -> bool:
    if read.confidence < floor:
        return False
    try:
        GameAction(read.action)
    except ValueError:
        return False
    return True


def _action(read: JevAnswers) -> GameAction:
    return GameAction(read.action)


def _reason(read: JevAnswers, plan: PlanCard) -> str:
    brief = " ".join(plan.plan.split())[:80]
    return f"jev {read.action} (conf {read.confidence:.2f}) following: {brief}"


def _ask(
    plan: PlanCard,
    scene: str,
    *,
    obs: PlayerObservation,
    signals: FrameSignals,
    memory: str | None,
    recent: list[dict[str, Any]] | None,
    objectives: dict[str, str] | None,
    nuzlocke: dict[str, Any] | None,
    failed_approaches: list[list[str]] | None,
    no_progress: dict[str, Any] | None,
    jev_decide: Callable[[dict[str, Any], dict[str, Any]], JevAnswers],
) -> JevAnswers:
    menu = action_menu(scene, failed_approaches)
    state = build_jev_state(
        plan=plan,
        scene=scene,
        obs=obs,
        signals=signals,
        memory=memory,
        recent=recent,
        objectives=objectives,
        nuzlocke=nuzlocke,
        failed_approaches=failed_approaches,
        no_progress=no_progress,
    )
    try:
        return jev_decide(state, build_jev_questions(menu))
    except JevDecisionError:
        return JevAnswers(
            action="",
            confidence=0.0,
            plan_stale=0.0,
            objective_done=0.0,
            model="",
        )


def _failed_walks(failed_approaches: list[list[str]] | None) -> set[str]:
    found: set[str] = set()
    for seq in failed_approaches or []:
        for label in seq:
            if str(label).startswith("walk_"):
                found.add(str(label))
    return found


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
    PlanScene.DIALOG.value: {
        "skip_dialog": _SKIP,
        "press_b": _PRESS_B,
    },
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
