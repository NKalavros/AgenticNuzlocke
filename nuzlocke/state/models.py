"""Typed contracts shared by agents, referee, and arbiter."""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class GameMode(str, Enum):
    OVERWORLD = "overworld"
    ENCOUNTER = "encounter"
    BATTLE = "battle"
    BOX = "box"
    MENU = "menu"
    RECOVERY = "recovery"
    WIPED = "wiped"
    PAUSED = "paused"


class AgentRole(str, Enum):
    """Task owners. Encounter legality, box, and team concerns are handled
    as deterministic referee bookkeeping (see NuzlockeReferee / LedgerTracker)
    and Overworld/Battle prompt playbooks, not as separate agent roles."""

    DIRECTOR = "director"
    OVERWORLD = "overworld"
    BATTLE = "battle"
    RECOVERY = "recovery"


class ControlState(str, Enum):
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"


class GameAction(str, Enum):
    PRESS_A = "press_a"
    PRESS_B = "press_b"
    PRESS_START = "press_start"
    PRESS_SELECT = "press_select"
    WALK_UP = "walk_up"
    WALK_DOWN = "walk_down"
    WALK_LEFT = "walk_left"
    WALK_RIGHT = "walk_right"
    # Client-side multi-tile walks (expanded before /action).
    WALK_UP_2 = "walk_up_2"
    WALK_UP_3 = "walk_up_3"
    WALK_UP_4 = "walk_up_4"
    WALK_UP_5 = "walk_up_5"
    WALK_DOWN_2 = "walk_down_2"
    WALK_DOWN_3 = "walk_down_3"
    WALK_DOWN_4 = "walk_down_4"
    WALK_DOWN_5 = "walk_down_5"
    WALK_LEFT_2 = "walk_left_2"
    WALK_LEFT_3 = "walk_left_3"
    WALK_LEFT_4 = "walk_left_4"
    WALK_LEFT_5 = "walk_left_5"
    WALK_RIGHT_2 = "walk_right_2"
    WALK_RIGHT_3 = "walk_right_3"
    WALK_RIGHT_4 = "walk_right_4"
    WALK_RIGHT_5 = "walk_right_5"
    HOLD_A_30 = "hold_a_30"
    HOLD_B_120 = "hold_b_120"
    WAIT_60 = "wait_60"
    A_UNTIL_DIALOG_END = "a_until_dialog_end"
    # Client-side macro: mash B+A through narrative text (not a raw emu opcode).
    SKIP_DIALOG = "skip_dialog"


class LandmarkNote(BaseModel):
    label: str
    note: str


class ObjectivesUpdate(BaseModel):
    primary: str | None = None
    secondary: str | None = None
    tertiary: str | None = None


class TaskEnvelope(BaseModel):
    task_id: str
    owner: AgentRole
    objective: str
    context_refs: list[str] = Field(default_factory=list)
    allowed_tools: list[str] = Field(default_factory=lambda: ["observe", "propose_actions"])
    constraints: list[str] = Field(default_factory=list)
    success: list[str] = Field(default_factory=list)
    abort: list[str] = Field(default_factory=list)


class ActionProposal(BaseModel):
    task_id: str
    agent: AgentRole
    reason: str
    actions: list[GameAction]
    expected: list[str] = Field(default_factory=list)
    risk: Literal["low", "medium", "high"] = "low"
    objectives: ObjectivesUpdate | None = None
    landmarks: list[LandmarkNote] = Field(default_factory=list)


class ArbiterResult(BaseModel):
    proposal_id: str
    status: Literal["approved", "rejected", "partial"]
    executed_actions: list[GameAction] = Field(default_factory=list)
    stopped_early_because: str | None = None
    result_state_ref: str | None = None
    rejection_reason: str | None = None


class DirectorDecision(BaseModel):
    mode: GameMode
    owner: AgentRole
    objective: str
    constraints: list[str] = Field(default_factory=list)
    success: list[str] = Field(default_factory=list)
    abort: list[str] = Field(default_factory=list)
    narration: str = ""
    stop_run: bool = False
    stop_reason: str | None = None


class RecoveryAdvice(BaseModel):
    diagnosis: str
    proposed_actions: list[GameAction] = Field(default_factory=list)
    escalate_to_human: bool = False
    reason: str
    objectives: ObjectivesUpdate | None = None
    landmarks: list[LandmarkNote] = Field(default_factory=list)


class PlayerObservation(BaseModel):
    """Human-assist observation layer (no privileged RNG/hidden IVs)."""

    screenshot_path: str | None = None
    map_name: str | None = None
    map_id: int | None = None
    x: int | None = None
    y: int | None = None
    facing: str | None = None
    dialog_active: bool = False
    dialog_text: str | None = None
    joy_ignore: int = 0
    text_box_id: int | None = None
    input_ready: bool = True
    in_battle: bool = False
    battle: dict[str, Any] | None = None
    party: list[dict[str, Any]] = Field(default_factory=list)
    bag: list[dict[str, Any]] = Field(default_factory=list)
    badges: list[str] = Field(default_factory=list)
    money: int | None = None
    collision_ascii: str | None = None
    frame_count: int | None = None
    raw_player: dict[str, Any] = Field(default_factory=dict)


class RunSummary(BaseModel):
    run_id: str
    status: str
    game: str
    observation_mode: str
    current_mode: GameMode
    current_milestone: str | None = None
    current_cap: int | None = None
    active_task: TaskEnvelope | None = None
    living_party: list[str] = Field(default_factory=list)
    dead_count: int = 0
    encounter_count: int = 0
    last_error: str | None = None


class LLMResponse(BaseModel):
    role: AgentRole
    raw_text: str
    parsed: dict[str, Any] | None = None
    model: str
    provider: str
    usage: dict[str, Any] | None = None
