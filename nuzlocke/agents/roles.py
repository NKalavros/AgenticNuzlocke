"""Role agent helpers."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from nuzlocke.agents import prompts
from nuzlocke.llm.base import LLMProvider
from nuzlocke.state.models import (
    ActionProposal,
    AgentRole,
    DirectorDecision,
    GameAction,
    GameMode,
    LandmarkNote,
    ObjectivesUpdate,
    PlayerObservation,
    RecoveryAdvice,
    TaskEnvelope,
)

_JSON_SEP = (",", ":")


def _images(obs: PlayerObservation) -> list[Path]:
    if obs.screenshot_path and Path(obs.screenshot_path).exists():
        return [Path(obs.screenshot_path)]
    return []


def _dumps(payload: dict[str, Any]) -> str:
    return json.dumps(payload, separators=_JSON_SEP)


def _obs_payload(obs: PlayerObservation, *, vision_only: bool) -> dict[str, Any]:
    if vision_only:
        return {
            "vision_only": True,
            "note": (
                "No RAM / map / coords / collision. "
                "The attached screenshot is the only game state."
            ),
        }
    return {"observation": obs.model_dump(mode="json")}


def _with_extras(
    payload: dict[str, Any],
    *,
    memory: str | None = None,
    walkthrough_hint: str | None = None,
    objectives: dict[str, str] | None = None,
) -> dict[str, Any]:
    if memory and memory.strip():
        payload["memory"] = memory.strip()
    if walkthrough_hint and walkthrough_hint.strip():
        payload["walkthrough_hint"] = walkthrough_hint.strip()
        payload["walkthrough_skill"] = (
            "hint above is the relevant excerpt — do not browse skill files"
        )
    if objectives:
        payload["objectives"] = objectives
    return payload


def parse_objectives(raw: Any) -> ObjectivesUpdate | None:
    if not isinstance(raw, dict):
        return None
    primary = raw.get("primary")
    secondary = raw.get("secondary")
    tertiary = raw.get("tertiary")
    if not any(
        isinstance(v, str) and v.strip() for v in (primary, secondary, tertiary)
    ):
        return None
    return ObjectivesUpdate(
        primary=str(primary).strip() if isinstance(primary, str) and primary.strip() else None,
        secondary=(
            str(secondary).strip()
            if isinstance(secondary, str) and secondary.strip()
            else None
        ),
        tertiary=(
            str(tertiary).strip()
            if isinstance(tertiary, str) and tertiary.strip()
            else None
        ),
    )


def parse_landmarks(raw: Any) -> list[LandmarkNote]:
    if not isinstance(raw, list):
        return []
    out: list[LandmarkNote] = []
    for item in raw[:6]:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "").strip()
        note = str(item.get("note") or "").strip()
        if not label or not note:
            continue
        out.append(LandmarkNote(label=label[:80], note=note[:200]))
    return out


def merge_objectives(
    current: dict[str, str],
    update: ObjectivesUpdate | None,
) -> dict[str, str]:
    if update is None:
        return current
    merged = dict(current)
    if update.primary:
        merged["primary"] = update.primary
    if update.secondary:
        merged["secondary"] = update.secondary
    if update.tertiary:
        merged["tertiary"] = update.tertiary
    return merged


def objectives_for_dashboard(objectives: dict[str, str]) -> list[dict[str, Any]]:
    tiers = ("primary", "secondary", "tertiary")
    out: list[dict[str, Any]] = []
    for tier in tiers:
        text = objectives.get(tier)
        if text:
            out.append({"tier": tier, "text": text, "done": False})
    return out


def decide_director(
    llm: LLMProvider,
    *,
    summary: dict[str, Any],
    obs: PlayerObservation,
    memory: str | None = None,
    vision_only: bool = False,
    walkthrough_hint: str | None = None,
) -> DirectorDecision:
    # Title / intro boot: mash A until RAM reader sees a real map.
    # Still uses RAM for routing even in vision_only (screenshot goes to owner).
    player_name = (obs.raw_player or {}).get("name") or ""
    on_boot = (
        not obs.map_name
        or player_name.strip("?") == ""
        or set(player_name) <= {"?"}
        or (obs.map_name == "Pallet Town" and obs.x == 0 and obs.y == 0 and not obs.party)
    )
    if on_boot and not obs.in_battle:
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
    if obs.in_battle:
        return DirectorDecision(
            mode=GameMode.BATTLE,
            owner=AgentRole.BATTLE,
            objective="Resolve the current battle turn conservatively",
            constraints=["One turn at a time", "No trainer items"],
            abort=["blackout"],
            narration="Battle detected — routing to Battle Agent.",
        )

    stuck = int(summary.get("stuck_score") or 0)
    noop = int(summary.get("noop_streak") or 0)
    # Recovery owns the next vision call — never spend a Director LLM turn too.
    if stuck >= 6 or noop >= 2:
        return DirectorDecision(
            mode=GameMode.RECOVERY,
            owner=AgentRole.RECOVERY,
            objective="Break the stuck/noop loop using screenshot + walkthrough hint",
            constraints=[
                "Max 4 actions",
                "Screenshot is ground truth",
                "Do not repeat the same failed walks",
            ],
            success=[],
            abort=["battle_started"],
            narration=(
                f"Stuck path → recovery (stuck={stuck}, noop={noop}); "
                "no Director LLM."
            ),
        )

    objective = "Make safe progress toward Oak / Viridian / Pewter"
    if not vision_only and obs.map_name and "House" in obs.map_name:
        objective = (
            "If the SCREEN shows overworld, leave the house toward Oak; "
            "if it shows naming/dialog, resolve that first"
        )
    elif vision_only:
        objective = (
            "Read the screenshot only: clear menus/dialog/naming, then "
            "leave home and reach Oak's lab for a starter"
        )
    elif not obs.party:
        objective = "Obtain a starter from Professor Oak (screen-first)"
    return DirectorDecision(
        mode=GameMode.OVERWORLD,
        owner=AgentRole.OVERWORLD,
        objective=objective,
        constraints=[
            "About 1-5 logical actions per prompt; prefer walk_*_3/4 on clear paths",
            "Screenshot is ground truth",
            "Do not walk while a text box or naming grid is visible",
            "Use memory: do not repeat failed walks / false outdoors guesses",
        ],
        success=[],
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
    vision_only: bool = False,
    walkthrough_hint: str | None = None,
    objectives: dict[str, str] | None = None,
) -> ActionProposal:
    user = _dumps(
        _with_extras(
            {
                "task": task.model_dump(mode="json"),
                **_obs_payload(obs, vision_only=vision_only),
            },
            memory=memory,
            walkthrough_hint=walkthrough_hint,
            objectives=objectives,
        )
    )
    system = prompts.OVERWORLD_SYSTEM
    if vision_only:
        system += "\nVISION-ONLY: screenshot is the sole state input.\n"
    resp = llm.complete(
        role=AgentRole.OVERWORLD,
        system=system,
        user=user,
        schema_hint=prompts.OVERWORLD_SCHEMA,
        image_paths=_images(obs),
    )
    data = resp.parsed or {}
    actions_raw = data.get("actions") or ["wait_60"]
    actions: list[GameAction] = []
    for item in actions_raw:
        try:
            actions.append(GameAction(item))
        except ValueError:
            continue
    if not actions:
        actions = [GameAction.WAIT_60]
    return ActionProposal(
        task_id=task.task_id,
        agent=AgentRole.OVERWORLD,
        reason=str(data.get("reason") or resp.raw_text[:300] or "overworld step"),
        actions=actions[:12],
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
    vision_only: bool = False,
    walkthrough_hint: str | None = None,
    objectives: dict[str, str] | None = None,
) -> ActionProposal:
    user = _dumps(
        _with_extras(
            {
                "task": task.model_dump(mode="json"),
                **_obs_payload(obs, vision_only=vision_only),
                "reminder": "ONE battle input only (optional wait_60 after).",
            },
            memory=memory,
            walkthrough_hint=walkthrough_hint,
            objectives=objectives,
        )
    )
    resp = llm.complete(
        role=AgentRole.BATTLE,
        system=prompts.BATTLE_SYSTEM,
        user=user,
        schema_hint=prompts.BATTLE_SCHEMA,
        image_paths=_images(obs),
    )
    data = resp.parsed or {}
    actions_raw = data.get("actions") or ["press_a"]
    actions: list[GameAction] = []
    for item in actions_raw:
        try:
            actions.append(GameAction(item))
        except ValueError:
            continue
    if not actions:
        actions = [GameAction.PRESS_A]
    trimmed: list[GameAction] = []
    for action in actions:
        if len(trimmed) >= 4:
            break
        trimmed.append(action)
    return ActionProposal(
        task_id=task.task_id,
        agent=AgentRole.BATTLE,
        reason=str(data.get("reason") or resp.raw_text[:300] or "battle step"),
        actions=trimmed,
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
    vision_only: bool = False,
    walkthrough_hint: str | None = None,
    objectives: dict[str, str] | None = None,
) -> RecoveryAdvice:
    payload: dict[str, Any] = {
        "stuck_score": stuck_score,
        **_obs_payload(obs, vision_only=vision_only),
    }
    if not vision_only:
        payload["recent_positions"] = recent_positions
    user = _dumps(
        _with_extras(
            payload,
            memory=memory,
            walkthrough_hint=walkthrough_hint,
            objectives=objectives,
        )
    )
    resp = llm.complete(
        role=AgentRole.RECOVERY,
        system=prompts.RECOVERY_SYSTEM,
        user=user,
        schema_hint=prompts.RECOVERY_SCHEMA,
        image_paths=_images(obs),
    )
    data = resp.parsed or {}
    actions: list[GameAction] = []
    for item in data.get("proposed_actions") or ["hold_b_120", "press_a"]:
        try:
            actions.append(GameAction(item))
        except ValueError:
            continue
    return RecoveryAdvice(
        diagnosis=str(data.get("diagnosis") or "unknown"),
        proposed_actions=actions[:4],
        escalate_to_human=bool(data.get("escalate_to_human", stuck_score >= 5)),
        reason=str(data.get("reason") or resp.raw_text[:300]),
        objectives=parse_objectives(data.get("objectives")),
        landmarks=parse_landmarks(data.get("landmarks")),
    )


def rollup_memory(
    llm: LLMProvider,
    *,
    memory: str,
) -> list[str]:
    """Text-only compression of OptMem wake into durable facts (no screenshot)."""
    if not memory.strip():
        return []
    user = _dumps({"memory": memory.strip()[:6000]})
    resp = llm.complete(
        role=AgentRole.DIRECTOR,
        system=prompts.MEMORY_ROLLUP_SYSTEM,
        user=user,
        schema_hint=prompts.MEMORY_ROLLUP_SCHEMA,
        image_paths=None,
    )
    data = resp.parsed or {}
    notes_raw = data.get("notes")
    if not isinstance(notes_raw, list):
        return []
    notes: list[str] = []
    for item in notes_raw[:6]:
        text = " ".join(str(item).split()).strip()
        if text:
            notes.append(text[:200])
    return notes


def make_task(decision: DirectorDecision) -> TaskEnvelope:
    return TaskEnvelope(
        task_id=f"task-{uuid.uuid4().hex[:8]}",
        owner=decision.owner,
        objective=decision.objective,
        constraints=decision.constraints,
        success=decision.success,
        abort=decision.abort,
    )
