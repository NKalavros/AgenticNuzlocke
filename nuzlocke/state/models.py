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
    """Task owners. Encounters, boxes and the team are referee bookkeeping (NuzlockeReferee,
    LedgerTracker) and prompt playbooks, not agent roles."""

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
    # Client-side macro, not an emulator opcode: mash through narrative text.
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
    observation: PlayerObservation | None = Field(default=None, exclude=True)
    # Overworld walks in this burst, each with the tile before and after it.
    walks: list[dict[str, Any]] = Field(default_factory=list)


class PlanScene(str, Enum):
    """What the planner believes is on screen. Jev never sees the pixels."""

    TITLE = "title"
    DIALOG = "dialog"
    NAMING = "naming"
    OVERWORLD = "overworld"
    BATTLE = "battle"
    MENU = "menu"


class BattlePlan(BaseModel):
    """Conditional trainer strategy, with an opening consumed only on observed PP use."""

    moves: list[str] = Field(default_factory=list)
    opening_moves: list[str] = Field(default_factory=list)
    switch_to: str | None = None
    switch_below: float = Field(default=0.3, ge=0, le=1)
    notes: str = ""


class PlanCard(BaseModel):
    """Short plan the fast actor follows until the planner looks again."""

    scene: PlanScene
    see: str
    plan: str
    do_not: list[str] = Field(default_factory=list)
    objectives: ObjectivesUpdate | None = None
    landmarks: list[LandmarkNote] = Field(default_factory=list)
    world_digest: str = ""
    # The screenshot this card was written from had a narrative text box.
    text_box: bool = False
    # Text-region digest when a menu box (YES/NO, a name list) sat above the text box, else "".
    # A different prompt needs a new look.
    prompt_digest: str = ""
    # Buttons still to press. An overworld path is one burst; a menu or the naming grid takes one
    # button per cycle. A failed walk, a text box, or a scene change throws the rest away.
    steps: list[GameAction] = Field(default_factory=list)
    # The cell the planner named (``G7``) and, once stamped, the map tile under it.
    # A map tile stays right while the player walks; a cell does not.
    target_cell: str | None = None
    target: dict[str, Any] | None = None
    # What System 1's goal menu marks as the objective (``agents.goals``), and when it is done.
    goal_target: dict[str, Any] | None = None
    done_when: dict[str, Any] = Field(default_factory=dict)
    # System 2's plan for the current trainer battle: moves in order, and when to switch.
    battle_plan: dict[str, Any] = Field(default_factory=dict)
    battle_context: str | None = None
    route_plan: dict[str, Any] = Field(default_factory=dict)
    # The plan's single button was pressed, or its steps ran out.
    spent: bool = False
    created_at: float = 0.0


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
    # Grid-overlay copy of the same frame, attached to vision calls.
    vision_path: str | None = None
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
    # The map's objects from WRAM (``GET /map/objects``), in map tiles like ``x``/``y``.
    # Empty on a server without that route, or when ``ObjectTrust`` has withheld them.
    warps: list[dict[str, Any]] = Field(default_factory=list)
    signs: list[dict[str, Any]] = Field(default_factory=list)
    npcs: list[dict[str, Any]] = Field(default_factory=list)
    # The 18 tilemap rows as text (``environment.screen_text`` parses them). Letters also appear
    # outside boxes, so they count only when the pixel check sees a text box or menu.
    screen_rows: list[str] = Field(default_factory=list)
    # Map size in tiles and the sides that join another map (Pallet -> Route 1 is "up").
    map_size: dict[str, int] | None = None
    connections: list[str] = Field(default_factory=list)
    # The game is ignoring the D-pad (wJoyIgnore high nibble) or walking the player by script
    # (wStatusFlags5 bit 7). Measured through Oak's escort on Red Star; see AGENTS pitfall #22.
    cutscene: bool = False
    # pokemon-agent's story flags from /state (``has_pokedex``, ...).
    flags: dict[str, Any] = Field(default_factory=dict)
    frame_count: int | None = None
    raw_player: dict[str, Any] = Field(default_factory=dict)
    active_party_slot: int | None = None
    active_mon: dict[str, Any] = Field(default_factory=dict)
    return_map: int | None = None
    battle_result: int | None = None
    battle_lost: bool = False
    battle_style: str | None = None
    menu_index: int | None = None
    menu_scroll: int = 0
    grass_tiles: list[dict[str, int]] = Field(default_factory=list)
    policy: dict[str, Any] = Field(default_factory=dict)


class LLMResponse(BaseModel):
    role: AgentRole
    raw_text: str
    parsed: dict[str, Any] | None = None
    model: str
    provider: str
    usage: dict[str, Any] | None = None
