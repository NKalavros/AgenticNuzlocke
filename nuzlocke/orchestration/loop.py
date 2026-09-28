"""Main autonomous run loop with dashboard START/PAUSE/STOP."""

from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Any

from rich.console import Console

from nuzlocke.agents.jev_policy import (
    FrameSignals,
    choose_fast_action,
    classify_scene,
    plan_from_recovery,
    reconcile_plan,
)
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
from nuzlocke.config import (
    load_agents_config,
    ensure_relay_routing,
    load_project_env,
    load_rules,
    load_run_config,
    project_root,
)
from nuzlocke.environment.joypad import is_naming_lock
from nuzlocke.environment.nous_red import NousRedEnvironment
from nuzlocke.environment.screen import digests_from_path, text_box_open
from nuzlocke.knowledge.walkthrough import excerpt_for_context, skill_dir
from nuzlocke.llm.factory import create_jev, create_provider
from nuzlocke.memory import OptMem
from nuzlocke.orchestration.arbiter import ActionArbiter
from nuzlocke.orchestration.checkpoint import CHECKPOINT_NAME, should_checkpoint
from nuzlocke.orchestration.fallback import (
    bridge_down_proposal,
    is_bridge_down,
    llm_error_fallback_proposal,
)
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


def _install_walkthrough_skill(workspace: Path) -> None:
    """Copy walkthrough skill into the Cursor agent workspace for on-demand reads."""
    import shutil

    src = skill_dir()
    if not src.is_dir():
        return
    dest = workspace / "skills" / "pokemon-red-walkthrough"
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest)


class RunLoop:
    def __init__(
        self,
        *,
        rom_path: Path | None,
        run_id: str | None = None,
        resume: bool = False,
        provider_override: str | None = None,
        vision_only: bool | None = None,
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
        if resume:
            from nuzlocke.orchestration.checkpoint import stage_for_boot

            stage_for_boot(self.run_dir)
        self.referee = NuzlockeReferee(self.rules)
        self.vision_only = (
            bool(vision_only)
            if vision_only is not None
            else bool(self.run_cfg.get("vision_only", False))
        )
        rom = rom_path or (
            Path(self.run_cfg["rom_path"]) if self.run_cfg.get("rom_path") else None
        )
        pa = self.run_cfg.get("pokemon_agent") or {}
        host = pa.get("host", "127.0.0.1")
        port = int(pa.get("port", 8765))
        self.env = NousRedEnvironment(
            base_url=f"http://{host}:{port}",
            run_dir=self.run_dir,
            rom_path=rom,
            auto_start=bool(pa.get("auto_start", True)),
            speed=int(pa.get("speed", 4)),
            press_interval_s=float(self.run_cfg.get("press_interval_s", 0.1)),
            load_state=CHECKPOINT_NAME if resume else None,
        )
        if resume:
            self.env.publish_savestate(CHECKPOINT_NAME)
            self.env.load_checkpoint(CHECKPOINT_NAME)
        control = self.run_cfg.get("control") or {}
        self.arbiter = ActionArbiter(
            self.env,
            self.store,
            max_actions=int(control.get("max_actions_per_proposal", 12)),
        )
        self.llm = create_provider(
            self.agents_cfg,
            workspace=self.run_dir / "agent_workspace",
            on_stream=lambda text: self.env.push_event("reasoning", text),
        )
        self.jev = create_jev(self.agents_cfg)
        planner_cfg = self.agents_cfg.get("planner") or {}
        self.plan: PlanCard | None = None
        self._low_confidence_streak = 0
        self._prev_world: str | None = None
        self._prev_dialog: str | None = None
        self.plan_every_s = float(planner_cfg.get("plan_every_s", 45))
        self.stale_noul = float(planner_cfg.get("stale_noul", 0.7))
        self.confidence_floor = float(planner_cfg.get("confidence_floor", 0.55))
        _install_walkthrough_skill(self.run_dir / "agent_workspace")
        self.stuck = StuckTracker()
        self.ledger = LedgerTracker(self.referee)
        # Short-term context for prompts (not OptMem).
        self.recent_steps: list[dict[str, Any]] = []
        self._recent_limit = 8
        self.prompt_interval_s = max(
            0.0, float(self.run_cfg.get("prompt_interval_s", 1.5))
        )
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
            if bool(checkpoint_cfg.get("enabled", True))
            else 0
        )
        self._last_ledger_change_step = -1000
        self._last_recovery_step = -1
        self.objectives = self._seed_objectives()
        if self.memory.enabled:
            self.memory.note(
                f"Run {self.run_id} {'resumed' if resume else 'started'}; "
                f"game={self.run_cfg.get('game')}; "
                f"vision_only={self.vision_only}; "
                f"rom={Path(rom).name if rom else 'none'}; "
                "Red Star: trust screenshot; avoid up/down outdoor hallucination loops"
            )
        self._write_manifest(rom)

    def _seed_objectives(self) -> dict[str, str]:
        milestones = self.run_cfg.get("milestones") or []
        texts: list[str] = []
        for item in milestones:
            if isinstance(item, dict) and item.get("description"):
                texts.append(str(item["description"]).strip())
            elif isinstance(item, str):
                texts.append(item.strip())
        while len(texts) < 3:
            texts.append("")
        seeded = {
            "primary": texts[0]
            or "Leave home · get starter from Oak",
            "secondary": texts[1]
            or "Reach Viridian · resolve Route 1 encounter",
            "tertiary": texts[2]
            or "Prepare legal team · attempt Brock",
        }
        return {k: v for k, v in seeded.items() if v}

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
            __import__("json").dumps(manifest, indent=2),
            encoding="utf-8",
        )
        self.store.set_meta("manifest", manifest)

    def _manifest_model(self) -> Any:
        provider = self.agents_cfg.get("provider")
        cur = self.agents_cfg.get("cursor") or {}
        if provider == "dual":
            planner = self.agents_cfg.get("planner") or {}
            jev = self.agents_cfg.get("jev") or {}
            return {
                "planner": {
                    "id": planner.get("model"),
                    "params": planner.get("params"),
                },
                "jev": jev.get("model"),
            }
        if provider == "cursor":
            return {"id": cur.get("model"), "params": cur.get("params")}
        return (self.agents_cfg.get("openai_compatible") or {}).get("model")

    def _wait_until_running(self) -> ControlState:
        respect = bool((self.run_cfg.get("control") or {}).get("respect_dashboard_control", True))
        poll = float((self.run_cfg.get("control") or {}).get("poll_interval_s", 0.5))
        if not respect:
            self.env.set_control(ControlState.RUNNING)
            return ControlState.RUNNING
        console.print(
            f"[cyan]Dashboard:[/cyan] http://127.0.0.1:{(self.run_cfg.get('pokemon_agent') or {}).get('port', 8765)}/dashboard"
        )
        console.print("[yellow]Press START on the dashboard (or we wait on /control).[/yellow]")
        # A leftover STOP from the previous session is not a request to
        # quit this one. Only RUNNING begins the run; Ctrl-C aborts the wait.
        while True:
            state = self.env.get_control()
            if state == ControlState.RUNNING:
                return state
            time.sleep(poll)

    def run(self, *, max_steps: int | None = None) -> None:
        self.store.append("run_start", {"run_id": self.run_id})
        self.env.push_event(
            "key_moment",
            f"Nuzlocke run {self.run_id} live — watch Field Log + game stage"
            + (" · vision-only" if self.vision_only else "")
            + (" · OptMem on" if self.memory.enabled else ""),
            category="milestone",
        )
        dash_objs = objectives_for_dashboard(self.objectives)
        if dash_objs:
            self.env.set_objectives(dash_objs)
        dash = (
            f"http://{(self.run_cfg.get('pokemon_agent') or {}).get('host', '127.0.0.1')}:"
            f"{(self.run_cfg.get('pokemon_agent') or {}).get('port', 8765)}/dashboard"
        )
        console.print(f"[bold cyan]Watch live:[/bold cyan] {dash}")
        console.print(
            "[dim]Cursor agents: Agents panel → Filter → Source → SDK[/dim]"
        )
        try:
            import webbrowser

            webbrowser.open(dash)
        except Exception:
            pass
        control = self._wait_until_running()
        if control == ControlState.STOPPED:
            console.print("[red]Stopped before start.[/red]")
            return

        steps = 0
        while max_steps is None or steps < max_steps:
            control = self.env.get_control()
            if control == ControlState.STOPPED:
                console.print("[red]STOP from dashboard.[/red]")
                break
            if control == ControlState.PAUSED:
                time.sleep(0.5)
                continue

            # Vision-only cadence: no RAM-based readiness polling (joy_ignore
            # / dialog_active can be wrong on ROM hacks like Red Star — the
            # agent must trust the screenshot). Let the emulation run in
            # real time and just look at whatever is on screen each cycle.
            cycle_started = time.time()
            obs = self.env.observe()
            speech = (
                text_box_open(obs.screenshot_path)
                and not obs.in_battle
                and not is_naming_lock(obs.joy_ignore)
            )
            if speech:
                console.print("[dim]speech on screen[/dim]")
            else:
                console.print(f"[dim]map={obs.map_name} battle={obs.in_battle}[/dim]")

            self.store.append("observation", obs.model_dump(mode="json"))
            if self._cutscene_screen(obs):
                self.stuck.pause_for_cutscene()
            self.stuck.update_position(obs)
            self.referee.advance(len(obs.badges))
            if self.ledger.update(obs, step=steps):
                self._last_ledger_change_step = steps

            violations = self.referee.assert_party_legal(obs)
            if violations:
                self.env.push_event("alert", "; ".join(violations))
                self.store.append("rule_violation", {"violations": violations})

            summary = {
                "run_id": self.run_id,
                "cap": self.referee.current_cap,
                "stuck_score": self.stuck.stuck_score,
                "noop_streak": self.stuck.noop_streak,
                "loop_streak": self.stuck.loop_streak,
                "no_progress_streak": self.stuck.no_progress_streak,
                "deaths": len(self.referee.death_ledger),
                "encounters": self.referee.encounter_ledger,
                "vision_only": self.vision_only,
                "hint": (
                    f"noop_streak={self.stuck.noop_streak}"
                    if self.stuck.noop_streak >= 1
                    else (
                        f"loop_streak={self.stuck.loop_streak}"
                        if self.stuck.loop_streak >= 1
                        else (
                            f"no_progress_streak={self.stuck.no_progress_streak}"
                            if self.stuck.no_progress_streak >= 1
                            else None
                        )
                    )
                ),
            }
            memory_text = self.memory.wake()
            recent_ctx = list(self.recent_steps)
            failed_approaches = [list(item) for item in self.stuck.failed_approaches]
            no_progress_ctx = self._no_progress_context()
            need_guide = self.stuck.needs_guide()
            walkthrough_hint = None
            if need_guide:
                # Orchestrator may use RAM map name to pick the right section
                # even in vision_only mode (LLM still won't see RAM).
                walkthrough_hint = excerpt_for_context(
                    map_name=obs.map_name,
                    reason=str(summary.get("hint") or ""),
                    memory=memory_text,
                )
                if walkthrough_hint:
                    self.env.push_event(
                        "reasoning",
                        "[walkthrough] injected stuck-helper excerpt",
                    )
            decision = decide_director(
                self.llm,
                summary=summary,
                obs=obs,
                memory=memory_text,
                vision_only=self.vision_only,
                walkthrough_hint=walkthrough_hint,
                speech=speech,
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
            # Keep agent-owned objectives on the dashboard; fold Director goal into
            # primary only when the agent has not set one yet.
            if "primary" not in self.objectives and decision.objective:
                self.objectives["primary"] = decision.objective
            dash_objs = objectives_for_dashboard(self.objectives)
            if dash_objs:
                self.env.set_objectives(dash_objs)

            used_recovery = False
            pause = False
            tier = self.stuck.escalation_tier()
            try:
                proposal, used_recovery, pause = self._select_proposal(
                    tier=tier,
                    decision=decision,
                    task=task,
                    obs=obs,
                    steps=steps,
                    memory_text=memory_text,
                    recent_ctx=recent_ctx,
                    walkthrough_hint=walkthrough_hint,
                    failed_approaches=failed_approaches or None,
                    no_progress_ctx=no_progress_ctx,
                )
            except Exception as err:
                self.store.append(
                    "llm_error",
                    {"error": str(err), "owner": task.owner.value},
                )
                if is_bridge_down(err):
                    self.env.push_event(
                        "alert",
                        f"Cursor bridge down — waiting (keep Cursor app open): {err}",
                    )
                    console.print(
                        "[red]Cursor SDK bridge connection refused.[/red] "
                        "Keep the Cursor app open, then the run will retry."
                    )
                    time.sleep(8.0)
                    proposal = bridge_down_proposal(task)
                    self.arbiter.set_owner(proposal.agent)
                else:
                    self.env.push_event("alert", f"LLM error (fallback macro): {err}")
                    console.print(
                        f"[yellow]LLM error, using fallback macro:[/yellow] {err}"
                    )
                    proposal = llm_error_fallback_proposal(task)
                    self.arbiter.set_owner(proposal.agent)

            if pause:
                continue

            self._apply_proposal_meta(proposal)
            action_labels = [a.value for a in proposal.actions]
            announce = (
                f"[{proposal.agent.value}] {proposal.reason} → {action_labels}"
            )
            self.env.push_event("decision", announce)
            console.print(f"[magenta]next[/magenta] {announce}")
            before_fp = self.stuck.fingerprint(obs)
            result = self.arbiter.apply(proposal)
            after = self.env.observe()
            after_fp = self.stuck.fingerprint(after)
            executed_labels = [a.value for a in result.executed_actions]
            is_noop = self.stuck.record_result(
                before_fp,
                after_fp,
                executed=bool(result.executed_actions),
                actions=executed_labels or None,
            )
            if used_recovery and not is_noop:
                self.stuck.discount(2)
            if is_noop:
                self.env.push_event(
                    "alert",
                    f"noop x{self.stuck.noop_streak}: actions did not change screen/state",
                )
                if (
                    self.memory.enabled
                    and self.stuck.noop_streak >= 3
                    and executed_labels
                    and any(a.startswith("walk_") for a in executed_labels)
                ):
                    noted = self.memory.note(
                        "ANTI do not repeat: " + " ".join(executed_labels)
                    )
                    if noted:
                        self.env.push_event("reasoning", noted)
            elif self.stuck.loop_streak >= 3:
                self.env.push_event(
                    "alert",
                    f"loop x{self.stuck.loop_streak}: oscillating walks or tiles",
                )
            elif self.stuck.no_progress_streak >= 3:
                self.env.push_event(
                    "alert",
                    f"no_progress x{self.stuck.no_progress_streak}: "
                    "only text changed, the world did not",
                )
            self.env.push_event(
                "action",
                f"{result.status}: {[a.value for a in result.executed_actions]}"
                + (
                    f" ({result.stopped_early_because})"
                    if result.stopped_early_because
                    else ""
                ),
            )
            console.print(
                f"[green]step {steps}[/green] {task.owner.value} -> "
                f"{result.status} {[a.value for a in result.executed_actions]}"
                + (
                    f" [noop={self.stuck.noop_streak}]"
                    if self.stuck.noop_streak
                    else (
                        f" [loop={self.stuck.loop_streak}]"
                        if self.stuck.loop_streak
                        else ""
                    )
                )
            )
            # Label honestly. The old version reported "ok" / "skip_dialog" for
            # every one of the 200 looping steps in run 20260821-164159-3c5a68,
            # so the agent's own history read as unbroken success.
            if self.stuck.noop_streak:
                outcome = f"noop x{self.stuck.noop_streak}"
            elif self.stuck.no_progress_streak:
                outcome = f"no_progress x{self.stuck.no_progress_streak}"
            else:
                outcome = result.stopped_early_because or "ok"
            # Short-term prompt context only — OptMem stays for landmarks/rollups.
            self.recent_steps.append(
                {
                    "step": steps,
                    "agent": proposal.agent.value,
                    "actions": [a.value for a in result.executed_actions][:8],
                    "outcome": outcome,
                    "reason": (proposal.reason or "")[:160],
                }
            )
            self.recent_steps = self.recent_steps[-self._recent_limit :]
            steps += 1
            self._maybe_rollup_memory(
                steps=steps,
                in_battle=after.in_battle,
            )
            self._maybe_checkpoint(steps=steps, in_battle=after.in_battle)

            # Keep ~prompt_interval_s between prompt cycles; actions already ran live.
            if self.prompt_interval_s > 0:
                remaining = self.prompt_interval_s - (time.time() - cycle_started)
                if remaining > 0:
                    time.sleep(remaining)
        self._save_continue_point()
        self.store.append("run_end", {"run_id": self.run_id, "steps": steps})
        self.close()

    def _select_proposal(
        self,
        *,
        tier: int,
        decision: Any,
        task: Any,
        obs: PlayerObservation,
        steps: int,
        memory_text: str | None,
        recent_ctx: list[dict[str, Any]],
        walkthrough_hint: str | None,
        failed_approaches: list[list[str]] | None,
        no_progress_ctx: dict[str, Any] | None,
    ) -> tuple[ActionProposal | None, bool, bool]:
        """Pick this cycle's buttons. Returns proposal, used_recovery, pause."""
        if tier in (2, 4):
            # Tier 2 breaks the loop mechanically — no LLM call. The
            # screen looks identical every cycle, so a vision call just
            # re-proposes what already failed (222 times in run
            # 20260821-164159-3c5a68). Tier 4 does the same and then
            # tears down the stale goal that got us here.
            proposal = self._disengage_proposal(task, tier=tier)
            if tier == 4:
                self._hard_reset_intent()
            self.plan = None
            self.arbiter.set_owner(AgentRole.RECOVERY)
            self._last_recovery_step = steps
            return proposal, True, False
        # A few wrong joystick presses stay with Jev. The recovery model
        # only runs once mechanical disengage has already failed (tier 3),
        # or when there is no fast actor at all.
        jev_keeps_stick = self.jev is not None and tier < 3
        if not jev_keeps_stick and (tier >= 1 or decision.mode == GameMode.RECOVERY):
            advice = advise_recovery(
                self.llm,
                obs=obs,
                stuck_score=self.stuck.stuck_score,
                recent_positions=self.stuck.recent_positions,
                memory=memory_text,
                recent=recent_ctx,
                vision_only=self.vision_only,
                walkthrough_hint=walkthrough_hint
                or excerpt_for_context(
                    map_name=obs.map_name,
                    reason="stuck recovery",
                    memory=memory_text,
                ),
                objectives=self.objectives,
                nuzlocke=self._nuzlocke_state(),
                failed_approaches=failed_approaches,
                loop_streak=self.stuck.loop_streak,
                no_progress=no_progress_ctx,
                # Tier 3: mechanical disengage did not help either, so
                # tell it the goal itself is probably already satisfied.
                reframe=tier >= 3,
            )
            self.store.append("recovery", advice.model_dump(mode="json"))
            self.env.push_event("alert", advice.diagnosis)
            # Only pause for a human after many failed recoveries.
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
                # Fallback is B-only and B-terminated: an A at the end
                # re-opens whatever NPC we were already stuck on.
                actions=advice.proposed_actions
                or [
                    GameAction.HOLD_B_120,
                    GameAction.PRESS_B,
                    GameAction.HOLD_B_120,
                ],
                objectives=advice.objectives,
                landmarks=advice.landmarks,
            )
            self.arbiter.set_owner(AgentRole.RECOVERY)
            self._last_recovery_step = steps
            return proposal, True, False
        if self.jev is not None:
            return (
                self._fast_proposal(
                    task=task,
                    obs=obs,
                    memory_text=memory_text,
                    recent_ctx=recent_ctx,
                    walkthrough_hint=walkthrough_hint,
                    failed_approaches=failed_approaches,
                    no_progress_ctx=no_progress_ctx,
                ),
                False,
                False,
            )
        if task.owner == AgentRole.OVERWORLD:
            return (
                propose_overworld(
                    self.llm,
                    task=task,
                    obs=obs,
                    memory=memory_text,
                    recent=recent_ctx,
                    vision_only=self.vision_only,
                    walkthrough_hint=walkthrough_hint,
                    objectives=self.objectives,
                    nuzlocke=self._nuzlocke_state(),
                    failed_approaches=failed_approaches,
                    loop_streak=self.stuck.loop_streak,
                    no_progress=no_progress_ctx,
                ),
                False,
                False,
            )
        return (
            propose_battle(
                self.llm,
                task=task,
                obs=obs,
                memory=memory_text,
                recent=recent_ctx,
                vision_only=self.vision_only,
                walkthrough_hint=walkthrough_hint,
                objectives=self.objectives,
                nuzlocke=self._nuzlocke_state(),
            ),
            False,
            False,
        )

    def _fast_proposal(
        self,
        *,
        task: Any,
        obs: PlayerObservation,
        memory_text: str | None,
        recent_ctx: list[dict[str, Any]],
        walkthrough_hint: str | None,
        failed_approaches: list[list[str]] | None,
        no_progress_ctx: dict[str, Any] | None,
    ) -> ActionProposal:
        """System 1 cycle. The planner runs only when the card is stale."""
        signals = self._frame_signals(obs)

        def refresh() -> PlanCard:
            card = propose_plan(
                self.llm,
                obs=obs,
                memory=memory_text,
                recent=recent_ctx,
                vision_only=self.vision_only,
                walkthrough_hint=walkthrough_hint,
                objectives=self.objectives,
                nuzlocke=self._nuzlocke_state(),
                failed_approaches=failed_approaches,
                no_progress=no_progress_ctx,
                objective=task.objective,
            )
            card.world_digest = signals.world_digest
            card.text_box = signals.text_box
            card.created_at = time.time()
            self.store.append("plan", card.model_dump(mode="json"))
            self.env.push_event("reasoning", f"[planner] {card.see} → {card.plan}")
            return card

        def jev_decide(state: dict[str, Any], questions: dict[str, Any]) -> Any:
            allowed = set((questions.get("action") or {}).get("criteria") or {})
            assert self.jev is not None
            return self.jev.decide(state=state, questions=questions, allowed=allowed)

        turn = choose_fast_action(
            plan=self.plan,
            obs=obs,
            signals=signals,
            now=time.time(),
            plan_every_s=self.plan_every_s,
            stale_noul=self.stale_noul,
            confidence_floor=self.confidence_floor,
            low_confidence_streak=self._low_confidence_streak,
            same_tile_streak=self.stuck.same_tile_streak,
            failed_approaches=failed_approaches,
            memory=memory_text,
            recent=recent_ctx,
            objectives=self.objectives,
            nuzlocke=self._nuzlocke_state(),
            no_progress=no_progress_ctx,
            jev_decide=jev_decide,
            refresh_plan=refresh,
        )
        self.plan = turn.plan
        self._low_confidence_streak = turn.low_confidence_streak
        self.store.append(
            "jev",
            {
                "actions": [action.value for action in turn.actions],
                "reason": turn.reason,
                "replanned": turn.replanned,
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

    def _adopt_recovery_plan(
        self,
        advice: RecoveryAdvice,
        obs: PlayerObservation,
    ) -> None:
        signals = self._frame_signals(obs)
        card = reconcile_plan(
            plan_from_recovery(
                advice,
                scene=classify_scene(obs, None, signals),
                world_digest=signals.world_digest,
                now=time.time(),
            ),
            obs,
        )
        card.text_box = signals.text_box
        self.plan = card
        self._low_confidence_streak = 0
        self.store.append("plan", card.model_dump(mode="json"))

    def _cutscene_screen(self, obs: PlayerObservation) -> bool:
        """Title splash or an open narrative box. Not a battle, not a menu."""
        if obs.in_battle:
            return False
        if self.plan is not None and self.plan.scene == PlanScene.MENU:
            return False
        if text_box_open(obs.screenshot_path):
            return True
        return self.plan is not None and self.plan.scene == PlanScene.TITLE

    def _frame_signals(self, obs: PlayerObservation) -> FrameSignals:
        world, dialog = digests_from_path(obs.screenshot_path)
        signals = FrameSignals(
            world_digest=world,
            dialog_digest=dialog,
            world_changed=self._prev_world is not None and world != self._prev_world,
            dialog_changed=self._prev_dialog is not None and dialog != self._prev_dialog,
            text_box=text_box_open(obs.screenshot_path),
        )
        self._prev_world = world
        self._prev_dialog = dialog
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
        repeats = self.stuck.repeated_actions()
        if repeats:
            ctx["repeated_actions"] = repeats
        if self.stuck.same_tile_streak >= 2:
            ctx["cycles_on_this_tile"] = self.stuck.same_tile_streak
        return ctx

    def _disengage_proposal(self, task: Any, *, tier: int) -> ActionProposal:
        """Blind mechanical escape — press B, then leave the tile."""
        actions = self.stuck.disengage_actions()
        labels = [a.value for a in actions]
        reason = (
            f"forced disengage (tier {tier}, "
            f"no_progress x{self.stuck.no_progress_streak}, "
            f"same tile x{self.stuck.same_tile_streak}): "
            "the world has not changed in a long time — closing any text box "
            "and walking off this tile without asking the model"
        )
        self.env.push_event("alert", reason)
        console.print(f"[yellow]disengage tier {tier}[/yellow] {labels}")
        self.store.append(
            "disengage",
            {
                "tier": tier,
                "actions": labels,
                "no_progress_streak": self.stuck.no_progress_streak,
                "same_tile_streak": self.stuck.same_tile_streak,
                "repeated_actions": self.stuck.repeated_actions(),
            },
        )
        return ActionProposal(
            task_id=task.task_id,
            agent=AgentRole.RECOVERY,
            reason=reason,
            actions=actions,
        )

    def _hard_reset_intent(self) -> None:
        """Tier 4: the goal itself is the problem — tear it down.

        A stale objective survives indefinitely otherwise: the rollup writes it
        into OptMem from the looping `recent`, wake() feeds it back next cycle,
        and the agent re-derives the same dead plan. Run
        20260821-164159-3c5a68 has the same "deliver Oak's Parcel" rollup six
        times over, long after the parcel was delivered.
        """
        dropped = self.objectives.get("primary")
        self.stuck.hard_reset()
        self.objectives.pop("primary", None)
        note = (
            "STALE GOAL dropped after a long no-progress streak: "
            f"{dropped or 'unknown'} — it was most likely already complete. "
            "Do not restate it; pick the next walkthrough step instead."
        )
        if self.memory.enabled:
            self.memory.note("ANTI " + note)
        self.env.push_event("alert", note)
        console.print(f"[red]hard reset of intent:[/red] {dropped}")
        self.store.append("intent_reset", {"dropped_primary": dropped})

    def _apply_proposal_meta(self, proposal: ActionProposal) -> None:
        if proposal.objectives is not None:
            self.objectives = merge_objectives(self.objectives, proposal.objectives)
            dash = objectives_for_dashboard(self.objectives)
            if dash:
                self.env.set_objectives(dash)
            self.store.append("objectives", self.objectives)
        if proposal.landmarks and self.memory.enabled:
            wrote = []
            for landmark in proposal.landmarks:
                noted = self.memory.note(f"LANDMARK {landmark.label}: {landmark.note}")
                if noted:
                    wrote.append(landmark.label)
            if wrote:
                self.env.push_event(
                    "reasoning",
                    f"landmarks: {wrote}",
                )

    def _maybe_rollup_memory(self, *, steps: int, in_battle: bool) -> None:
        if not self.memory.enabled or self.rollup_every <= 0:
            return
        if steps == 0 or steps % self.rollup_every != 0:
            return
        if in_battle:
            return
        if self._last_recovery_step >= 0 and steps - self._last_recovery_step <= 1:
            return
        # Never roll up while stuck. The rollup is generated from `recent`, so
        # rolling up mid-loop distills the loop itself into durable "facts" that
        # wake() then feeds back every cycle — a closed belief loop that
        # outlived the goal it described for 33 minutes in run
        # 20260821-164159-3c5a68.
        if self.stuck.stuck_score >= 3 or self.stuck.no_progress_streak >= 3:
            return
        # Roll up from short-term recent + any durable wake (no per-step OptMem spam).
        wake = self.memory.wake()
        recent_bits = [
            f"s{r.get('step')}:{r.get('actions')}→{r.get('outcome')}"
            for r in self.recent_steps
        ]
        source = "\n".join(
            [wake, "recent: " + "; ".join(recent_bits) if recent_bits else ""]
        ).strip()
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
            obs = self.env.observe()
        except Exception as err:
            console.print(f"[yellow]No continue savestate: {err}[/yellow]")
            return
        if obs.in_battle:
            console.print(
                "[yellow]In battle, so the last out-of-battle savestate was left as-is.[/yellow]"
            )
            return
        try:
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
        # Keep emulator up for watching unless we started it and user wants exit.
        # Do not kill pokemon-agent by default so dashboard remains.
        self.env._client.close()


def scripted_smoke(rom_path: Path | None, steps: int = 5) -> dict[str, Any]:
    """No-LLM smoke: observe and walk a few tiles with arbiter logging."""
    root = project_root()
    run_cfg = load_run_config()
    run_id = "smoke-" + uuid.uuid4().hex[:8]
    run_dir = root / "runs" / run_id
    store = EventStore(run_dir)
    rom = rom_path or (
        Path(run_cfg["rom_path"]) if run_cfg.get("rom_path") else None
    )
    pa = run_cfg.get("pokemon_agent") or {}
    env = NousRedEnvironment(
        base_url=f"http://{pa.get('host', '127.0.0.1')}:{int(pa.get('port', 8765))}",
        run_dir=run_dir,
        rom_path=rom,
        auto_start=bool(pa.get("auto_start", True)),
    )
    arbiter = ActionArbiter(env, store, active_owner=AgentRole.OVERWORLD)
    obs = env.observe()
    store.append("observation", obs.model_dump(mode="json"))
    env.push_event("milestone", "Scripted smoke walk")
    from nuzlocke.state.models import GameAction

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
        "dashboard": f"http://{pa.get('host', '127.0.0.1')}:{pa.get('port', 8765)}/dashboard",
    }
