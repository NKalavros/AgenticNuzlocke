"""Role agent helpers."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from nuzlocke.agents import prompts
from nuzlocke.agents.locomotion import map_context
from nuzlocke.agents.navigation import parse_route_plan
from nuzlocke.environment.joypad import is_naming_lock
from nuzlocke.environment.macros import expand_actions
from nuzlocke.knowledge.beats import current_beat, is_intro_boot
from nuzlocke.llm.base import LLMProvider
from nuzlocke.orchestration.stuck import (
    LOOP_RECOVERY,
    NO_PROGRESS_RECOVERY,
    NOOP_RECOVERY,
    STUCK_RECOVERY,
    avoid_blocked_walk,
    single_named_walk,
)
from nuzlocke.referee.type_chart import battle_matchup
from nuzlocke.state.models import (
    ActionProposal,
    AgentRole,
    DirectorDecision,
    GameAction,
    GameMode,
    LandmarkNote,
    ObjectivesUpdate,
    PlanCard,
    PlanScene,
    PlayerObservation,
    RecoveryAdvice,
    TaskEnvelope,
)

_TIERS = ("primary", "secondary", "tertiary")


def _images(obs: PlayerObservation) -> list[Path]:
    for path in (obs.vision_path, obs.screenshot_path):
        if path and Path(path).exists():
            return [Path(path)]
    return []


def _obs_payload(obs: PlayerObservation, *, vision_only: bool) -> dict[str, Any]:
    if not vision_only:
        return {"observation": obs.model_dump(mode="json")}
    payload: dict[str, Any] = {
        "vision_only": True,
        "note": (
            "The screenshot decides dialog, menus, and battles. `map` is the tilemap walk grid, "
            "in the same cells as the screenshot grid. It is usually right; blocked_on_tile and "
            "recent outcomes are what actually happened."
        ),
    }
    grid = map_context(obs)
    if grid:
        payload["map"] = grid
    # Bit 5 (dialog) stays out: it reads 0 through real dialog on Red Star.
    if is_naming_lock(obs.joy_ignore):
        payload["hard_signal"] = (
            "RAM shows instant-text mode: the NAMING KEYBOARD (letter grid) or a Pokédex page. "
            "On the letter grid, walk_* moves the letter cursor, press_a types the highlighted "
            "letter and press_start finishes the name — never skip_dialog there. On a Pokédex "
            "page, press_a turns the page."
        )
    return payload


def _with_extras(
    payload: dict[str, Any],
    *,
    memory: str | None = None,
    recent: list[dict[str, Any]] | None = None,
    walkthrough_hint: str | None = None,
    objectives: dict[str, str] | None = None,
    nuzlocke: dict[str, Any] | None = None,
    failed_approaches: list[list[str]] | None = None,
    no_progress: dict[str, Any] | None = None,
    beat: str | None = None,
    blocked_on_tile: list[str] | None = None,
    buttons_on_this_tile: dict[str, int] | None = None,
    trigger: str | None = None,
    journal: list[str] | None = None,
    battle: dict[str, Any] | None = None,
    constraints: list[str] | None = None,
    navigation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    memory = (memory or "").strip()
    for key, value in (
        ("trigger", trigger),
        ("journal", journal),
        ("battle", battle),
        ("constraints", constraints),
        ("navigation", navigation),
    ):
        if value:
            payload[key] = value
    walkthrough_hint = (walkthrough_hint or "").strip()
    if recent:
        payload["recent"] = recent
    if memory:
        payload["memory"] = memory
    if walkthrough_hint:
        payload["walkthrough_hint"] = walkthrough_hint
        payload["walkthrough_skill"] = (
            "hint above is the relevant excerpt — do not browse skill files"
        )
    if objectives:
        payload["objectives"] = objectives
    if nuzlocke:
        payload["nuzlocke"] = nuzlocke
    if failed_approaches:
        payload["failed_approaches"] = failed_approaches
        payload["failed_approaches_note"] = (
            "Walk bursts that already nooped — sidestep; do not ban A/Start/skip_dialog"
        )
    if no_progress and no_progress.get("streak"):
        payload["no_progress"] = no_progress
        payload["no_progress_note"] = (
            f"The game world has not changed for {no_progress['streak']} straight cycles — only "
            "text has. Whatever you have been repeating is not working. Either your current "
            "objective is already complete, or you are talking to the wrong thing. Do something "
            "structurally different: walk away from this tile, or pick a different objective."
        )
    if beat:
        payload["beat"] = beat
        payload["beat_note"] = (
            "This is the only objective. Do not replace it. Name the one button that serves it."
        )
    if blocked_on_tile:
        payload["blocked_on_tile"] = list(blocked_on_tile)
        payload["blocked_on_tile_note"] = (
            "These directions did not move the player on this tile. "
            "Do not choose them. Sidestep, then retry the beat's direction."
        )
    if buttons_on_this_tile:
        payload["buttons_on_this_tile"] = dict(buttons_on_this_tile)
        pressed_a = int(buttons_on_this_tile.get("press_a") or 0)
        pressed_b = int(buttons_on_this_tile.get("press_b") or 0)
        if pressed_a or pressed_b:
            payload["buttons_note"] = (
                f"On this tile A was pressed {pressed_a} time(s) and B {pressed_b} time(s). A "
                "book, sign, or generic chatter is not the beat. Do not press A here again. If "
                "this is not a YES/NO or the starter itself, name a walk toward the beat."
            )
    return payload


def _ask(
    llm: LLMProvider,
    obs: PlayerObservation,
    payload: dict[str, Any],
    *,
    role: AgentRole,
    system: str,
    schema: dict[str, Any],
    **extras: Any,
) -> tuple[dict[str, Any], str]:
    resp = llm.complete(
        role=role,
        system=system,
        user=json.dumps(_with_extras(payload, **extras), separators=(",", ":")),
        schema_hint=schema,
        image_paths=_images(obs),
    )
    return resp.parsed or {}, resp.raw_text


def _parse_actions(raw: Any) -> list[GameAction]:
    actions: list[GameAction] = []
    for item in raw or ():
        try:
            actions.append(GameAction(item))
        except ValueError:
            continue
    return actions


def _clean_lines(items: Any, width: int) -> list[str]:
    texts = (" ".join(str(item).split()) for item in items[:6])
    return [text[:width] for text in texts if text]


def _stripped(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    return value.strip() or None


def parse_objectives(raw: Any) -> ObjectivesUpdate | None:
    if not isinstance(raw, dict):
        return None
    tiers = {tier: _stripped(raw.get(tier)) for tier in _TIERS}
    return ObjectivesUpdate(**tiers) if any(tiers.values()) else None


def parse_landmarks(raw: Any) -> list[LandmarkNote]:
    if not isinstance(raw, list):
        return []
    out: list[LandmarkNote] = []
    for item in raw[:6]:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "").strip()
        note = str(item.get("note") or "").strip()
        if label and note:
            out.append(LandmarkNote(label=label[:80], note=note[:200]))
    return out


def merge_objectives(current: dict[str, str], update: ObjectivesUpdate | None) -> dict[str, str]:
    if update is None:
        return current
    merged = dict(current)
    for tier, text in update.model_dump().items():
        if text:
            merged[tier] = text
    return merged


def objectives_for_dashboard(objectives: dict[str, str]) -> list[dict[str, Any]]:
    return [
        {"tier": tier, "text": objectives[tier], "done": False}
        for tier in _TIERS
        if objectives.get(tier)
    ]


# Next-gym target per badge count, mirroring NuzlockeReferee.MILESTONE_ORDER.
_NEXT_GYM_TARGET: tuple[str, ...] = (
    "Pewter City for Brock",
    "Cerulean City for Misty",
    "Vermilion City for Lt. Surge",
    "Celadon City for Erika",
    "Fuchsia City for Koga",
    "Saffron City for Sabrina",
    "Cinnabar Island for Blaine",
    "Viridian City for Giovanni",
    "the Pokemon League to challenge the Elite Four and Champion",
)


def decide_director(
    llm: LLMProvider,
    *,
    summary: dict[str, Any],
    obs: PlayerObservation,
    memory: str | None = None,
    vision_only: bool = False,
    walkthrough_hint: str | None = None,
    speech: bool = False,
) -> DirectorDecision:
    """Deterministic routing: never calls ``llm``."""
    if obs.in_battle:
        return DirectorDecision(
            mode=GameMode.BATTLE,
            owner=AgentRole.BATTLE,
            objective="Resolve the current battle turn conservatively",
            constraints=["One turn at a time", "No trainer items"],
            abort=["blackout"],
            narration="Battle detected — routing to Battle Agent.",
        )
    # Speech wins over the map: NEW GAME places the player in Red's House while Oak still talks.
    if speech:
        return DirectorDecision(
            mode=GameMode.OVERWORLD,
            owner=AgentRole.OVERWORLD,
            objective="Someone is still speaking. Advance that dialogue. The map grid is not the scene.",
            constraints=[
                "Trust the screenshot over the map name and coordinates",
                "One button press to page the current line",
                "Do not walk",
            ],
            success=["the speaker is done and the overworld is visible"],
            abort=["battle_started"],
            narration="Speech on screen — ignore the map grid.",
        )
    if is_intro_boot(obs):
        return DirectorDecision(
            mode=GameMode.OVERWORLD,
            owner=AgentRole.OVERWORLD,
            objective="Advance title/intro using the screenshot as ground truth",
            constraints=[
                "Trust the screenshot over RAM",
                "Prefer skip_dialog for Oak/intro text; naming keyboard → END",
                "Handle YES-NO / naming before walking",
                "Max 12 actions (macros count as one)",
            ],
            success=["controllable overworld visible on screen"],
            abort=["battle_started"],
            narration="Boot/intro — overworld agent should read the screen.",
        )

    stuck = int(summary.get("stuck_score") or 0)
    noop = int(summary.get("noop_streak") or 0)
    loop = int(summary.get("loop_streak") or 0)
    no_progress = int(summary.get("no_progress_streak") or 0)
    if (
        stuck >= STUCK_RECOVERY
        or noop >= NOOP_RECOVERY
        or loop >= LOOP_RECOVERY
        or no_progress >= NO_PROGRESS_RECOVERY
    ):
        return DirectorDecision(
            mode=GameMode.RECOVERY,
            owner=AgentRole.RECOVERY,
            objective="Break the stuck/noop loop using screenshot + walkthrough hint",
            constraints=[
                "Max 4 actions",
                "Screenshot is ground truth",
                "Do not repeat failed_approaches",
            ],
            abort=["battle_started"],
            narration=(
                f"Stuck path → recovery (stuck={stuck}, noop={noop}, loop={loop}, "
                f"no_progress={no_progress}); no Director LLM."
            ),
        )

    next_target = _NEXT_GYM_TARGET[min(len(obs.badges), len(_NEXT_GYM_TARGET) - 1)]
    beat = None if is_naming_lock(obs.joy_ignore) else current_beat(obs)
    if beat is not None:
        objective = beat.text
    elif vision_only:
        objective = f"Read the screenshot only: clear menus/dialog/naming, then continue toward {next_target}"
    elif "House" in (obs.map_name or ""):
        objective = (
            f"If the SCREEN shows overworld, leave the house and continue toward {next_target}; "
            "if it shows naming/dialog, resolve that first"
        )
    elif not obs.party:
        objective = "Obtain a starter from Professor Oak (screen-first)"
    else:
        objective = f"Make safe progress toward {next_target}"
    return DirectorDecision(
        mode=GameMode.OVERWORLD,
        owner=AgentRole.OVERWORLD,
        objective=objective,
        constraints=[
            "About 1-5 logical actions per prompt; prefer walk_*_3/4 on clear paths",
            "Screenshot is ground truth",
            "Do not walk while a text box or naming grid is visible",
        ],
        abort=["battle_started", "stuck_score >= 6"],
        narration=(
            "Fast route → overworld (vision-only)."
            if vision_only
            else f"Fast route → overworld (RAM map={obs.map_name or 'unknown'})."
        ),
    )


def propose_overworld(
    llm: LLMProvider,
    *,
    task: TaskEnvelope,
    obs: PlayerObservation,
    memory: str | None = None,
    recent: list[dict[str, Any]] | None = None,
    vision_only: bool = False,
    walkthrough_hint: str | None = None,
    objectives: dict[str, str] | None = None,
    nuzlocke: dict[str, Any] | None = None,
    failed_approaches: list[list[str]] | None = None,
    loop_streak: int = 0,
    no_progress: dict[str, Any] | None = None,
    beat: str | None = None,
    blocked_on_tile: list[str] | None = None,
) -> ActionProposal:
    data, raw_text = _ask(
        llm,
        obs,
        {"task": task.model_dump(mode="json"), **_obs_payload(obs, vision_only=vision_only)},
        role=AgentRole.OVERWORLD,
        system=prompts.OVERWORLD_SYSTEM + (prompts.VISION_ONLY_SUFFIX if vision_only else ""),
        schema=prompts.OVERWORLD_SCHEMA,
        memory=memory,
        recent=recent,
        walkthrough_hint=walkthrough_hint,
        objectives=objectives,
        nuzlocke=nuzlocke,
        failed_approaches=failed_approaches,
        no_progress=no_progress,
        beat=beat,
        blocked_on_tile=blocked_on_tile,
    )
    actions = _parse_actions(data.get("actions")) or [GameAction.WAIT_60]
    return ActionProposal(
        task_id=task.task_id,
        agent=AgentRole.OVERWORLD,
        reason=str(data.get("reason") or raw_text[:300] or "overworld step"),
        actions=avoid_blocked_walk(actions, blocked_on_tile or [], alternate=loop_streak)[:12],
        expected=list(data.get("expected") or []),
        risk=data.get("risk") if data.get("risk") in {"low", "medium", "high"} else "low",
        objectives=parse_objectives(data.get("objectives")),
        landmarks=parse_landmarks(data.get("landmarks")),
    )


def propose_battle(
    llm: LLMProvider,
    *,
    task: TaskEnvelope,
    obs: PlayerObservation,
    memory: str | None = None,
    recent: list[dict[str, Any]] | None = None,
    vision_only: bool = False,
    walkthrough_hint: str | None = None,
    objectives: dict[str, str] | None = None,
    nuzlocke: dict[str, Any] | None = None,
) -> ActionProposal:
    payload = {
        "task": task.model_dump(mode="json"),
        **_obs_payload(obs, vision_only=vision_only),
        "reminder": "ONE battle input only (optional wait_60 after).",
    }
    enemy_species = str(((obs.battle or {}).get("enemy") or {}).get("species") or "")
    matchup = battle_matchup(obs.party, enemy_species) if enemy_species else None
    if matchup:
        payload["type_matchup"] = matchup
    data, raw_text = _ask(
        llm,
        obs,
        payload,
        role=AgentRole.BATTLE,
        system=prompts.BATTLE_SYSTEM,
        schema=prompts.BATTLE_SCHEMA,
        memory=memory,
        recent=recent,
        walkthrough_hint=walkthrough_hint,
        objectives=objectives,
        nuzlocke=nuzlocke,
    )
    return ActionProposal(
        task_id=task.task_id,
        agent=AgentRole.BATTLE,
        reason=str(data.get("reason") or raw_text[:300] or "battle step"),
        actions=(_parse_actions(data.get("actions")) or [GameAction.PRESS_A])[:4],
        expected=list(data.get("expected") or []),
        risk=data.get("risk") if data.get("risk") in {"low", "medium", "high"} else "medium",
    )


def advise_recovery(
    llm: LLMProvider,
    *,
    obs: PlayerObservation,
    stuck_score: int,
    recent_positions: list[tuple[str | None, int | None, int | None]],
    memory: str | None = None,
    recent: list[dict[str, Any]] | None = None,
    vision_only: bool = False,
    walkthrough_hint: str | None = None,
    objectives: dict[str, str] | None = None,
    nuzlocke: dict[str, Any] | None = None,
    failed_approaches: list[list[str]] | None = None,
    loop_streak: int = 0,
    no_progress: dict[str, Any] | None = None,
    reframe: bool = False,
    beat: str | None = None,
    blocked_on_tile: list[str] | None = None,
) -> RecoveryAdvice:
    payload: dict[str, Any] = {
        "stuck_score": stuck_score,
        **_obs_payload(obs, vision_only=vision_only),
    }
    if not vision_only:
        payload["recent_positions"] = recent_positions
    if reframe:
        payload["reframe"] = (
            "Your current objective has produced nothing for a long time. Assume it is ALREADY "
            "COMPLETE or unreachable from here. Do not propose talking to the same NPC again. Set "
            "new objectives and propose actions that leave this spot — a door, stairs, or the "
            "next walkthrough step."
        )
    data, raw_text = _ask(
        llm,
        obs,
        payload,
        role=AgentRole.RECOVERY,
        system=prompts.RECOVERY_SYSTEM,
        schema=prompts.RECOVERY_SCHEMA,
        memory=memory,
        recent=recent,
        walkthrough_hint=walkthrough_hint,
        objectives=objectives,
        nuzlocke=nuzlocke,
        failed_approaches=failed_approaches,
        no_progress=no_progress,
        beat=beat,
        blocked_on_tile=blocked_on_tile,
    )
    # An empty answer pages with B. A would re-open whoever the player faces.
    actions = _parse_actions(data.get("proposed_actions") or ["press_b", "press_b"])
    named = single_named_walk(str(data.get("reason") or ""))
    if named is not None and actions and actions[0].value.startswith("walk_"):
        actions[0] = named
    return RecoveryAdvice(
        diagnosis=str(data.get("diagnosis") or "unknown"),
        proposed_actions=avoid_blocked_walk(
            actions[:4], blocked_on_tile or [], alternate=loop_streak
        ),
        escalate_to_human=bool(data.get("escalate_to_human", stuck_score >= 5)),
        reason=str(data.get("reason") or raw_text[:300]),
        objectives=parse_objectives(data.get("objectives")),
        landmarks=parse_landmarks(data.get("landmarks")),
    )


def rollup_memory(llm: LLMProvider, *, memory: str) -> list[str]:
    memory = memory.strip()
    if not memory:
        return []
    resp = llm.complete(
        role=AgentRole.DIRECTOR,
        system=prompts.MEMORY_ROLLUP_SYSTEM,
        user=json.dumps({"memory": memory[:6000]}, separators=(",", ":")),
        schema_hint=prompts.MEMORY_ROLLUP_SCHEMA,
        image_paths=None,
    )
    notes = (resp.parsed or {}).get("notes")
    return _clean_lines(notes, 200) if isinstance(notes, list) else []


def propose_plan(
    llm: LLMProvider,
    *,
    obs: PlayerObservation,
    memory: str | None = None,
    recent: list[dict[str, Any]] | None = None,
    vision_only: bool = False,
    walkthrough_hint: str | None = None,
    objectives: dict[str, str] | None = None,
    nuzlocke: dict[str, Any] | None = None,
    failed_approaches: list[list[str]] | None = None,
    no_progress: dict[str, Any] | None = None,
    objective: str | None = None,
    beat: str | None = None,
    blocked_on_tile: list[str] | None = None,
    buttons_on_this_tile: dict[str, int] | None = None,
    trigger: str | None = None,
    journal: list[str] | None = None,
    battle: dict[str, Any] | None = None,
    constraints: list[str] | None = None,
    navigation: dict[str, Any] | None = None,
) -> PlanCard:
    """System 2: read the screenshot and the journal, and set the next objective."""
    data, _ = _ask(
        llm,
        obs,
        {"objective": objective or "", **_obs_payload(obs, vision_only=vision_only)},
        role=AgentRole.DIRECTOR,
        system=prompts.PLANNER_SYSTEM + (prompts.VISION_ONLY_SUFFIX if vision_only else ""),
        schema=prompts.PLANNER_SCHEMA,
        memory=memory,
        recent=recent,
        walkthrough_hint=walkthrough_hint,
        objectives=objectives,
        nuzlocke=nuzlocke,
        failed_approaches=failed_approaches,
        no_progress=no_progress,
        beat=beat,
        blocked_on_tile=blocked_on_tile,
        buttons_on_this_tile=buttons_on_this_tile,
        trigger=trigger,
        journal=journal,
        battle=battle,
        constraints=constraints,
        navigation=navigation,
    )
    try:
        scene = PlanScene(str(data.get("scene") or "").strip().lower())
    except ValueError:
        scene = PlanScene.OVERWORLD
    plan = str(data.get("plan") or "").strip()[:500]
    return PlanCard(
        scene=scene,
        see=str(data.get("see") or "").strip()[:300] or "screen unread",
        plan=plan or objective or "Continue the current objective.",
        do_not=_clean_lines(data.get("do_not") or [], 120),
        steps=parse_steps(data.get("steps")),
        target_cell=parse_cell(_target_value(data.get("target"), "cell")),
        goal_target=parse_target(data.get("target")),
        done_when=data.get("done_when") if isinstance(data.get("done_when"), dict) else {},
        battle_plan=_battle_plan(data.get("battle_plan")),
        route_plan=parse_route_plan(data.get("route_plan")),
        objectives=parse_objectives(data.get("objectives")),
        landmarks=parse_landmarks(data.get("landmarks")),
    )


# Walks are single tiles so each one can be checked before the next.
_STEP_BUTTONS = {
    GameAction.WALK_UP,
    GameAction.WALK_DOWN,
    GameAction.WALK_LEFT,
    GameAction.WALK_RIGHT,
    GameAction.PRESS_A,
    GameAction.PRESS_B,
    GameAction.PRESS_START,
}
MAX_PLAN_STEPS = 6


def parse_steps(raw: Any) -> list[GameAction]:
    """The planner's button path, expanded to single presses and capped."""
    if not isinstance(raw, list):
        return []
    actions = _parse_actions(str(item).strip().lower() for item in raw)
    return [step for step in expand_actions(actions) if step in _STEP_BUTTONS][:MAX_PLAN_STEPS]


def _battle_plan(raw: Any) -> dict[str, Any]:
    """Move names in order, a switch target, and the HP fraction to switch at."""
    if not isinstance(raw, dict):
        return {}
    moves = [str(m).strip().upper() for m in raw.get("moves") or [] if str(m).strip()]
    try:
        below = float(raw.get("switch_below") or 0.0)
    except (TypeError, ValueError):
        below = 0.0
    from nuzlocke.state.models import BattlePlan

    plan = BattlePlan(
        moves=moves[:4],
        opening_moves=[str(m).upper() for m in raw.get("opening_moves", [])][:4],
        switch_below=min(max(below, 0.0), 1.0),
    ).model_dump(exclude_none=True)
    if raw.get("switch_to"):
        plan["switch_to"] = str(raw["switch_to"]).strip()
    if raw.get("notes"):
        plan["notes"] = str(raw["notes"])[:200]
    return plan if moves or plan["opening_moves"] or "switch_to" in plan else {}


def _target_value(raw: Any, kind: str) -> Any:
    """The value of a ``{"kind", "value"}`` target of this kind; a bare string is a cell."""
    if isinstance(raw, dict):
        return raw.get("value") if raw.get("kind") == kind else None
    return raw if kind == "cell" else None


def parse_target(raw: Any) -> dict[str, Any] | None:
    """System 2's target in the form ``agents.goals`` matches options against."""
    from nuzlocke.environment.maps import map_name

    if not isinstance(raw, dict):
        cell = parse_cell(raw)
        return {"kind": "cell", "cell": cell} if cell else None
    kind = str(raw.get("kind") or "").lower()
    value = str(raw.get("value") or "").strip()
    if kind == "exit" and value:
        wanted = value.casefold()
        dest = next(
            (i for i in range(256) if (map_name(i) or "").casefold() == wanted and i != 255), None
        )
        if dest is None and wanted in {"outside", "back outside", "out"}:
            dest = 255
        return {"kind": "warp", "dest_map": dest} if dest is not None else None
    if kind == "edge" and value in {"up", "down", "left", "right"}:
        return {"kind": "edge", "dir": value}
    if kind == "npc" and value:
        return {"kind": "npc", "name": value}
    if kind == "cell" and parse_cell(value):
        return {"kind": "cell", "cell": parse_cell(value)}
    return None


def parse_cell(raw: Any) -> str | None:
    """A walk-grid cell like ``G7``, or None."""
    text = str(raw or "").strip().upper()
    if len(text) == 2 and text[0] in "ABCDEFGHIJ" and text[1] in "123456789":
        return text
    return None


def make_task(decision: DirectorDecision) -> TaskEnvelope:
    return TaskEnvelope(
        task_id=f"task-{uuid.uuid4().hex[:8]}",
        owner=decision.owner,
        objective=decision.objective,
        constraints=decision.constraints,
        success=decision.success,
        abort=decision.abort,
    )
