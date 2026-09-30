"""Main autonomous run loop with dashboard START/PAUSE/STOP."""

from __future__ import annotations

import contextlib
import hashlib
import json
import shutil
import time
import uuid
import webbrowser
from pathlib import Path
from typing import Any

from rich.console import Console

from nuzlocke.agents.goals import DIRS, ObjectTrust, RoomMap, cell_to_tile
from nuzlocke.agents.jev_policy import (
    FrameSignals,
    accepts,
    battle_facts,
    choose_fast_action,
    classify_scene,
    plan_from_recovery,
    reconcile_plan,
)
from nuzlocke.agents.locomotion import GridTrust, next_tile
from nuzlocke.agents.roles import (
    advise_recovery,
    decide_director,
    make_task,
    merge_objectives,
    objectives_for_dashboard,
    propose_battle,
    propose_overworld,
    propose_plan,
    rollup_memory,
)
from nuzlocke.agents.system1 import S1Turn, system1_turn
from nuzlocke.agents.system3 import constraints as nuzlocke_constraints
from nuzlocke.agents.system3 import current_beat, objective_window
from nuzlocke.config import (
    ensure_relay_routing,
    load_agents_config,
    load_project_env,
    load_rules,
    load_run_config,
    project_root,
)
from nuzlocke.environment.joypad import is_naming_lock
from nuzlocke.environment.nous_red import NousRedEnvironment
from nuzlocke.environment.screen import digests_from_path, prompt_box_open, text_box_open
from nuzlocke.environment.screen_text import parse_screen
from nuzlocke.knowledge.walkthrough import excerpt_for_context, skill_dir
from nuzlocke.llm.factory import create_jev, create_provider
from nuzlocke.memory import OptMem
from nuzlocke.orchestration.arbiter import ActionArbiter
from nuzlocke.orchestration.checkpoint import (
    CHECKPOINT_NAME,
    RunCheckpoint,
    should_checkpoint,
    stage_for_boot,
)
from nuzlocke.orchestration.fallback import (
    bridge_down_proposal,
    is_bridge_down,
    llm_error_fallback_proposal,
)
from nuzlocke.orchestration.journal import Journal
from nuzlocke.orchestration.journal import outcome as journal_outcome
from nuzlocke.orchestration.ledger import LedgerTracker
from nuzlocke.orchestration.stuck import StuckTracker
from nuzlocke.referee.rules import NuzlockeReferee
from nuzlocke.state.models import (
    ActionProposal,
    AgentRole,
    ControlState,
    GameAction,
    GameMode,
    PlanCard,
    PlanScene,
    PlayerObservation,
    RecoveryAdvice,
)
from nuzlocke.state.store import EventStore

console = Console()

RECENT_LIMIT = 8
DEFAULT_OBJECTIVES = {
    "primary": "Leave home · get starter from Oak",
    "secondary": "Reach Viridian · resolve Route 1 encounter",
    "tertiary": "Prepare legal team · attempt Brock",
}
# Context keys the battle prompt does not take, and the ones Jev does not take.
OVERWORLD_ONLY = ("failed_approaches", "no_progress", "beat", "blocked_on_tile")
VISION_ONLY = ("vision_only", "walkthrough_hint")
PAGING = ("press_b", "skip_dialog")


def configured_rom(rom_path: Path | None, run_cfg: dict[str, Any]) -> Path | None:
    """``--rom``, else ``rom_path`` from config/run.yaml."""
    if rom_path:
        return rom_path
    return Path(run_cfg["rom_path"]) if run_cfg.get("rom_path") else None


def _install_walkthrough_skill(workspace: Path) -> None:
    """Copy the walkthrough skill into the Cursor agent workspace for on-demand reads."""
    src = skill_dir()
    if not src.is_dir():
        return
    dest = workspace / "skills" / "pokemon-red-walkthrough"
    shutil.rmtree(dest, ignore_errors=True)
    shutil.copytree(src, dest)


def _without(context: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    return {key: value for key, value in context.items() if key not in keys}


def _first_streak(*streaks: tuple[str, int]) -> str | None:
    """``name=count`` for the first nonzero streak."""
    return next((f"{name}={count}" for name, count in streaks if count), None)


# Overworld triggers that wait out a cooldown after a System 2 look: run
# 20260929-030330-de1d51 asked System 2 1,393 times (5.5 of 6.1 hours), 1,200 of them for
# "objective path blocked" or "objective not on this map", one after another.
S2_COOLDOWN_CYCLES = 8
_COOLDOWN_TRIGGERS = {
    "no objective",
    "objective not on this map",
    "objective path blocked",
    "jev unsure twice",
    "goal keeps failing",
}
_EXPLORE = {"kind": "explore"}


def _stamp(card: PlanCard, signals: FrameSignals, obs: PlayerObservation | None = None) -> PlanCard:
    """Record the frame a card was written on, so later cycles can tell what changed."""
    card.world_digest = signals.world_digest
    card.text_box = signals.text_box
    card.prompt_digest = signals.dialog_digest if signals.prompt_box else ""
    tile = cell_to_tile(card.target_cell, obs) if obs is not None else None
    if tile is not None and card.target is None:
        card.target = {"x": tile[0], "y": tile[1], "label": card.target_cell}
    if tile is not None and (card.goal_target or {}).get("kind") == "cell":
        # A cell is only right from where the player stood; a map tile stays right.
        card.goal_target = {
            "kind": "tile",
            "x": tile[0],
            "y": tile[1],
            "label": card.target_cell,
            "map_id": obs.map_id,
        }
    return card


class RunLoop:
    def __init__(
        self,
        *,
        rom_path: Path | None,
        run_id: str | None = None,
        resume: bool = False,
        provider_override: str | None = None,
        vision_only: bool | None = None,
        port: int | None = None,
        headless: bool = False,
    ) -> None:
        if resume and not run_id:
            raise ValueError("resume=True requires an existing run_id")
        load_project_env()
        ensure_relay_routing()
        self.root = project_root()
        self.run_cfg = load_run_config()
        self.agents_cfg = load_agents_config()
        if provider_override:
            self.agents_cfg["provider"] = provider_override
        self.rules = load_rules()
        self.run_id = run_id or time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
        self.run_dir = self.root / "runs" / self.run_id
        self.store = EventStore(self.run_dir)
        rom = configured_rom(rom_path, self.run_cfg)
        identity = {
            "rom": hashlib.sha256(rom.read_bytes()).hexdigest() if rom else None,
            "rules": hashlib.sha256(json.dumps(self.rules, sort_keys=True).encode()).hexdigest(),
        }
        self.integrity = RunCheckpoint(self.run_dir, identity)
        restored = None
        if resume:
            if headless and (self.run_dir / "sandbox.json").exists():
                paired = self.run_dir / "sandbox-controller.json"
                if paired.exists():
                    record = json.loads(paired.read_text())
                    if record.get("identity") != identity:
                        raise RuntimeError("Sandbox source uses a different ROM or rules")
                    restored = record["controller"]
                    restored["cycle"] = 0  # --steps is the diagnostic's budget.
            else:
                restored = self.integrity.load()
                from nuzlocke.orchestration.checkpoint import IntegrityError

                if restored.get("integrity_head") != self.store.integrity_head(verify=True):
                    raise IntegrityError("Checkpoint does not match the latest rule-event history")
                if restored.get("referee", {}).get("wiped"):
                    raise IntegrityError("This run ended in a wipe; inspect it with sandbox --from")
            stage_for_boot(self.run_dir)
        self.referee = NuzlockeReferee(self.rules)
        self.vision_only = bool(
            self.run_cfg.get("vision_only", False) if vision_only is None else vision_only
        )
        rom = configured_rom(rom_path, self.run_cfg)
        pa = self.run_cfg.get("pokemon_agent") or {}
        base_url = f"http://{pa.get('host', '127.0.0.1')}:{int(port or pa.get('port', 8765))}"
        # A headless loop owns its emulator: no dashboard START, no browser,
        # and the server it started is stopped when the loop ends.
        self.headless = headless
        self.dashboard_url = f"{base_url}/dashboard"
        self.navigation_url = f"{base_url}/navigation"
        self.env = NousRedEnvironment(
            base_url=base_url,
            run_dir=self.run_dir,
            rom_path=rom,
            auto_start=headless or bool(pa.get("auto_start", True)),
            speed=int(pa.get("speed", 4)),
            press_interval_s=float(self.run_cfg.get("press_interval_s", 0.1)),
            load_state=CHECKPOINT_NAME if resume else None,
        )
        if resume:
            self.env.publish_savestate(CHECKPOINT_NAME)
            self.env.load_checkpoint(CHECKPOINT_NAME)
        control = self.run_cfg.get("control") or {}
        self.arbiter = ActionArbiter(
            self.env, self.store, max_actions=int(control.get("max_actions_per_proposal", 12))
        )
        workspace = self.run_dir / "agent_workspace"
        try:
            self.llm = create_provider(
                self.agents_cfg,
                workspace=workspace,
                on_stream=lambda text: self.env.push_event("reasoning", text),
            )
        except Exception:
            self.env.shutdown()
            raise
        self.jev = create_jev(self.agents_cfg)
        planner_cfg = self.agents_cfg.get("planner") or {}
        self.plan_every_s = float(planner_cfg.get("plan_every_s", 45))
        self.stale_noul = float(planner_cfg.get("stale_noul", 0.7))
        self.confidence_floor = float(planner_cfg.get("confidence_floor", 0.55))
        self.plan: PlanCard | None = None
        self._low_confidence_streak = 0
        self._prev_world: str | None = None
        self._prev_dialog: str | None = None
        _install_walkthrough_skill(workspace)
        self.stuck = StuckTracker()
        self.grid_trust = GridTrust()
        self.object_trust = ObjectTrust()
        # System 1: the map it has walked, goals that went nowhere, and the log System 2 reads.
        self.room = RoomMap()
        from nuzlocke.agents.navigation import Navigator

        self.navigator = Navigator()
        self.journal = Journal(self.run_dir / "journal.jsonl")
        self._goal_fails: dict[str, int] = {}
        # The text each goal ended in last time on this map, shown on its option.
        self._goal_texts: dict[str, str] = {}
        self._s1: S1Turn | None = None
        self._last_look = -S2_COOLDOWN_CYCLES
        self._last_direction: str | None = None
        # Move -> type, read from the battle TYPE/ box as each move is highlighted.
        self.move_types: dict[str, str] = {}
        self.ledger = LedgerTracker(self.referee)
        # Short-term prompt context; OptMem keeps landmarks and rollups.
        self.recent_steps: list[dict[str, Any]] = []
        self.prompt_interval_s = max(0.0, float(self.run_cfg.get("prompt_interval_s", 1.5)))
        mem_cfg = self.run_cfg.get("memory") or {}
        self.memory = OptMem(
            self.run_dir / "memory",
            wake_lines=int(mem_cfg.get("wake_lines", 24)),
            enabled=bool(mem_cfg.get("enabled", True)),
        )
        self.rollup_every = max(0, int(mem_cfg.get("rollup_every", 25)))
        checkpoint_cfg = self.run_cfg.get("checkpoint") or {}
        self.checkpoint_every_steps = (
            max(0, int(checkpoint_cfg.get("every_steps", 50)))
            if checkpoint_cfg.get("enabled", True)
            else 0
        )
        self._last_ledger_change_step = -1000
        self._last_recovery_step = -1
        self.objectives = self._seed_objectives()
        self._beat_locked = False
        self._beat_id: str | None = None
        self._prompt_beat: str | None = None
        self._beat_heading: str | None = None
        if self.memory.enabled:
            self.memory.note(
                f"Run {self.run_id} {'resumed' if resume else 'started'}; "
                f"game={self.run_cfg.get('game')}; vision_only={self.vision_only}; "
                f"rom={Path(rom).name if rom else 'none'}; "
                "Red Star: trust screenshot; avoid up/down outdoor hallucination loops"
            )
        self._cycle = 0
        self._cached_observation = None
        self._preparing_target = None
        self._closing_preparation = False
        self._starter_seen = None
        self._pending_move = None
        from nuzlocke.agents.move_learning import MoveLearner

        self.move_learner = MoveLearner()
        from nuzlocke.agents.lead_rotation import LeadRotation

        self.lead_rotation = LeadRotation()
        from nuzlocke.agents.shop import ShopController

        self.shop = ShopController()
        self._rejected_starters = set()
        self._previous_party = []
        self._encounter_search_counts = {}
        self._encounter_tables = {}
        self._grass_visits = {}
        self._last_search_cycle = None
        if restored:
            self._restore_controller(restored)
        self.env.on_before_action = self.integrity.begin
        self.env.on_transition = self._ingest
        self.arbiter.policy = lambda obs: self._policy(obs)
        if not resume:
            self._write_manifest(rom)

    def _ingest(self, obs: PlayerObservation) -> None:
        """Observe irreversible outcomes at every actual emulator advancement."""
        self.referee.advance(len(obs.badges))
        if obs.wild_species and not obs.in_battle and not obs.cutscene:
            self._encounter_tables[str(obs.map_id)] = obs.wild_species
        if self._pending_move and self.plan:
            slot, name, old_pp = self._pending_move
            mon = obs.party[slot] if slot < len(obs.party) else {}
            current = next(
                (m.get("pp") for m in mon.get("moves", []) if str(m.get("name")).upper() == name),
                None,
            )
            if current is not None and current < old_pp:
                opening = self.plan.battle_plan.get("opening_moves", [])
                if opening and opening[0].upper() == name:
                    opening.pop(0)
                self._pending_move = None
                self.store.append("battle_plan_advanced", {"move": name})
        if obs.in_battle and obs.active_mon and obs.active_party_slot is not None:
            slot = obs.active_party_slot
            if 0 <= slot < len(obs.party) and obs.active_mon.get("species") == obs.party[slot].get(
                "species"
            ):
                obs.party[slot].update(obs.active_mon)
        if self.ledger.update(obs, step=self._cycle):
            self._last_ledger_change_step = self._cycle
            self.store.append("ledger_commit", self.referee.snapshot())
        self.referee.identify(obs)
        if getattr(self, "move_learner", None) is not None:
            self.move_learner.observe(obs, self.store.append)
        if getattr(self, "lead_rotation", None) is not None:
            self.lead_rotation.observe(obs, self.store.append)
        if getattr(self, "shop", None) is not None:
            try:
                self.shop.observe(obs, self.store.append)
            except RuntimeError as err:
                self.shop.error = str(err)
        if self._preparing_target and not obs.in_battle:
            previous = {m.get("capture_id"): m for m in self._previous_party}
            for mon in obs.party:
                old = previous.get(mon.get("capture_id"))
                if old and mon.get("level", 0) > old.get("level", 0):
                    self.store.append(
                        "candy_use",
                        {
                            "capture_id": mon["capture_id"],
                            "before": old["level"],
                            "after": mon["level"],
                            "target": self._preparing_target,
                        },
                    )
                    if mon["level"] > self._preparing_target or mon.get("dead"):
                        raise RuntimeError("candy preparation violated its authorization")
        self._previous_party = [dict(m) for m in obs.party]
        preparation = self.run_cfg.get("rare_candy") or {}
        if "Boulder" in obs.badges:
            setting = "misty_level" if obs.map_id in {3, 64, 65, 35, 36} else "post_brock_level"
            default = 21 if setting == "misty_level" else 18
        else:
            setting = "brock_level" if obs.map_id in {2, 54, 58} else "first_center_level"
            default = 14 if setting == "brock_level" else 12
        target = int(preparation.get(setting, default)) if preparation.get("enabled") else 0
        obs.policy.update(
            preparation_target=min(target, self._preparation_limit()),
            level_cap=self.referee.current_cap,
            level_cap_buffer=int(self.run_cfg.get("level_cap_buffer", 1)),
            first_encounter=self.ledger.first_encounter,
            duplicate_encounter=self.ledger.duplicate_encounter,
            avoid_wild_grinding=bool((self.run_cfg.get("rare_candy") or {}).get("enabled")),
            wiped=self.referee.wiped,
            preparing=bool(self._preparing_target),
        )
        if self.referee.wiped:
            self.env.terminal = True
            return

    def _policy(self, obs):
        from nuzlocke.agents.policy import decision

        self.referee.identify(obs)
        if getattr(self, "move_learner", None) is not None:
            actions = self.move_learner.actions(obs)
            if actions is not None:
                obs.policy["learning_actions"] = [a.value for a in actions]
        if getattr(self, "lead_rotation", None) is not None:
            actions = self.lead_rotation.actions(obs)
            if actions is not None:
                obs.policy["rotation_actions"] = [a.value for a in actions]
        if getattr(self, "shop", None) is not None:
            actions = self.shop.actions(obs)
            if actions is not None:
                obs.policy["shop_actions"] = [a.value for a in actions]
        obs.policy.update(
            level_cap=self.referee.current_cap,
            level_cap_buffer=int(self.run_cfg.get("level_cap_buffer", 1)),
            first_encounter=self.ledger.first_encounter,
            duplicate_encounter=self.ledger.duplicate_encounter,
            avoid_wild_grinding=bool((self.run_cfg.get("rare_candy") or {}).get("enabled")),
            preparing=bool(self._preparing_target),
            wiped=self.referee.wiped,
        )
        return decision(obs, first_encounter=self.ledger.first_encounter)

    def _preparation_limit(self):
        from nuzlocke.agents.level_buffer import preparation_limit

        return preparation_limit(
            self.referee.current_cap, int(self.run_cfg.get("level_cap_buffer", 1))
        )

    def _controller_snapshot(self) -> dict:
        def tiles(data):
            return {str(k): [[*tile, value] for tile, value in v.items()] for k, v in data.items()}

        return {
            "integrity_head": self.store.integrity_head(),
            "referee": self.referee.snapshot(),
            "ledger": self.ledger.snapshot(),
            "cycle": self._cycle,
            "plan": self.plan.model_dump(mode="json") if self.plan else None,
            "objectives": self.objectives,
            "move_types": self.move_types,
            "preparing_target": self._preparing_target,
            "closing_preparation": self._closing_preparation,
            "starter_seen": self._starter_seen,
            "pending_move": self._pending_move,
            "move_learning": self.move_learner.snapshot(),
            "shop": self.shop.snapshot() if getattr(self, "shop", None) else None,
            "evolution_waits": getattr(self, "_evolution_waits", 0),
            "lead_rotation": self.lead_rotation.snapshot()
            if getattr(self, "lead_rotation", None)
            else None,
            "rejected_starters": list(self._rejected_starters),
            "previous_party": self._previous_party,
            "encounter_search_counts": self._encounter_search_counts,
            "encounter_tables": self._encounter_tables,
            "grass_visits": self._grass_visits,
            "navigation": self.navigator.snapshot(),
            "room": {
                "known": tiles(self.room.known),
                "blocked": tiles(self.room._blocked),
                "visited": {str(k): list(v) for k, v in self.room.visited.items()},
                "cycle": self.room.cycle,
                "edge_blocks": {
                    str(k): [[*edge, at] for edge, at in v.items()]
                    for k, v in self.room.edge_blocks.items()
                },
                "crossed_edges": {str(k): list(v) for k, v in self.room.crossed_edges.items()},
                "terrain_tiles": tiles(self.room.terrain_tiles),
            },
            "grid_trust": self.grid_trust._counts,
            "object_trust": self.object_trust._counts,
            "grid_confirmed": self.grid_trust._confirmed,
            "object_confirmed": self.object_trust._confirmed,
        }

    def _restore_controller(self, data: dict) -> None:
        self.referee.restore(data["referee"])
        self.ledger.restore(data["ledger"])
        self._cycle = data["cycle"]
        self.plan = PlanCard.model_validate(data["plan"]) if data.get("plan") else None
        self.objectives = data["objectives"]
        self.move_types = data["move_types"]
        self._preparing_target = data.get("preparing_target")
        self._closing_preparation = data.get("closing_preparation", False)
        self._starter_seen = data.get("starter_seen")
        self._pending_move = data.get("pending_move")
        self.move_learner.restore(data.get("move_learning"))
        self._evolution_waits = data.get("evolution_waits", 0)
        if getattr(self, "shop", None) is not None:
            self.shop.restore(data.get("shop"))
        if getattr(self, "lead_rotation", None) is not None:
            self.lead_rotation.restore(data.get("lead_rotation"))
        self._previous_party = data.get("previous_party", [])
        self._encounter_search_counts = data.get("encounter_search_counts", {})
        self._encounter_tables = data.get("encounter_tables", {})
        self._grass_visits = data.get("grass_visits", {})
        self._rejected_starters = {tuple(t) for t in data.get("rejected_starters", [])}

        def key(k):
            return int(k) if str(k).isdigit() else k

        room = data["room"]
        self.room.known = {
            key(k): {(x, y): v for x, y, v in rows} for k, rows in room["known"].items()
        }
        self.room._blocked = {
            key(k): {(x, y): v for x, y, v in rows} for k, rows in room["blocked"].items()
        }
        self.room.visited = {
            key(k): {tuple(t) for t in rows} for k, rows in room["visited"].items()
        }
        self.room.cycle = room["cycle"]
        self.room.edge_blocks = {
            key(k): {(x, y, d): at for x, y, d, at in rows}
            for k, rows in room.get("edge_blocks", {}).items()
        }
        self.room.crossed_edges = {
            key(k): {tuple(edge) for edge in rows}
            for k, rows in room.get("crossed_edges", {}).items()
        }
        self.room.terrain_tiles = {
            key(k): {(x, y): tuple(value) for x, y, value in rows}
            for k, rows in room.get("terrain_tiles", {}).items()
        }
        self.navigator.restore(data.get("navigation", {}))
        self.grid_trust._counts = {key(k): v for k, v in data["grid_trust"].items()}
        self.object_trust._counts = {key(k): v for k, v in data["object_trust"].items()}
        self.grid_trust._confirmed = {key(k): v for k, v in data.get("grid_confirmed", {}).items()}
        self.object_trust._confirmed = {
            key(k): v for k, v in data.get("object_confirmed", {}).items()
        }

    def _intervention(self, obs, task):
        from nuzlocke.agents.preparation import preparation_turn
        from nuzlocke.environment.evolution import evolution_phase

        self._evolution_waits = (
            getattr(self, "_evolution_waits", 0) + 1
            if evolution_phase(obs.screen_rows) == "animation"
            else 0
        )
        if self._evolution_waits > 30:
            raise RuntimeError(
                "Evolution screen did not finish after 30 wait cycles; paused for inspection"
            )

        if getattr(self, "move_learner", None) is not None:
            actions, reason = self.move_learner.turn(
                obs,
                decide=self.jev.decide if self.jev else None,
                record=self.store.append,
                confidence_floor=self.confidence_floor,
            )
            if actions:
                return ActionProposal(
                    task_id=task.task_id, agent=task.owner, actions=actions, reason=reason
                )
        if getattr(self, "shop", None) is not None:
            actions, reason = self.shop.turn(obs, record=self.store.append)
            if actions:
                return ActionProposal(
                    task_id=task.task_id, agent=task.owner, actions=actions, reason=reason
                )
        from nuzlocke.agents.gym_preparation import at_leader, needs_top_up

        if (
            not (at_leader(obs) and needs_top_up(obs))
            and getattr(self, "lead_rotation", None) is not None
            and not self._preparing_target
            and not self._closing_preparation
        ):
            actions, reason = self.lead_rotation.turn(obs, record=self.store.append)
            if actions:
                return ActionProposal(
                    task_id=task.task_id, agent=task.owner, actions=actions, reason=reason
                )
        actions, reason = preparation_turn(self, obs)
        if actions:
            return ActionProposal(
                task_id=task.task_id, agent=task.owner, actions=actions, reason=reason
            )
        return None

    def _seed_objectives(self) -> dict[str, str]:
        texts: list[str] = []
        for item in self.run_cfg.get("milestones") or []:
            if isinstance(item, dict) and item.get("description"):
                texts.append(str(item["description"]).strip())
            elif isinstance(item, str):
                texts.append(item.strip())
        texts += [""] * len(DEFAULT_OBJECTIVES)
        return {key: texts[i] or text for i, (key, text) in enumerate(DEFAULT_OBJECTIVES.items())}

    def _nuzlocke_state(self) -> dict[str, Any]:
        return {
            "cap": self.referee.current_cap,
            "milestone": self.referee.current_milestone,
            "dead": [entry.get("nickname") for entry in self.referee.death_ledger],
            "frozen_encounters": dict(self.referee.encounter_ledger),
        }

    def _write_manifest(self, rom: Path | None) -> None:
        manifest = {
            "run_id": self.run_id,
            "game": self.run_cfg.get("game"),
            "observation_mode": self.run_cfg.get("observation_mode"),
            "vision_only": self.vision_only,
            "memory_enabled": self.memory.enabled,
            "rom_path": str(rom) if rom else None,
            "provider": self.agents_cfg.get("provider"),
            "model": self._manifest_model(),
            "rules": self.rules,
        }
        (self.run_dir / "manifest.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )
        self.store.set_meta("manifest", manifest)

    def _manifest_model(self) -> Any:
        provider = self.agents_cfg.get("provider")
        if provider == "dual":
            planner = self.agents_cfg.get("planner") or {}
            return {
                "planner": {"id": planner.get("model"), "params": planner.get("params")},
                "jev": (self.agents_cfg.get("jev") or {}).get("model"),
            }
        if provider == "cursor":
            cursor = self.agents_cfg.get("cursor") or {}
            return {"id": cursor.get("model"), "params": cursor.get("params")}
        return (self.agents_cfg.get("openai_compatible") or {}).get("model")

    def _publish_navigation(self, obs: PlayerObservation) -> None:
        from nuzlocke.referee.type_chart import types_for_species

        from nuzlocke.knowledge.encounters import coverage

        payload = self.navigator.context(obs, self.room, self._objective(obs)[0])
        payload.update(
            run_id=self.run_id,
            cycle=self._cycle,
            in_battle=obs.in_battle,
            party=[
                {**m, "types": list(types_for_species(m.get("species", ""))) or m.get("types", [])}
                for m in obs.party
            ],
            badges=obs.badges,
            encounters=coverage(self),
            updated_at=time.time(),
        )
        self.env.publish_navigation(payload)

    def _publish_objectives(self) -> None:
        dash = objectives_for_dashboard(self.objectives)
        if dash:
            self.env.set_objectives(dash)

    def _wait_until_running(self) -> ControlState:
        control = self.run_cfg.get("control") or {}
        if self.headless or not control.get("respect_dashboard_control", True):
            self.env.set_control(ControlState.RUNNING)
            return ControlState.RUNNING
        console.print(f"[cyan]Dashboard:[/cyan] {self.dashboard_url}")
        console.print("[yellow]Press START on the dashboard (or we wait on /control).[/yellow]")
        # A leftover STOP from the previous session is not a request to quit
        # this one. Only RUNNING begins the run; Ctrl-C aborts the wait.
        while self.env.get_control() != ControlState.RUNNING:
            time.sleep(float(control.get("poll_interval_s", 0.5)))
        return ControlState.RUNNING

    def run(self, *, max_steps: int | None = None) -> None:
        self.store.append("run_start", {"run_id": self.run_id})
        flags = (" · vision-only" if self.vision_only else "") + (
            " · OptMem on" if self.memory.enabled else ""
        )
        self.env.push_event(
            "key_moment",
            f"Nuzlocke run {self.run_id} live — watch Field Log + game stage{flags}",
            category="milestone",
        )
        self._publish_objectives()
        console.print(f"[bold cyan]Watch live:[/bold cyan] {self.dashboard_url}")
        console.print(f"[bold cyan]Route monitor:[/bold cyan] {self.navigation_url}")
        console.print("[dim]Cursor agents: Agents panel → Filter → Source → SDK[/dim]")
        if not self.headless:
            with contextlib.suppress(Exception):
                webbrowser.open(self.navigation_url)
        self._wait_until_running()

        steps = self._cycle
        while max_steps is None or steps < max_steps:
            control = self.env.get_control()
            if control == ControlState.STOPPED:
                console.print("[red]STOP from dashboard.[/red]")
                break
            if control == ControlState.PAUSED:
                time.sleep(0.5)
                continue

            cycle_started = time.time()
            self._cycle = steps
            # Even a cached atomic read can be mid-transition; settle before decisions.
            raw_obs = self.env.observe()
            self._cached_observation = None
            self._ingest(raw_obs)
            # Prompts and the step picker see the grid only while this map's
            # grid has matched real movement. The event log keeps the raw read.
            obs = self.object_trust.view(self.grid_trust.view(raw_obs))
            locked = obs.in_battle or is_naming_lock(obs.joy_ignore)
            speech = not locked and text_box_open(obs.screenshot_path)
            controllable = not locked and not speech
            console.print(
                "[dim]speech on screen[/dim]"
                if speech
                else f"[dim]map={obs.map_name} battle={obs.in_battle}[/dim]"
            )
            self.store.append("observation", raw_obs.model_dump(mode="json"))
            self._publish_navigation(obs)
            if obs.cutscene or self._cutscene_screen(obs):
                self.stuck.pause_for_cutscene()
            self.stuck.update_position(obs)
            self.referee.advance(len(obs.badges))
            if self.ledger.update(obs, step=steps):
                self._last_ledger_change_step = steps
            if self.referee.wiped:
                # A Nuzlocke ends when the whole party is gone. Keep the savestate to look at.
                self.store.append("nuzlocke_wipe", {"reason": self.referee.wiped, "step": steps})
                self.env.push_event("alert", f"Nuzlocke lost: {self.referee.wiped}")
                console.print(f"[red]Nuzlocke lost: {self.referee.wiped}. Stopping.[/red]")
                break
            stop_after = self.run_cfg.get("stop_after", "brock")
            stop_badge = {"brock": "Boulder", "misty": "Cascade"}.get(stop_after)
            if stop_badge and stop_badge in obs.badges:
                self.store.append("milestone_complete", {"milestone": stop_after, "step": steps})
                self.integrity.commit(self.env, self._controller_snapshot())
                break
            violations = self.referee.assert_party_legal(obs)
            if violations:
                self.env.push_event("alert", "; ".join(violations))
                # Carrying an ineligible Pokémon is legal; using it in a later battle is not.
                self.store.append("party_ineligible", {"violations": violations})

            stuck = self.stuck
            hint = _first_streak(
                ("noop_streak", stuck.noop_streak),
                ("loop_streak", stuck.loop_streak),
                ("no_progress_streak", stuck.no_progress_streak),
            )
            summary = {
                "run_id": self.run_id,
                "cap": self.referee.current_cap,
                "stuck_score": stuck.stuck_score,
                "noop_streak": stuck.noop_streak,
                "loop_streak": stuck.loop_streak,
                "no_progress_streak": stuck.no_progress_streak,
                "deaths": len(self.referee.death_ledger),
                "encounters": self.referee.encounter_ledger,
                "vision_only": self.vision_only,
                "hint": hint,
            }
            memory_text = self.memory.wake()
            beat_hint = self._sync_beats(obs, controllable=controllable)
            walkthrough_hint = beat_hint
            if stuck.needs_guide():
                # The RAM map name picks the section; the model still does not see RAM.
                excerpt = excerpt_for_context(
                    map_name=obs.map_name, reason=hint or "", memory=memory_text
                )
                if excerpt:
                    walkthrough_hint = f"{beat_hint}\n\n{excerpt}" if beat_hint else excerpt
                if walkthrough_hint:
                    self.env.push_event("reasoning", "[walkthrough] injected stuck-helper excerpt")
            # A few B presses page a real line. After that the beat stays the
            # objective, or the model is told the only task is "someone is
            # speaking" and it pages a book forever.
            paged_out = self._pages() >= 4
            decision = decide_director(
                self.llm,
                summary=summary,
                obs=obs,
                memory=memory_text,
                vision_only=self.vision_only,
                walkthrough_hint=walkthrough_hint,
                speech=speech and not paged_out,
            )
            self.store.append("director", decision.model_dump(mode="json"))
            if decision.narration:
                self.env.push_event("reasoning", f"[director] {decision.narration}")
            self.env.push_event(
                "decision",
                f"mode={decision.mode.value} owner={decision.owner.value} → {decision.objective}",
            )
            if decision.stop_run:
                console.print(f"[red]Director stopped run: {decision.stop_reason}[/red]")
                break

            task = make_task(decision)
            self.arbiter.set_owner(task.owner)
            # The director's goal fills primary only when the agent has not set one.
            if "primary" not in self.objectives and decision.objective:
                self.objectives["primary"] = decision.objective
            self._publish_objectives()

            used_recovery = pause = False
            # Set again when System 1 proposes; a disengage or Recovery press is not its turn.
            self._s1 = None
            try:
                proposal, used_recovery, pause = self._select_proposal(
                    tier=stuck.escalation_tier(),
                    decision=decision,
                    task=task,
                    obs=obs,
                    steps=steps,
                    context=self._context(memory_text, walkthrough_hint),
                )
            except Exception as err:
                proposal = self._fallback_proposal(task, err)
            if pause:
                continue

            if self._s1 and self._s1.choice.startswith("move_"):
                from nuzlocke.agents.battle import active_mon, parse_battle

                screen = parse_battle(obs.screen_rows)
                index = int(self._s1.choice.removeprefix("move_"))
                if index < len(screen.options):
                    name = screen.options[index].upper()
                    pp = next(
                        (
                            m.get("pp")
                            for m in active_mon(obs).get("moves", [])
                            if str(m.get("name")).upper() == name
                        ),
                        None,
                    )
                    if pp is not None:
                        self._pending_move = (obs.active_party_slot or 0, name, pp)
            self._apply_proposal_meta(proposal)
            announce = f"[{proposal.agent.value}] {proposal.reason} → {[a.value for a in proposal.actions]}"
            self.env.push_event("decision", announce)
            console.print(f"[magenta]next[/magenta] {announce}")
            before_fp = stuck.fingerprint(obs)
            if self.env.get_control() == ControlState.STOPPED:
                if self.integrity.pending.exists():
                    self.integrity.commit(self.env, self._controller_snapshot())
                break
            result = self.arbiter.apply(proposal)
            after = result.observation or self.env.observe()
            self._ingest(after)
            self._cached_observation = after
            after_fp = stuck.fingerprint(after)
            executed = [a.value for a in result.executed_actions]
            after_box = text_box_open(after.screenshot_path)
            is_noop = stuck.record_result(
                before_fp,
                after_fp,
                executed=bool(executed),
                actions=executed or None,
                allow_immobile=controllable
                and not after.in_battle
                and not is_naming_lock(after.joy_ignore)
                and not after_box,
            )
            if result.walks:
                grid_disagreed = self.grid_trust.record_path(raw_obs, result.walks)
            else:
                grid_disagreed = self.grid_trust.record(raw_obs, after, executed)
            if self.object_trust.record(raw_obs, after, result.walks):
                self.env.push_event(
                    "alert",
                    f"warp table for {raw_obs.map_name or 'this map'} disagrees with where "
                    "the map changed; its doors and NPCs are withheld from now on",
                )
                self.store.append(
                    "objects_untrusted", {"map": raw_obs.map_name, "map_id": raw_obs.map_id}
                )
            if grid_disagreed:
                self.env.push_event(
                    "alert",
                    f"walk grid for {after.map_name or 'this map'} disagrees with "
                    "where the player walked; it is withheld from now on",
                )
                self.store.append("grid_untrusted", {"map": after.map_name, "map_id": after.map_id})
                self.room.known.pop(after.map_id, None)
            if used_recovery and not is_noop:
                stuck.discount(2)
            if is_noop:
                self.env.push_event(
                    "alert", f"noop x{stuck.noop_streak}: actions did not change screen/state"
                )
                walked = any(label.startswith("walk_") for label in executed)
                if self.memory.enabled and stuck.noop_streak >= 3 and walked:
                    noted = self.memory.note("ANTI do not repeat: " + " ".join(executed))
                    if noted:
                        self.env.push_event("reasoning", noted)
            elif stuck.loop_streak >= 3:
                self.env.push_event(
                    "alert", f"loop x{stuck.loop_streak}: oscillating walks or tiles"
                )
            elif stuck.last_immobile:
                self.env.push_event(
                    "alert",
                    f"immobile x{stuck.immobile_streak}: {' '.join(executed)} did not change the tile",
                )
            elif stuck.no_progress_streak >= 3:
                self.env.push_event(
                    "alert",
                    f"no_progress x{stuck.no_progress_streak}: only text changed, the world did not",
                )
            stopped = result.stopped_early_because
            self.env.push_event(
                "action", f"{result.status}: {executed}" + (f" ({stopped})" if stopped else "")
            )
            tag = _first_streak(
                ("immobile", stuck.immobile_streak if stuck.last_immobile else 0),
                ("noop", stuck.noop_streak),
                ("loop", stuck.loop_streak),
            )
            console.print(
                f"[green]step {steps}[/green] {task.owner.value} -> {result.status} {executed}"
                + (f" [{tag}]" if tag else "")
            )
            if (before_fp.map_name, before_fp.x, before_fp.y) == (
                after_fp.map_name,
                after_fp.x,
                after_fp.y,
            ):
                for label in executed:
                    stuck.press_counts[label] = stuck.press_counts.get(label, 0) + 1
            else:
                stuck.press_counts.clear()
            self._after_system1(raw_obs, after, result, executed, after_box, steps)
            # Label honestly: a history of "ok" on every looping step reads as success.
            if stuck.last_immobile:
                outcome = f"immobile x{stuck.immobile_streak}"
            elif after_box and any(label in PAGING for label in executed):
                outcome = f"paging x{self._pages()}"
            elif stuck.noop_streak:
                outcome = f"noop x{stuck.noop_streak}"
            elif stuck.no_progress_streak:
                outcome = f"no_progress x{stuck.no_progress_streak}"
            else:
                outcome = stopped or "ok"
            self.recent_steps.append(
                {
                    "step": steps,
                    "agent": proposal.agent.value,
                    "actions": executed[:8],
                    "outcome": outcome,
                    "reason": (proposal.reason or "")[:160],
                }
            )
            self.recent_steps = self.recent_steps[-RECENT_LIMIT:]
            steps += 1
            self._maybe_rollup_memory(steps=steps, in_battle=after.in_battle)
            self._cycle = steps
            self.integrity.commit(self.env, self._controller_snapshot())
            remaining = self.prompt_interval_s - (time.time() - cycle_started)
            if remaining > 0:
                time.sleep(remaining)
        if self.integrity.pending.exists() and (
            self._cached_observation is not None or self.referee.wiped
        ):
            self.integrity.commit(self.env, self._controller_snapshot())
        self.store.append("run_end", {"run_id": self.run_id, "steps": steps})
        self.close()

    def _context(self, memory: str | None, walkthrough_hint: str | None) -> dict[str, Any]:
        """Keyword arguments the role prompts share."""
        return {
            "memory": memory,
            "recent": list(self.recent_steps),
            "vision_only": self.vision_only,
            "walkthrough_hint": walkthrough_hint,
            "objectives": self.objectives,
            "nuzlocke": self._nuzlocke_state(),
            "failed_approaches": [list(item) for item in self.stuck.failed_approaches] or None,
            "no_progress": self._no_progress_context(),
            "beat": self._prompt_beat,
            "blocked_on_tile": sorted(self.stuck.blocked_on_tile),
        }

    def _fallback_proposal(self, task: Any, err: Exception) -> ActionProposal:
        self.store.append("llm_error", {"error": str(err), "owner": task.owner.value})
        if getattr(self, "jev", None) is not None:
            self.env.set_control(ControlState.PAUSED)
            self.env.push_event(
                "alert",
                f"Planning unavailable; paused. Restore the connection and press START: {err}",
            )
            console.print(f"[yellow]Planning unavailable; paused:[/yellow] {err}")
            proposal = ActionProposal(
                task_id=task.task_id,
                agent=task.owner,
                actions=[GameAction.WAIT_60],
                reason="planning unavailable; pause and preserve checkpoint",
            )
            self.arbiter.set_owner(proposal.agent)
            return proposal
        if is_bridge_down(err):
            self.env.push_event(
                "alert", f"Cursor bridge down — waiting (keep Cursor app open): {err}"
            )
            console.print(
                "[red]Cursor SDK bridge connection refused.[/red] "
                "Keep the Cursor app open, then the run will retry."
            )
            time.sleep(8.0)
            proposal = bridge_down_proposal(task)
        else:
            self.env.push_event("alert", f"LLM error (fallback macro): {err}")
            console.print(f"[yellow]LLM error, using fallback macro:[/yellow] {err}")
            proposal = llm_error_fallback_proposal(task)
        self.arbiter.set_owner(proposal.agent)
        return proposal

    def _select_proposal(
        self,
        *,
        tier: int,
        decision: Any,
        task: Any,
        obs: PlayerObservation,
        steps: int,
        context: dict[str, Any],
    ) -> tuple[ActionProposal | None, bool, bool]:
        """Pick this cycle's buttons. Returns proposal, used_recovery, pause."""
        if getattr(self, "referee", None) is not None:
            intervention = self._intervention(obs, task)
            if intervention is not None:
                return intervention, False, False
        if obs.in_battle:
            tier = 0  # Battle menus never receive an overworld disengage.
        elif getattr(self, "referee", None) is not None:
            self._objective(obs)
            if obs.policy.get("encounter_phase") == "pacing" and self.stuck.immobile_streak < 3:
                tier = 0  # Intentional grass pacing is progress; actual immobility still recovers.
        if tier in (2, 4):
            # Mechanical, no LLM: the screen looks the same every cycle, so a
            # vision call re-proposes what already failed. Tier 4 also tears
            # down the stale goal that got us here.
            proposal = self._disengage_proposal(task, obs=obs, tier=tier)
            if tier == 4:
                self._hard_reset_intent()
            self.plan = None
            self.arbiter.set_owner(AgentRole.RECOVERY)
            self._last_recovery_step = steps
            return proposal, True, False
        # A few wrong joystick presses stay with Jev. The recovery model runs
        # once mechanical disengage has failed (tier 3), or with no fast actor.
        if (self.jev is None or tier >= 3) and (tier >= 1 or decision.mode == GameMode.RECOVERY):
            hint = context["walkthrough_hint"] or excerpt_for_context(
                map_name=obs.map_name, reason="stuck recovery", memory=context["memory"]
            )
            advice = advise_recovery(
                self.llm,
                obs=self.env.vision_frame(obs),
                stuck_score=self.stuck.stuck_score,
                recent_positions=self.stuck.recent_positions,
                loop_streak=self.stuck.loop_streak,
                # Tier 3: disengage did not help either, so the goal is probably done.
                reframe=tier >= 3,
                **{**context, "walkthrough_hint": hint},
            )
            self.store.append("recovery", advice.model_dump(mode="json"))
            self.env.push_event("alert", advice.diagnosis)
            if advice.escalate_to_human and self.stuck.stuck_score >= 12:
                self.env.set_control(ControlState.PAUSED)
                console.print("[yellow]Escalated to human pause.[/yellow]")
                return None, False, True
            if self.jev is not None:
                self._adopt_recovery_plan(advice, obs)
            proposal = ActionProposal(
                task_id=task.task_id,
                agent=AgentRole.RECOVERY,
                reason=advice.reason,
                # B only: an A at the end re-opens the NPC we were stuck on.
                actions=advice.proposed_actions or [GameAction.PRESS_B] * 3,
                objectives=advice.objectives,
                landmarks=advice.landmarks,
            )
            self.arbiter.set_owner(AgentRole.RECOVERY)
            self._last_recovery_step = steps
            return proposal, True, False
        if self.jev is not None:
            return self._fast_proposal(task=task, obs=obs, context=context), False, False
        frame = self.env.vision_frame(obs)
        if task.owner == AgentRole.OVERWORLD:
            proposal = propose_overworld(
                self.llm, task=task, obs=frame, loop_streak=self.stuck.loop_streak, **context
            )
        else:
            proposal = propose_battle(
                self.llm, task=task, obs=frame, **_without(context, OVERWORLD_ONLY)
            )
        return proposal, False, False

    def _fast_proposal(
        self, *, task: Any, obs: PlayerObservation, context: dict[str, Any]
    ) -> ActionProposal:
        """System 1 cycle. The planner runs only when the card is stale."""
        signals = self._frame_signals(obs)
        # The last mash left the box unchanged. Another would be the same B,
        # so the planner looks at it instead.
        last_actions = self.recent_steps[-1]["actions"] if self.recent_steps else []
        mash_stalled = (
            signals.text_box
            and last_actions == [GameAction.SKIP_DIALOG.value]
            and not signals.dialog_changed
        )

        def refresh(trigger: str | None = None) -> PlanCard:
            started = time.monotonic()
            card = propose_plan(
                self.llm,
                obs=self.env.vision_frame(obs),
                objective=task.objective,
                buttons_on_this_tile=dict(self.stuck.press_counts) or None,
                trigger=trigger,
                journal=self.journal.since_last_look() or None,
                battle=self._battle_brief(obs) if obs.in_battle else None,
                navigation=self.navigator.context(obs, self.room, self._objective(obs)[0])
                if not obs.in_battle
                else None,
                constraints=self._constraints(obs),
                **context,
            )
            _stamp(card, signals, obs)
            card.created_at = time.time()
            latency = round(time.monotonic() - started, 2)
            self.store.append("plan", {**card.model_dump(mode="json"), "latency_s": latency})
            self.env.push_event("reasoning", f"[planner] {card.see} → {card.plan}")
            return card

        def jev_decide(state: dict[str, Any], questions: dict[str, Any]) -> Any:
            menu = (questions.get("action") or {}).get("criteria") or {}
            record: dict[str, Any] = {
                "scene": state.get("scene"),
                "menu": menu,
                "state_bytes": len(json.dumps(state, default=str)),
            }
            try:
                read = self.jev.decide(state=state, questions=questions, allowed=set(menu))
            except Exception as err:
                self.store.append("jev_call", {**record, "error": str(err)[:200]})
                raise
            self.store.append(
                "jev_call",
                {
                    **record,
                    "choice": read.action,
                    "confidence": read.confidence,
                    "probabilities": read.probabilities,
                    "plan_stale": read.plan_stale,
                    "objective_done": read.objective_done,
                    "accepted": accepts(read, self.confidence_floor),
                    "latency_s": read.latency_s,
                },
            )
            return read

        # System 1 first. System 2's steps are for screens System 1 cannot read (the naming
        # keyboard); pressed ahead of it, they kept a battle bag from System 3's POKé BALL.
        s1 = self._system1(obs, signals, mash_stalled=mash_stalled, jev_decide=jev_decide)
        if s1 is not None and not s1.trigger and self.plan is not None:
            self.plan.steps.clear()
        if s1 is not None and s1.trigger and self.plan is not None and self.plan.steps:
            # System 2 already answered with buttons for this screen: press them, no new look.
            s1 = None
        looked = False
        if (
            s1 is not None
            and s1.trigger in _COOLDOWN_TRIGGERS
            and len(self.journal.lines) - self._last_look < S2_COOLDOWN_CYCLES
        ):
            # Healing must retain its objective during the planning cooldown.
            if current_beat(obs) and current_beat(obs).id.startswith("heal"):
                return ActionProposal(
                    task_id=task.task_id,
                    agent=task.owner,
                    reason="retain healing objective",
                    actions=[GameAction.WAIT_60],
                )
            # System 2 looked moments ago. Asking again buys the same answer; explore instead.
            s1 = self._system1(
                obs, signals, mash_stalled=mash_stalled, jev_decide=jev_decide, explore=True
            )
        if s1 is not None and s1.trigger:
            # A decision System 1 cannot make: System 2 looks once, then System 1 tries again.
            self.plan = reconcile_plan(refresh(s1.trigger), obs)
            self._last_look = len(self.journal.lines)
            self.journal.looked()
            self._goal_fails.clear()
            self._low_confidence_streak = 0
            looked = True
            self.store.append("jev", {"actions": [], "reason": s1.reason, "looks": [s1.trigger]})
            s1 = (
                None
                if self.plan.steps
                else self._system1(obs, signals, mash_stalled=False, jev_decide=jev_decide)
            )
            if s1 is not None and s1.trigger:
                # Still undecided right after a look: press the look's steps if it wrote
                # any, else wait a moment. Never a second look in the same cycle.
                s1 = (
                    None
                    if self.plan.steps
                    else S1Turn(
                        [GameAction.WAIT_60], f"System 2 looked ({s1.trigger}); waiting", "wait"
                    )
                )
        if s1 is not None:
            return self._system1_proposal(task, s1)
        self._s1 = None
        turn = choose_fast_action(
            plan=self.plan,
            obs=obs,
            signals=signals,
            now=time.time(),
            plan_every_s=self.plan_every_s,
            stale_noul=self.stale_noul,
            confidence_floor=self.confidence_floor,
            low_confidence_streak=self._low_confidence_streak,
            force_replan=False if looked else self._forced_look(signals, mash_stalled=mash_stalled),
            mash_stalled=mash_stalled,
            jev_decide=jev_decide,
            refresh_plan=refresh,
            **_without(context, VISION_ONLY),
        )
        self.plan = turn.plan
        self._low_confidence_streak = turn.low_confidence_streak
        self.store.append(
            "jev",
            {
                "actions": [action.value for action in turn.actions],
                "reason": turn.reason,
                "replanned": turn.replanned,
                "looks": turn.looks,
                "scene": turn.plan.scene.value,
            },
        )
        return ActionProposal(
            task_id=task.task_id,
            agent=turn.agent,
            reason=turn.reason,
            actions=turn.actions,
            objectives=turn.objectives,
            landmarks=turn.landmarks,
        )

    def _objective(self, obs: PlayerObservation) -> tuple[dict[str, Any] | None, str | None, bool]:
        """The target System 1 walks toward: the beat's, else System 2's card, else none."""
        beat = current_beat(obs) if self._beat_locked else None
        from nuzlocke.knowledge.encounters import encounter_objective

        encounter = encounter_objective(self, obs, beat)
        if encounter:
            return encounter
        if beat is not None and beat.id == "heal_forest":
            from nuzlocke.agents.goals import Routes, collision_map

            routes = Routes((obs.x, obs.y), collision_map(obs, self.room) or {})
            choices = []
            for warp in obs.warps:
                destination = warp.get("dest_map")
                if destination not in {47, 50}:
                    continue
                path = routes.onto((warp["x"], warp["y"]))
                if path is not None:
                    # Remaining gate/Route 2 walks are a conservative allowance, not a guarantee.
                    choices.append((len(path) + (32 if destination == 47 else 64), destination))
            if choices:
                cost, destination = min(choices)
                obs.policy["healing_route_steps"] = cost
                return {"kind": "warp", "dest_map": destination}, beat.text, True
        if beat is not None and beat.target:
            return beat.target, beat.text, True
        card = self.plan
        if card is None or not card.goal_target:
            return None, None, False
        if card.goal_target.get("kind") == "tile" and card.goal_target.get("map_id") != obs.map_id:
            # A tile on the screenshot belongs to the map it was read on.
            return None, None, False
        wanted = str(card.done_when.get("map") or "").casefold()
        if wanted and wanted == (obs.map_name or "").casefold():
            return None, None, False
        return card.goal_target, card.plan, False

    def _system1(
        self,
        obs: PlayerObservation,
        signals: FrameSignals,
        *,
        mash_stalled: bool,
        jev_decide: Any,
        explore: bool = False,
    ) -> S1Turn | None:
        target, text, from_code = self._objective(obs)
        if not obs.party and obs.map_id == 40 and self._rejected_starters:
            balls = [
                n
                for n in obs.npcs
                if n.get("picture") == 74 and (n["x"], n["y"] + 1) not in self._rejected_starters
            ]
            if balls:
                target = {"kind": "face", "x": balls[0]["x"], "y": balls[0]["y"] + 1, "dir": "up"}
        if explore:
            target, text, from_code = _EXPLORE, "explore until System 2 looks again", True
        return system1_turn(
            obs=obs,
            screen=parse_screen(obs.screen_rows),
            text_box=signals.text_box,
            mash_stalled=mash_stalled,
            room=self.room,
            objective=target,
            objective_text=text,
            objective_from_code=from_code,
            heading=self._beat_heading,
            fails=self._goal_fails,
            last_texts=self._goal_texts,
            last_direction=self._last_direction,
            low_confidence_streak=self._low_confidence_streak,
            confidence_floor=self.confidence_floor,
            stale_noul=self.stale_noul,
            journal=self.journal.lines,
            constraints=self._constraints(obs),
            jev_decide=jev_decide,
            move_types=self.move_types,
            first_encounter=self.ledger.first_encounter,
            battle_plan=self._battle_plan(obs),
            navigator=self.navigator,
            route_plan=self.plan.route_plan if self.plan else None,
        )

    def _battle_brief(self, obs: PlayerObservation) -> dict[str, Any]:
        """What System 2 plans a battle from: the field, our moves with types, the party."""
        brief = dict(battle_facts(obs) or {})
        from nuzlocke.agents.battle import active_mon

        lead = active_mon(obs)
        brief["our_moves"] = [
            f"{m.get('name')} ({self.move_types.get(str(m.get('name')).upper(), 'type unknown')},"
            f" {m.get('pp')} PP)"
            for m in lead.get("moves") or []
            if isinstance(m, dict)
        ]
        brief["party"] = [
            f"{m.get('species')} L{m.get('level')} {m.get('hp')}/{m.get('max_hp')}"
            for m in obs.party
        ]
        return brief

    def _battle_plan(self, obs: PlayerObservation) -> dict[str, Any] | None:
        """System 2's plan for this trainer battle; dropped once the battle is over."""
        if self.plan is None:
            return None
        from nuzlocke.agents.battle import active_mon

        lead = active_mon(obs)
        exhausted = sorted(m.get("name", "") for m in lead.get("moves", []) if m.get("pp") == 0)
        critical = lead.get("hp", 0) / (lead.get("max_hp") or 1) < 0.35
        context = json.dumps(
            [
                obs.map_id,
                (obs.battle or {}).get("type"),
                (obs.battle or {}).get("enemy", {}).get("species"),
                (obs.battle or {}).get("enemy", {}).get("level"),
                obs.active_party_slot,
                lead.get("status"),
                critical,
                exhausted,
                [
                    m.get("capture_id")
                    for m in obs.party
                    if not m.get("dead") and not m.get("ineligible")
                ],
            ]
        )
        if not obs.in_battle or (self.plan.battle_context and self.plan.battle_context != context):
            self.plan.battle_plan = {}
        self.plan.battle_context = context
        return self.plan.battle_plan or None

    def _constraints(self, obs: PlayerObservation) -> list[str]:
        """System 3's briefing: the rules, the cap, the next boss, the trainers on this map."""
        dead = [str(entry.get("nickname")) for entry in self.referee.death_ledger]
        return nuzlocke_constraints(obs, self.referee.current_cap, dead)

    def _system1_proposal(self, task: Any, s1: S1Turn) -> ActionProposal:
        self._s1 = s1
        self._low_confidence_streak = s1.low_confidence_streak
        self.store.append(
            "jev",
            {
                "actions": [action.value for action in s1.actions],
                "reason": s1.reason,
                "looks": [],
                "scene": f"s1:{s1.kind}",
                "choice": s1.choice,
            },
        )
        # The arbiter takes presses from the task's owner, which a stuck tier can make Recovery.
        return ActionProposal(
            task_id=task.task_id, agent=task.owner, reason=s1.reason, actions=s1.actions
        )

    def _after_system1(
        self,
        before: PlayerObservation,
        after: PlayerObservation,
        result: Any,
        executed: list[str],
        after_box: bool,
        cycle: int,
    ) -> None:
        """Teach the room map, count goals that went nowhere, and write the journal line."""
        if not before.cutscene and not before.in_battle:
            self.room.record_walks(before, list(result.walks or []))
        if not self.grid_trust.trusted(after):
            self.room.known.pop(after.map_id, None)
        self.room.visit(self.grid_trust.view(after))
        self.navigator.observe(after, self.room)
        self._publish_navigation(after)
        moved = sum(
            1
            for step in result.walks or []
            if (step.get("x0"), step.get("y0")) != (step.get("x1"), step.get("y1"))
        )
        walks = [label.removeprefix("walk_") for label in executed if label.startswith("walk_")]
        if walks and walks[-1] in DIRS:
            self._last_direction = walks[-1]
        map_changed = (after.map_id, after.map_name) != (before.map_id, before.map_name)
        text = " ".join(parse_screen(after.screen_rows).text_lines) if after_box else None
        s1 = self._s1
        goal = s1.goal if s1 is not None and s1.goal is not None else None
        if map_changed:
            self._goal_fails.clear()
            self._goal_texts.clear()
        elif goal is not None and goal.kind != "wait":
            # No move, or the same line as last time (the old man's "You can't go through
            # here!" nudging the player back): either way the goal went nowhere.
            repeated = bool(text) and self._goal_texts.get(goal.key) == text
            if repeated or not (moved or text or after.in_battle):
                self._goal_fails[goal.key] = self._goal_fails.get(goal.key, 0) + 1
            elif moved:
                self._goal_fails.pop(goal.key, None)
            if text:
                self._goal_texts[goal.key] = text
        self.journal.add(
            {
                "cycle": cycle,
                "map": before.map_name,
                "x": before.x,
                "y": before.y,
                "kind": s1.kind if s1 is not None else "planner",
                "choice": s1.choice if s1 is not None else None,
                "label": s1.goal.label if s1 is not None and s1.goal is not None else None,
                "p": s1.probability if s1 is not None else None,
                "actions": executed,
                "outcome": journal_outcome(
                    before,
                    after,
                    moved_tiles=moved,
                    text=text,
                    stopped=result.stopped_early_because,
                ),
                "text": text,
            }
        )

    def _pages(self) -> int:
        """B presses and ``skip_dialog`` mashes on this tile."""
        return sum(self.stuck.press_counts.get(label, 0) for label in PAGING)

    def _forced_look(self, signals: FrameSignals, *, mash_stalled: bool) -> str | bool:
        """Why this cycle must look before pressing anything, or False."""
        if mash_stalled:
            return "skip_dialog left the box unchanged"
        # Single B presses only: a mash already pages until the box closes or
        # stalls, and a stall is looked at above.
        pages = self.stuck.press_counts.get("press_b", 0)
        if signals.text_box and pages >= 4 and pages % 4 == 0:
            return "long text on one tile"
        return False

    def _adopt_recovery_plan(self, advice: RecoveryAdvice, obs: PlayerObservation) -> None:
        signals = self._frame_signals(obs)
        card = plan_from_recovery(
            advice,
            scene=classify_scene(obs, None, signals),
            world_digest=signals.world_digest,
            now=time.time(),
        )
        self.plan = _stamp(reconcile_plan(card, obs), signals)
        self._low_confidence_streak = 0
        self.store.append("plan", self.plan.model_dump(mode="json"))

    def _cutscene_screen(self, obs: PlayerObservation) -> bool:
        """Title splash or an open narrative box. Not a battle, not a menu."""
        scene = self.plan.scene if self.plan is not None else None
        if obs.in_battle or scene == PlanScene.MENU:
            return False
        return scene == PlanScene.TITLE or text_box_open(obs.screenshot_path)

    def _frame_signals(self, obs: PlayerObservation) -> FrameSignals:
        world, dialog = digests_from_path(obs.screenshot_path)
        text_box = text_box_open(obs.screenshot_path)
        signals = FrameSignals(
            world_digest=world,
            dialog_digest=dialog,
            world_changed=self._prev_world is not None and world != self._prev_world,
            dialog_changed=self._prev_dialog is not None and dialog != self._prev_dialog,
            text_box=text_box,
            prompt_box=text_box and prompt_box_open(obs.screenshot_path),
        )
        self._prev_world, self._prev_dialog = world, dialog
        return signals

    def _no_progress_context(self) -> dict[str, Any] | None:
        """Evidence that the world has stopped moving, for the role prompts."""
        streak = self.stuck.no_progress_streak
        if streak < 2:
            return None
        ctx: dict[str, Any] = {
            "streak": streak,
            "measured_from": "pixels above the text box (world region)",
        }
        if repeats := self.stuck.repeated_actions():
            ctx["repeated_actions"] = repeats
        if self.stuck.same_tile_streak >= 2:
            ctx["cycles_on_this_tile"] = self.stuck.same_tile_streak
        return ctx

    def _disengage_proposal(
        self, task: Any, *, obs: PlayerObservation, tier: int
    ) -> ActionProposal:
        """Leave the tile toward the beat heading. One step, not a random circle."""
        stuck = self.stuck
        target, _, _ = self._objective(obs)
        recovery_heading = (
            target.get("dir") if target and target.get("kind") == "edge" else self._beat_heading
        )
        step = next_tile(
            heading=recovery_heading, grid=obs.collision_ascii, blocked=set(stuck.blocked_on_tile)
        )
        if step and step.action:
            actions = [step.action]
        elif step and step.choices:
            actions = [step.choices[0]]
        else:
            actions = stuck.disengage_actions()
        labels = [a.value for a in actions]
        reason = (
            f"forced disengage (tier {tier}, no_progress x{stuck.no_progress_streak}, "
            f"same tile x{stuck.same_tile_streak}, immobile x{stuck.immobile_streak}): "
            "one step toward the current heading, without asking the model"
        )
        self.env.push_event("alert", reason)
        console.print(f"[yellow]disengage tier {tier}[/yellow] {labels}")
        self.store.append(
            "disengage",
            {
                "tier": tier,
                "actions": labels,
                "no_progress_streak": stuck.no_progress_streak,
                "same_tile_streak": stuck.same_tile_streak,
                "repeated_actions": stuck.repeated_actions(),
            },
        )
        return ActionProposal(
            task_id=task.task_id, agent=AgentRole.RECOVERY, reason=reason, actions=actions
        )

    def _hard_reset_intent(self) -> None:
        """Tier 4: tear the goal down.

        A stale objective otherwise survives: the rollup writes it into OptMem
        from the looping ``recent``, wake() feeds it back, and the agent
        re-derives the same dead plan. A code-owned beat is not dropped.
        """
        dropped = self.objectives.get("primary")
        self.stuck.hard_reset()
        if self._beat_locked:
            self.env.push_event(
                "alert", f"Stuck streaks reset. The current beat stays: {dropped or 'unknown'}."
            )
            console.print(f"[red]hard reset of stuck state:[/red] {dropped}")
            self.store.append("intent_reset", {"dropped_primary": None, "beat": dropped})
            return
        self.objectives.pop("primary", None)
        note = (
            f"STALE GOAL dropped after a long no-progress streak: {dropped or 'unknown'} — "
            "it was most likely already complete. "
            "Do not restate it; pick the next walkthrough step instead."
        )
        if self.memory.enabled:
            self.memory.note("ANTI " + note)
        self.env.push_event("alert", note)
        console.print(f"[red]hard reset of intent:[/red] {dropped}")
        self.store.append("intent_reset", {"dropped_primary": dropped})

    def _sync_beats(self, obs: PlayerObservation, *, controllable: bool) -> str | None:
        """Own primary/secondary/tertiary while an early-game beat applies.

        Returns the beat's walkthrough line for this planner call, or None on
        speech, a battle, or the naming grid (speech is not a new goal).
        """
        if not controllable:
            return None
        window = objective_window(obs)
        beat = current_beat(obs)
        if window is None or beat is None:
            if self._beat_locked:
                self.objectives = self._seed_objectives()
            self._beat_locked = False
            self._beat_id = self._prompt_beat = self._beat_heading = None
            return None
        self._beat_locked = True
        self.objectives = window
        self._prompt_beat, self._beat_heading = beat.text, beat.heading
        if beat.id != self._beat_id:
            self._beat_id = beat.id
            self.plan = None
        return beat.hint

    def _apply_proposal_meta(self, proposal: ActionProposal) -> None:
        if proposal.objectives is not None and not self._beat_locked:
            self.objectives = merge_objectives(self.objectives, proposal.objectives)
            self._publish_objectives()
            self.store.append("objectives", self.objectives)
        if proposal.landmarks and self.memory.enabled:
            wrote = [
                landmark.label
                for landmark in proposal.landmarks
                if self.memory.note(f"LANDMARK {landmark.label}: {landmark.note}")
            ]
            if wrote:
                self.env.push_event("reasoning", f"landmarks: {wrote}")

    def _maybe_rollup_memory(self, *, steps: int, in_battle: bool) -> None:
        # Never while stuck: the rollup is generated from `recent`, so rolling
        # up mid-loop turns the loop itself into durable "facts" that wake()
        # feeds back every cycle.
        stuck = self.stuck.stuck_score >= 3 or self.stuck.no_progress_streak >= 3
        just_recovered = self._last_recovery_step >= 0 and steps - self._last_recovery_step <= 1
        if (
            not self.memory.enabled
            or self.rollup_every <= 0
            or steps == 0
            or steps % self.rollup_every
            or in_battle
            or just_recovered
            or stuck
        ):
            return
        recent = "; ".join(
            f"s{r.get('step')}:{r.get('actions')}→{r.get('outcome')}" for r in self.recent_steps
        )
        source = "\n".join([self.memory.wake(), f"recent: {recent}" if recent else ""]).strip()
        if not source:
            return
        try:
            notes = rollup_memory(self.llm, memory=source)
        except Exception as err:
            self.env.push_event("alert", f"memory rollup failed: {err}")
            return
        if not notes:
            return
        for note in notes:
            self.memory.note(f"ROLLUP {note}")
        self.env.push_event("reasoning", f"[memory] rollup wrote {len(notes)} notes")
        self.store.append("memory_rollup", {"steps": steps, "notes": notes})

    def _maybe_checkpoint(self, *, steps: int, in_battle: bool) -> None:
        if not should_checkpoint(
            steps=steps,
            every_steps=self.checkpoint_every_steps,
            in_battle=in_battle,
            last_ledger_change_step=self._last_ledger_change_step,
        ):
            return
        try:
            self.env.save_checkpoint(CHECKPOINT_NAME)
        except Exception as err:
            self.env.push_event("alert", f"checkpoint save failed: {err}")
            return
        self.store.append("checkpoint", {"steps": steps, "name": CHECKPOINT_NAME})
        self.env.push_event("reasoning", f"[checkpoint] saved at step {steps}")

    def _save_continue_point(self) -> None:
        """Write the savestate a later ``--resume`` will load."""
        if self.checkpoint_every_steps <= 0:
            return
        try:
            if self.env.observe().in_battle:
                console.print(
                    "[yellow]In battle, so the last out-of-battle savestate was left as-is.[/yellow]"
                )
                return
            self.env.save_checkpoint(CHECKPOINT_NAME)
        except Exception as err:
            console.print(f"[yellow]Could not write the continue savestate: {err}[/yellow]")
            return
        self.store.append("checkpoint", {"name": CHECKPOINT_NAME, "reason": "stop"})
        console.print(
            "[green]Savestate saved.[/green] Continue from here with:\n"
            f"  uv run nuzlocke run --resume {self.run_id}"
        )

    def close(self) -> None:
        self.llm.close()
        if self.jev is not None:
            self.jev.close()
        # A live run leaves pokemon-agent up so the dashboard stays watchable.
        if self.headless:
            self.env.shutdown()
        else:
            self.env._client.close()


def scripted_smoke(rom_path: Path | None, steps: int = 5) -> dict[str, Any]:
    """No-LLM smoke: observe and walk a few tiles with arbiter logging."""
    run_cfg = load_run_config()
    run_id = "smoke-" + uuid.uuid4().hex[:8]
    run_dir = project_root() / "runs" / run_id
    store = EventStore(run_dir)
    pa = run_cfg.get("pokemon_agent") or {}
    base_url = f"http://{pa.get('host', '127.0.0.1')}:{int(pa.get('port', 8765))}"
    env = NousRedEnvironment(
        base_url=base_url,
        run_dir=run_dir,
        rom_path=configured_rom(rom_path, run_cfg),
        auto_start=bool(pa.get("auto_start", True)),
    )
    arbiter = ActionArbiter(env, store, active_owner=AgentRole.OVERWORLD)
    obs = env.observe()
    store.append("observation", obs.model_dump(mode="json"))
    env.push_event("milestone", "Scripted smoke walk")
    proposal = ActionProposal(
        task_id="task-smoke",
        agent=AgentRole.OVERWORLD,
        reason="scripted smoke walk",
        actions=[GameAction.WALK_UP] * min(steps, 5),
    )
    result = arbiter.apply(proposal)
    final = env.observe()
    env._client.close()
    return {
        "run_id": run_id,
        "before": obs.model_dump(mode="json"),
        "arbiter": result.model_dump(mode="json"),
        "after": final.model_dump(mode="json"),
        "dashboard": f"{base_url}/dashboard",
    }
