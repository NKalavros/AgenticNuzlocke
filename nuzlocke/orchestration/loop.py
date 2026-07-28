"""Main autonomous run loop with dashboard START/PAUSE/STOP."""

from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Any

from rich.console import Console

from nuzlocke.agents.roles import (
    advise_recovery,
    decide_director,
    make_task,
    propose_battle,
    propose_overworld,
)
from nuzlocke.config import load_agents_config, load_rules, load_run_config, project_root
from nuzlocke.environment.joypad import is_naming_lock
from nuzlocke.environment.nous_red import NousRedEnvironment
from nuzlocke.knowledge.walkthrough import excerpt_for_context, skill_dir
from nuzlocke.llm.factory import create_provider
from nuzlocke.memory import OptMem
from nuzlocke.orchestration.arbiter import ActionArbiter
from nuzlocke.referee.rules import NuzlockeReferee
from nuzlocke.state.models import (
    ActionProposal,
    AgentRole,
    ControlState,
    GameAction,
    GameMode,
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
        provider_override: str | None = None,
        vision_only: bool | None = None,
    ) -> None:
        self.root = project_root()
        self.run_cfg = load_run_config()
        self.agents_cfg = load_agents_config()
        if provider_override:
            self.agents_cfg["provider"] = provider_override
        self.rules = load_rules()
        self.run_id = run_id or time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
        self.run_dir = self.root / "runs" / self.run_id
        self.store = EventStore(self.run_dir)
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
        )
        control = self.run_cfg.get("control") or {}
        self.arbiter = ActionArbiter(
            self.env,
            self.store,
            max_actions=int(control.get("max_actions_per_proposal", 8)),
        )
        self.llm = create_provider(
            self.agents_cfg,
            workspace=self.run_dir / "agent_workspace",
            on_stream=lambda text: self.env.push_event("reasoning", text),
        )
        _install_walkthrough_skill(self.run_dir / "agent_workspace")
        self.stuck_score = 0
        self.recent_positions: list[tuple[str | None, int | None, int | None]] = []
        self._last_fingerprint: tuple | None = None
        self._noop_streak = 0
        self.prompt_interval_s = max(
            0.0, float(self.run_cfg.get("prompt_interval_s", 2.0))
        )
        mem_cfg = self.run_cfg.get("memory") or {}
        self.memory = OptMem(
            self.run_dir / "memory",
            memo_bin=mem_cfg.get("memo_bin"),
            wake_lines=int(mem_cfg.get("wake_lines", 48)),
            enabled=bool(mem_cfg.get("enabled", True)),
        )
        if self.memory.enabled:
            self.memory.note(
                f"Run {self.run_id} started; game={self.run_cfg.get('game')}; "
                f"vision_only={self.vision_only}; "
                f"rom={Path(rom).name if rom else 'none'}; "
                "Red Star: trust screenshot; avoid up/down outdoor hallucination loops"
            )
        self._write_manifest(rom)

    def _write_manifest(self, rom: Path | None) -> None:
        manifest = {
            "run_id": self.run_id,
            "game": self.run_cfg.get("game"),
            "observation_mode": self.run_cfg.get("observation_mode"),
            "vision_only": self.vision_only,
            "memory_enabled": self.memory.enabled,
            "rom_path": str(rom) if rom else None,
            "provider": self.agents_cfg.get("provider"),
            "model": (
                {
                    "id": (self.agents_cfg.get("cursor") or {}).get("model"),
                    "params": (self.agents_cfg.get("cursor") or {}).get("params"),
                }
                if self.agents_cfg.get("provider") == "cursor"
                else (self.agents_cfg.get("openai_compatible") or {}).get("model")
            ),
            "rules": self.rules,
        }
        (self.run_dir / "manifest.json").write_text(
            __import__("json").dumps(manifest, indent=2),
            encoding="utf-8",
        )
        self.store.set_meta("manifest", manifest)

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
        while True:
            state = self.env.get_control()
            if state == ControlState.RUNNING:
                return state
            if state == ControlState.STOPPED:
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
        self.env.set_objectives(
            [
                {
                    "tier": "primary",
                    "text": "Leave home · get starter from Oak",
                    "done": False,
                },
                {
                    "tier": "secondary",
                    "text": "Reach Viridian · resolve Route 1 encounter",
                    "done": False,
                },
                {
                    "tier": "tertiary",
                    "text": "Prepare legal team · attempt Brock (cap 14)",
                    "done": False,
                },
            ]
        )
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

            # Advance dialog / wait out animations before spending an LLM turn.
            ready_cfg = self.run_cfg.get("input_ready") or {}
            if bool(ready_cfg.get("enabled", True)):
                obs = self.env.wait_until_input_ready(
                    timeout_s=float(ready_cfg.get("timeout_s", 3.0)),
                    auto_advance_dialog=bool(
                        ready_cfg.get("auto_advance_dialog", True)
                    ),
                    poll_wait_action=str(
                        ready_cfg.get("poll_wait_action", "wait_30")
                    ),
                    skip_dialog_max_rounds=int(
                        ready_cfg.get("skip_dialog_max_rounds", 30)
                    ),
                )
            else:
                obs = self.env.observe()

            naming = is_naming_lock(obs.joy_ignore)
            console.print(
                f"[dim]joy[/dim] ignore={obs.joy_ignore} "
                f"dialog={obs.dialog_active} naming={naming} "
                f"ready={obs.input_ready} battle={obs.in_battle}"
            )
            self.env.push_event(
                "reasoning",
                f"joy_ignore={obs.joy_ignore} dialog={obs.dialog_active} "
                f"naming={naming} input_ready={obs.input_ready}",
            )

            # Cadence timer starts once the game can accept a decision.
            cycle_started = time.time()

            self.store.append("observation", obs.model_dump(mode="json"))
            pos = (obs.map_name, obs.x, obs.y)
            self.recent_positions.append(pos)
            self.recent_positions = self.recent_positions[-8:]
            # Only accumulate stuck when we sit on the same tile with no dialog
            # and no map change — intro/menus often hold position by design.
            same_tile = (
                len(self.recent_positions) >= 6
                and len(set(self.recent_positions[-6:])) == 1
            )
            if same_tile and not obs.dialog_active and not obs.in_battle:
                self.stuck_score += 1
            else:
                self.stuck_score = max(0, self.stuck_score - 1)

            violations = self.referee.assert_party_legal(obs)
            if violations:
                self.env.push_event("alert", "; ".join(violations))
                self.store.append("rule_violation", {"violations": violations})

            summary = {
                "run_id": self.run_id,
                "cap": self.referee.current_cap,
                "stuck_score": self.stuck_score,
                "noop_streak": self._noop_streak,
                "deaths": len(self.referee.death_ledger),
                "encounters": self.referee.encounter_ledger,
                "vision_only": self.vision_only,
                "input_ready": obs.input_ready,
                "hint": (
                    "Last actions did not change the screen/position — "
                    "do not repeat the same walks; use the screenshot + memory."
                    if self._noop_streak >= 1
                    else None
                ),
            }
            memory_text = self.memory.wake()
            need_guide = self._noop_streak >= 2 or self.stuck_score >= 3
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
            self.env.set_objectives(
                [
                    {
                        "tier": "primary",
                        "text": task.objective,
                        "done": False,
                    },
                    {
                        "tier": "secondary",
                        "text": f"Owner: {task.owner.value} · stuck={self.stuck_score}",
                        "done": False,
                    },
                    {
                        "tier": "tertiary",
                        "text": f"Map: {obs.map_name or '?'} ({obs.x},{obs.y}) facing {obs.facing}",
                        "done": False,
                    },
                ]
            )

            try:
                if self._noop_streak >= 2 or self.stuck_score >= 6 or decision.mode == GameMode.RECOVERY:
                    advice = advise_recovery(
                        self.llm,
                        obs=obs,
                        stuck_score=self.stuck_score,
                        recent_positions=self.recent_positions,
                        memory=memory_text,
                        vision_only=self.vision_only,
                        walkthrough_hint=walkthrough_hint
                        or excerpt_for_context(
                            map_name=obs.map_name,
                            reason="stuck recovery",
                            memory=memory_text,
                        ),
                    )
                    self.store.append("recovery", advice.model_dump(mode="json"))
                    self.env.push_event("alert", advice.diagnosis)
                    # Only pause for a human after many failed recoveries.
                    if advice.escalate_to_human and self.stuck_score >= 12:
                        self.env.set_control(ControlState.PAUSED)
                        console.print("[yellow]Escalated to human pause.[/yellow]")
                        continue
                    proposal = ActionProposal(
                        task_id=task.task_id,
                        agent=AgentRole.RECOVERY,
                        reason=advice.reason,
                        actions=advice.proposed_actions
                        or [
                            GameAction.HOLD_B_120,
                            GameAction.PRESS_A,
                            GameAction.HOLD_B_120,
                            GameAction.PRESS_A,
                            GameAction.PRESS_A,
                        ],
                    )
                    self.arbiter.set_owner(AgentRole.RECOVERY)
                    self.stuck_score = max(0, self.stuck_score - 2)
                elif task.owner == AgentRole.OVERWORLD:
                    proposal = propose_overworld(
                        self.llm,
                        task=task,
                        obs=obs,
                        memory=memory_text,
                        vision_only=self.vision_only,
                        walkthrough_hint=walkthrough_hint,
                    )
                elif task.owner == AgentRole.BATTLE:
                    proposal = propose_battle(
                        self.llm,
                        task=task,
                        obs=obs,
                        memory=memory_text,
                        vision_only=self.vision_only,
                        walkthrough_hint=walkthrough_hint,
                    )
                else:
                    # MVP: unimplemented owners fall back to overworld macros.
                    console.print(
                        f"[yellow]Owner {task.owner.value} not fully implemented; "
                        "using overworld proposer.[/yellow]"
                    )
                    self.arbiter.set_owner(AgentRole.OVERWORLD)
                    task.owner = AgentRole.OVERWORLD
                    proposal = propose_overworld(
                        self.llm,
                        task=task,
                        obs=obs,
                        memory=memory_text,
                        vision_only=self.vision_only,
                        walkthrough_hint=walkthrough_hint,
                    )
            except Exception as err:
                self.store.append(
                    "llm_error",
                    {"error": str(err), "owner": task.owner.value},
                )
                self.env.push_event("alert", f"LLM error (fallback macro): {err}")
                console.print(f"[yellow]LLM error, using fallback macro:[/yellow] {err}")
                if task.owner == AgentRole.BATTLE:
                    proposal = ActionProposal(
                        task_id=task.task_id,
                        agent=AgentRole.BATTLE,
                        reason="fallback after LLM failure",
                        actions=[GameAction.PRESS_A],
                    )
                    self.arbiter.set_owner(AgentRole.BATTLE)
                else:
                    proposal = ActionProposal(
                        task_id=task.task_id,
                        agent=AgentRole.OVERWORLD,
                        reason="fallback after LLM failure",
                        actions=[
                            GameAction.HOLD_B_120,
                            GameAction.PRESS_A,
                            GameAction.HOLD_B_120,
                            GameAction.PRESS_A,
                            GameAction.WAIT_60,
                        ],
                    )
                    self.arbiter.set_owner(AgentRole.OVERWORLD)

            action_labels = [a.value for a in proposal.actions]
            announce = (
                f"[{proposal.agent.value}] {proposal.reason} → {action_labels}"
            )
            self.env.push_event("decision", announce)
            console.print(f"[magenta]next[/magenta] {announce}")
            before_fp = (
                obs.map_name,
                obs.x,
                obs.y,
                obs.facing,
                obs.dialog_active,
                Path(obs.screenshot_path).stat().st_size
                if obs.screenshot_path and Path(obs.screenshot_path).exists()
                else 0,
            )
            result = self.arbiter.apply(proposal)
            after = self.env.observe()
            after_fp = (
                after.map_name,
                after.x,
                after.y,
                after.facing,
                after.dialog_active,
                Path(after.screenshot_path).stat().st_size
                if after.screenshot_path and Path(after.screenshot_path).exists()
                else 0,
            )
            if after_fp == before_fp and result.executed_actions:
                self._noop_streak += 1
                self.stuck_score += 1
                self.env.push_event(
                    "alert",
                    f"noop x{self._noop_streak}: actions did not change screen/state",
                )
            else:
                self._noop_streak = 0
            self._last_fingerprint = after_fp
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
                + (f" [noop={self._noop_streak}]" if self._noop_streak else "")
            )
            # Durable memory of what was tried and what changed (or didn't).
            if self.memory.enabled:
                pos_bit = (
                    f"RAM {after.map_name or '?'}@({after.x},{after.y})"
                    if not self.vision_only
                    else "vision-only"
                )
                outcome = (
                    f"noop x{self._noop_streak}"
                    if self._noop_streak
                    else (result.stopped_early_because or "ok")
                )
                self.memory.note(
                    f"step{steps} [{proposal.agent.value}] {proposal.reason[:120]} "
                    f"→ {[a.value for a in result.executed_actions][:6]} "
                    f"| {pos_bit} | {outcome}"
                )
            steps += 1

            # Keep ~prompt_interval_s between prompt cycles; actions already ran live.
            if self.prompt_interval_s > 0:
                remaining = self.prompt_interval_s - (time.time() - cycle_started)
                if remaining > 0:
                    time.sleep(remaining)
        self.store.append("run_end", {"run_id": self.run_id, "steps": steps})
        self.close()

    def close(self) -> None:
        self.llm.close()
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
