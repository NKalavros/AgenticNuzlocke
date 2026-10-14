"""Role agent helpers."""

from __future__ import annotations

import json
import uuid
from functools import partial
from pathlib import Path
from typing import Any

from nuzlocke.agents import prompts
from nuzlocke.agents.locomotion import map_context
from nuzlocke.agents.navigation import parse_route_plan
from nuzlocke.assets import data
from nuzlocke.assets import data as asset_data
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


_CONTEXT_FIELDS = (
    "memory recent walkthrough_hint objectives nuzlocke failed_approaches no_progress beat "
    "blocked_on_tile buttons_on_this_tile trigger journal battle constraints navigation"
)
_CONTEXT_KEYS = set(_CONTEXT_FIELDS.split())


def _with_extras(payload: dict[str, Any], **context: Any) -> dict[str, Any]:
    unknown = context.keys() - _CONTEXT_KEYS
    if unknown:
        raise TypeError(f"Unexpected prompt context: {sorted(unknown)}")
    notes = data("prompts/context_notes.json")
    for key, value in context.items():
        if key in {"memory", "walkthrough_hint"}:
            value = (value or "").strip()
        if not value or (key == "no_progress" and not value.get("streak")):
            continue
        if key == "blocked_on_tile":
            value = list(value)
        if key == "buttons_on_this_tile":
            value = dict(value)
        payload[key] = value
        note_key = "walkthrough_skill" if key == "walkthrough_hint" else key + "_note"
        if note_key in notes:
            payload[note_key] = notes[note_key].format(**value) if key == "no_progress" else notes[note_key]
    buttons = context.get("buttons_on_this_tile") or {}
    counts = {key: int(buttons.get(key) or 0) for key in ("press_a", "press_b")}
    if any(counts.values()):
        payload["buttons_note"] = notes["buttons_note"].format(**counts)
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
    if getattr(llm, "name", "") in {"codex", "claude_code", "gemini_cli", "antigravity", "openai_compatible"}:
        from nuzlocke.llm.cli_providers import validate_output

        validate_output(resp.parsed, schema)
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
    return [{"tier": tier, "text": objectives[tier], "done": False} for tier in _TIERS if objectives.get(tier)]


# Next-gym target per badge count, mirroring NuzlockeReferee.MILESTONE_ORDER.
_NEXT_GYM_TARGET = tuple(asset_data("gym_targets.json"))


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
        return DirectorDecision(**data("prompts/director.json")["battle"])
    # Speech wins over the map: NEW GAME places the player in Red's House while Oak still talks.
    if speech:
        return DirectorDecision(**data("prompts/director.json")["speech"])
    if is_intro_boot(obs):
        return DirectorDecision(**data("prompts/director.json")["intro"])

    stuck = int(summary.get("stuck_score") or 0)
    noop = int(summary.get("noop_streak") or 0)
    loop = int(summary.get("loop_streak") or 0)
    no_progress = int(summary.get("no_progress_streak") or 0)
    if stuck >= STUCK_RECOVERY or noop >= NOOP_RECOVERY or loop >= LOOP_RECOVERY or no_progress >= NO_PROGRESS_RECOVERY:
        return DirectorDecision(
            **data("prompts/director.json")["recovery"],
            narration=f"Stuck path → recovery (stuck={stuck}, noop={noop}, loop={loop}, "
            f"no_progress={no_progress}); automatic recovery routing.",
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
        **data("prompts/director.json")["overworld"],
        objective=objective,
        narration="Fast route → overworld (vision-only)."
        if vision_only
        else f"Fast route → overworld (RAM map={obs.map_name or 'unknown'}).",
    )


def _propose_action(llm, *, role, task, obs, vision_only=False, loop_streak=0, blocked_on_tile=None, **context):
    in_battle = role == AgentRole.BATTLE
    payload = {"task": task.model_dump(mode="json"), **_obs_payload(obs, vision_only=vision_only)}
    if in_battle:
        payload["reminder"] = "ONE battle input only (optional wait_60 after)."
        if obs.policy.get("team_plan"):
            payload["system4"] = obs.policy["team_plan"]
        species = str(((obs.battle or {}).get("enemy") or {}).get("species") or "")
        if species and (matchup := battle_matchup(obs.party, species)):
            payload["type_matchup"] = matchup
    system = prompts.BATTLE_SYSTEM if in_battle else prompts.OVERWORLD_SYSTEM
    if vision_only and not in_battle:
        system += prompts.VISION_ONLY_SUFFIX
    result, raw = _ask(
        llm,
        obs,
        payload,
        role=role,
        system=system,
        schema=prompts.BATTLE_SCHEMA if in_battle else prompts.OVERWORLD_SCHEMA,
        blocked_on_tile=blocked_on_tile,
        **context,
    )
    actions = _parse_actions(result.get("actions")) or [GameAction.PRESS_A if in_battle else GameAction.WAIT_60]
    if not in_battle:
        actions = avoid_blocked_walk(actions, blocked_on_tile or [], alternate=loop_streak)
    return ActionProposal(
        task_id=task.task_id,
        agent=role,
        reason=str(result.get("reason") or raw[:300] or ("battle step" if in_battle else "overworld step")),
        actions=actions[: 4 if in_battle else 12],
        expected=list(result.get("expected") or []),
        risk=result.get("risk") if result.get("risk") in {"low", "medium", "high"} else ("medium" if in_battle else "low"),
        objectives=None if in_battle else parse_objectives(result.get("objectives")),
        landmarks=[] if in_battle else parse_landmarks(result.get("landmarks")),
    )


propose_overworld = partial(_propose_action, role=AgentRole.OVERWORLD)
propose_battle = partial(_propose_action, role=AgentRole.BATTLE)


def advise_recovery(
    llm: LLMProvider,
    *,
    obs: PlayerObservation,
    stuck_score: int,
    recent_positions: list[tuple[str | None, int | None, int | None]],
    vision_only: bool = False,
    loop_streak: int = 0,
    reframe: bool = False,
    blocked_on_tile: list[str] | None = None,
    **context: Any,
) -> RecoveryAdvice:
    payload: dict[str, Any] = {"stuck_score": stuck_score, **_obs_payload(obs, vision_only=vision_only)}
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
        blocked_on_tile=blocked_on_tile,
        **context,
    )
    # An empty answer pages with B. A would re-open whoever the player faces.
    actions = _parse_actions(data.get("proposed_actions") or ["press_b", "press_b"])
    named = single_named_walk(str(data.get("reason") or ""))
    if named is not None and actions and actions[0].value.startswith("walk_"):
        actions[0] = named
    return RecoveryAdvice(
        diagnosis=str(data.get("diagnosis") or "unknown"),
        proposed_actions=avoid_blocked_walk(actions[:4], blocked_on_tile or [], alternate=loop_streak),
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
    vision_only: bool = False,
    objective: str | None = None,
    blocked_on_tile: list[str] | None = None,
    **context: Any,
) -> PlanCard:
    """System 2: read the screenshot and the journal, and set the next objective."""
    data, _ = _ask(
        llm,
        obs,
        {"objective": objective or "", **_obs_payload(obs, vision_only=vision_only)},
        role=AgentRole.DIRECTOR,
        system=prompts.PLANNER_SYSTEM + (prompts.VISION_ONLY_SUFFIX if vision_only else ""),
        schema=prompts.PLANNER_SCHEMA,
        blocked_on_tile=blocked_on_tile,
        **context,
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
        target_cell=(parse_target(data.get("target")) or {}).get("cell"),
        goal_target=parse_target(data.get("target")),
        done_when=data.get("done_when") if isinstance(data.get("done_when"), dict) else {},
        battle_plan=_battle_plan(data.get("battle_plan")),
        route_plan=parse_route_plan(data.get("route_plan")),
        objectives=parse_objectives(data.get("objectives")),
        landmarks=parse_landmarks(data.get("landmarks")),
    )


# Walks are single tiles so each one can be checked before the next.
_STEP_BUTTONS = {
    GameAction(name) for name in ("walk_up", "walk_down", "walk_left", "walk_right", "press_a", "press_b", "press_start")
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
    from pydantic import ValidationError

    from nuzlocke.state.models import BattlePlan

    try:
        plan = BattlePlan(
            moves=moves[:4],
            opening_moves=[str(m).upper() for m in raw.get("opening_moves", [])][:4],
            move_rules=raw.get("move_rules") or [],
            avoid_moves=raw.get("avoid_moves") or [],
            switch_below=min(max(below, 0.0), 1.0),
        ).model_dump(exclude_none=True)
    except ValidationError:
        # Do not silently turn a malformed conditional strategy into unconditional moves.
        return {}
    if raw.get("switch_to"):
        plan["switch_to"] = str(raw["switch_to"]).strip()
    if raw.get("notes"):
        plan["notes"] = str(raw["notes"])[:1200]
    return plan if moves or plan["opening_moves"] or "switch_to" in plan else {}


def parse_target(raw: Any) -> dict[str, Any] | None:
    """System 2's target in the form ``agents.goals`` matches options against."""
    from nuzlocke.environment.maps import map_id_for_name

    raw = raw if isinstance(raw, dict) else {"kind": "cell", "value": raw}
    kind, value = str(raw.get("kind") or "").lower(), str(raw.get("value") or "").strip()
    if kind == "tile" and all(type(raw.get(k)) is int and 0 <= raw[k] < 256 for k in ("map_id", "x", "y")):
        return {"kind": "tile", **{k: raw[k] for k in ("map_id", "x", "y")}}
    if kind == "exit" and value:
        wanted = value.casefold()
        dest = map_id_for_name(wanted)
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
