"""CLI entrypoint: nuzlocke serve / smoke / run."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from nuzlocke.orchestration.loop import RunLoop, scripted_smoke

app = typer.Typer(add_completion=False, no_args_is_help=True)
console = Console()


@app.command("smoke")
def smoke(
    rom: Optional[Path] = typer.Option(
        None, "--rom", help="Path to Pokemon Red/Blue .gb ROM"
    ),
    steps: int = typer.Option(5, "--steps", help="Tiles to walk"),
) -> None:
    """Scripted observe + walk (no LLM). Validates env + arbiter + dashboard events."""
    try:
        result = scripted_smoke(rom, steps=steps)
    except FileNotFoundError as err:
        console.print(f"[red]{err}[/red]")
        raise typer.Exit(code=1) from err
    except RuntimeError as err:
        console.print(f"[red]{err}[/red]")
        raise typer.Exit(code=1) from err
    console.print_json(json.dumps(result, indent=2, default=str))
    console.print(f"[green]Dashboard:[/green] {result['dashboard']}")


@app.command("run")
def run(
    rom: Optional[Path] = typer.Option(
        None, "--rom", help="Path to Pokemon Red/Blue .gb ROM"
    ),
    provider: Optional[str] = typer.Option(
        None, "--provider", help="cursor | openai_compatible"
    ),
    max_steps: Optional[int] = typer.Option(
        -1,
        "--max-steps",
        help="Stop after N agent steps. Default -1 = run until dashboard STOP.",
    ),
    vision_only: Optional[bool] = typer.Option(
        None,
        "--vision-only/--with-ram",
        help="Screenshot (+ memory) only for role prompts; omit RAM JSON. "
        "Default from config/run.yaml or NUZLOCKE_VISION_ONLY.",
    ),
) -> None:
    """Start an autonomous Nuzlocke segment. Runs until STOP unless --max-steps is set."""
    steps = None if max_steps is None or max_steps < 0 else max_steps
    try:
        loop = RunLoop(
            rom_path=rom,
            provider_override=provider,
            vision_only=vision_only,
        )
    except FileNotFoundError as err:
        console.print(f"[red]{err}[/red]")
        raise typer.Exit(code=1) from err
    except RuntimeError as err:
        console.print(f"[red]{err}[/red]")
        raise typer.Exit(code=1) from err
    console.print(f"[cyan]Run directory:[/cyan] {loop.run_dir}")
    console.print(
        f"[cyan]Provider:[/cyan] {loop.agents_cfg.get('provider')} "
        f"model={ (loop.agents_cfg.get('cursor') or {}).get('model') }"
    )
    if steps is None:
        console.print(
            "[cyan]Limit:[/cyan] none — press STOP on the dashboard when done reviewing"
        )
    else:
        console.print(f"[cyan]Limit:[/cyan] {steps} agent steps")
    prompt_iv = float(loop.run_cfg.get("prompt_interval_s", 2.0))
    console.print(
        f"[cyan]Pace:[/cyan] prompt ~every {prompt_iv:g}s → announce → real-time actions "
        f"(NUZLOCKE_PROMPT_INTERVAL_S)"
    )
    console.print(
        f"[cyan]Vision:[/cyan] "
        + (
            "screenshot + OptMem only (no RAM in prompts)"
            if loop.vision_only
            else "screenshot + RAM JSON"
        )
    )
    console.print(
        f"[cyan]Memory:[/cyan] "
        + (
            f"OptMem on → {loop.run_dir / 'memory'}"
            if loop.memory.enabled
            else "off"
        )
    )
    loop.run(max_steps=steps)


@app.callback()
def main() -> None:
    """Multi-agent Nuzlocke runner."""


if __name__ == "__main__":
    app()
