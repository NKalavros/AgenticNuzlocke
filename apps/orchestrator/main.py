"""CLI entrypoint: nuzlocke smoke / run / sandbox."""

from __future__ import annotations

import contextlib
import json
from collections.abc import Iterator
from pathlib import Path

import typer
from rich.console import Console

from nuzlocke.config import ensure_relay_routing, load_project_env
from nuzlocke.orchestration.loop import RunLoop, scripted_smoke

app = typer.Typer(add_completion=False, no_args_is_help=True)
console = Console()
load_project_env()
ensure_relay_routing()

ROM_OPTION = typer.Option(None, "--rom", help="Path to Pokemon Red/Blue .gb ROM")
PROVIDER_OPTION = typer.Option(None, "--provider", help="cursor | openai_compatible | dual")


@contextlib.contextmanager
def _exit_on(*errors: type[Exception]) -> Iterator[None]:
    """Print a setup error in red and exit 1 instead of a traceback."""
    try:
        yield
    except errors as err:
        console.print(f"[red]{err}[/red]")
        raise typer.Exit(code=1) from err


@app.command("smoke")
def smoke(
    rom: Path | None = ROM_OPTION, steps: int = typer.Option(5, "--steps", help="Tiles to walk")
) -> None:
    """Scripted observe + walk (no LLM). Validates env + arbiter + dashboard events."""
    with _exit_on(FileNotFoundError, RuntimeError):
        result = scripted_smoke(rom, steps=steps)
    console.print_json(json.dumps(result, indent=2, default=str))
    console.print(f"[green]Dashboard:[/green] {result['dashboard']}")


@app.command("run")
def run(
    rom: Path | None = ROM_OPTION,
    provider: str | None = PROVIDER_OPTION,
    max_steps: int | None = typer.Option(
        -1, "--max-steps", help="Stop after N agent steps. Default -1 = run until dashboard STOP."
    ),
    vision_only: bool | None = typer.Option(
        None,
        "--vision-only/--with-ram",
        help="Screenshot (+ memory) only for role prompts; omit RAM JSON. "
        "Default from config/run.yaml or NUZLOCKE_VISION_ONLY.",
    ),
    resume: str | None = typer.Option(
        None,
        "--resume",
        help="Continue run-id from its savestate (runs/<run-id>/savestates/) "
        "instead of starting a new game.",
    ),
) -> None:
    """Start an autonomous Nuzlocke segment. Runs until STOP unless --max-steps is set."""
    steps = None if max_steps is None or max_steps < 0 else max_steps
    with _exit_on(FileNotFoundError, RuntimeError):
        loop = RunLoop(
            rom_path=rom,
            run_id=resume,
            resume=bool(resume),
            provider_override=provider,
            vision_only=vision_only,
        )
    cfg = loop.agents_cfg
    console.print(f"[cyan]Run directory:[/cyan] {loop.run_dir}")
    if cfg.get("provider") == "dual":
        planner, jev = (cfg.get("planner") or {}), (cfg.get("jev") or {})
        models = f"planner={planner.get('model')} jev={jev.get('model')}"
    else:
        models = f"model={(cfg.get('cursor') or {}).get('model')}"
    console.print(f"[cyan]Provider:[/cyan] {cfg.get('provider')} {models}")
    limit = (
        "none — press STOP on the dashboard when done reviewing"
        if steps is None
        else f"{steps} agent steps"
    )
    console.print(f"[cyan]Limit:[/cyan] {limit}")
    prompt_iv = float(loop.run_cfg.get("prompt_interval_s", 2.0))
    console.print(
        f"[cyan]Pace:[/cyan] prompt ~every {prompt_iv:g}s → announce → real-time actions "
        "(NUZLOCKE_PROMPT_INTERVAL_S)"
    )
    if not loop.vision_only:
        vision = "screenshot + RAM JSON"
    elif loop.memory.enabled:
        vision = "screenshot + OptMem only (no RAM in prompts)"
    else:
        vision = "screenshot only (no RAM in prompts)"
    console.print(f"[cyan]Vision:[/cyan] {vision}")
    memory = f"OptMem on → {loop.run_dir / 'memory'}" if loop.memory.enabled else "off"
    console.print(f"[cyan]Memory:[/cyan] {memory}")
    loop.run(max_steps=steps)


@app.command("sandbox")
def sandbox(
    source: str | None = typer.Option(
        None, "--from", help="Run id whose savestate to start from. Omit to boot the ROM fresh."
    ),
    state: str = typer.Option("auto", "--state", help="Savestate name in that run."),
    script: str | None = typer.Option(
        None,
        "--script",
        help="Buttons to press with no LLM, e.g. 'skip_dialog walk_down*2 wait_30'.",
    ),
    steps: int = typer.Option(30, "--steps", help="Loop cycles when no --script is given."),
    port: int | None = typer.Option(
        None, "--port", help="Emulator port. Default: the first free port from 8791."
    ),
    provider: str | None = PROVIDER_OPTION,
    rom: Path | None = ROM_OPTION,
) -> None:
    """Try the current code on a private emulator. The live run and its port are untouched."""
    from nuzlocke.config import load_run_config
    from nuzlocke.environment.nous_red import NousRedEnvironment
    from nuzlocke.orchestration.checkpoint import CHECKPOINT_NAME, stage_for_boot
    from nuzlocke.orchestration.loop import configured_rom
    from nuzlocke.orchestration.sandbox import (
        format_rows,
        free_port,
        new_sandbox,
        parse_script,
        run_script,
        summarize,
    )

    with _exit_on(FileNotFoundError, ValueError):
        tokens = parse_script(script) if script else None
        run_id, run_dir = new_sandbox(source, state=state)
    port = port or free_port()
    console.print(f"[cyan]Sandbox:[/cyan] {run_dir} on port {port}")

    if tokens is not None:
        if source:
            stage_for_boot(run_dir)
        env = NousRedEnvironment(
            base_url=f"http://127.0.0.1:{port}",
            run_dir=run_dir,
            rom_path=configured_rom(rom, load_run_config()),
            auto_start=True,
            press_interval_s=0.0,
            load_state=CHECKPOINT_NAME if source else None,
        )
        try:
            if source:
                env.load_checkpoint(CHECKPOINT_NAME)
            rows = run_script(env, tokens, run_dir / "frames")
            env.save_checkpoint(CHECKPOINT_NAME)
        finally:
            env.shutdown()
        (run_dir / "probe.jsonl").write_text(
            "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
        )
        typer.echo(format_rows(rows))
        typer.echo(f"frames: {run_dir / 'frames'}")
        typer.echo(f"continue from the last row: nuzlocke sandbox --from {run_id}")
        return

    with _exit_on(FileNotFoundError, RuntimeError):
        loop = RunLoop(
            rom_path=rom,
            run_id=run_id,
            resume=bool(source),
            provider_override=provider,
            port=port,
            headless=True,
        )
    try:
        loop.run(max_steps=max(1, steps))
    finally:
        loop.env.shutdown()
    report = summarize(run_dir)
    (run_dir / "summary.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    console.print_json(json.dumps(report))


@app.callback()
def main() -> None:
    """Multi-agent Nuzlocke runner."""


if __name__ == "__main__":
    app()
