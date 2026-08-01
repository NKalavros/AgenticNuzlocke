# AGENTS.md — Agentic Nuzlocke handoff

Operating notes for humans and coding agents working in this repo. Prefer this file + `README.md` over `PLAN.md` / `AGENT_READY_PLAN.md` for **what exists today**.

## What this project is

Autonomous **Pokemon Red-family Nuzlocke** runner:

- Emulation + Field Log dashboard: [NousResearch/pokemon-agent](https://github.com/NousResearch/pokemon-agent) (PyBoy)
- Our code: orchestration, Action Arbiter, OptMem, walkthrough skill, Cursor / OpenAI-compatible LLM providers
- Default ROM in config: Red Star (`red-star-2020-08-18.gb`) — legally obtained ROMs are gitignored

## Quick start

```bash
cd /Users/nikolas/Desktop/Projects/260727_AgenticNuzlocke
uv sync
export CURSOR_API_KEY=...   # required for default cursor provider
uv run pytest -q
uv run nuzlocke run --rom ./red-star-2020-08-18.gb --vision-only
```

Watch: http://127.0.0.1:8765/dashboard — press **START** / **PAUSE** / **STOP**.  
Cursor SDK turns: Agents panel → Filter → Source → SDK.

Default run length: **until dashboard STOP** (`--max-steps -1`). Vision-only is the default in `config/run.yaml`.

## Do / don’t

| Do | Don’t |
|----|--------|
| Look for `pokemon-agent` under `.venv/lib/python3.*/site-packages/pokemon_agent/` | Search `$HOME` or the whole disk for packages |
| Trust **screenshots** over RAM on Red Star | Blind-walk from map/coords alone |
| Only prompt the LLM when input-ready (orchestrator gate) | Spend LLM turns on dialog/animations |
| Keep changes scoped; update README/AGENTS when behavior changes | Restart a live run unless the user asks |
| Commit only when the user asks | Commit ROMs, `.env`, or `runs/*` artifacts |

## Runtime loop (truth)

```text
dashboard control
    → wait_until_input_ready   # auto-advance dialog; wait animations
    → OptMem wake
    → (if stuck) walkthrough_hint excerpt
    → Director → Overworld | Battle | Recovery
    → announce actions → ActionArbiter → /action
    → OptMem note
    → sleep to prompt_interval_s
```

### Cadence (`config/run.yaml`)

- `prompt_interval_s: 1.5` — min wall time between **prompt cycles** (`NUZLOCKE_PROMPT_INTERVAL_S`)
- `press_interval_s: 0.1` — tiny gap between buttons in a burst
- `max_actions_per_proposal: 12` — logical actions; `walk_*_2`…`_5` macros count as one
- `input_ready.enabled: true` — only invoke LLM when the agent can act
  - bit 5 dialog → auto mash B+A
  - bit 6 naming → prompt immediately
  - other locks → short wait (~3s), then prompt
- Action **`skip_dialog`**: agent-requested mash through narrative text (stops on naming)
- Multi-tile walks: `walk_up_3` etc. expand client-side before `/action`

### Vision

- Screenshots: native **160×144** PNG from `GET /screenshot`
- Attached via Cursor `SDKImage.from_file` with `dimension=(160,144)` metadata only
- **No Gemini `media_resolution`** (low/medium/high) on this SDK path — vision-only does not change image token billing by itself
- `vision_only` default **true** (`--with-ram` / `NUZLOCKE_VISION_ONLY=0` to include RAM JSON). Orchestrator still uses RAM for battle/boot routing and stuck scoring
- Cursor provider recreates the agent **every turn** so conversation history (and prior screenshots) cannot accumulate

### Memory (OptMem)

- Vendored CLI: `third_party/optmem/memo` ([VictorTaelin/OptMem](https://github.com/VictorTaelin/OptMem))
- Per run: `runs/<run-id>/memory/` via `MEMORY_DIR`
- Orchestrator: `wake` before prompt, `note` after step, deterministic auto-`nap`
- Default `wake_lines: 24`; `rollup_every: 25` runs a text-only memory compression (no screenshot)
- Agent may emit `objectives` + `landmarks` → dashboard / `LANDMARK` OptMem notes
- Disable: `memory.enabled: false` or `NUZLOCKE_MEMORY=0`

### Walkthrough skill

- Project skill: `.cursor/skills/pokemon-red-walkthrough/` (`SKILL.md` + `reference.md`)
- Copied into `runs/<run-id>/agent_workspace/skills/pokemon-red-walkthrough/`
- On stuck (`noop ≥ 2` or `stuck ≥ 3`): orchestrator injects a relevant `walkthrough_hint`
- When a hint is injected, Cursor agents must **not** `Read` skill files (excerpt is enough)
- Stuck / noop ≥ 2: Director stays deterministic → Recovery (one vision LLM call, never Director+Recovery)

## Config map

| File | Purpose |
|------|---------|
| `config/agents.yaml` | Provider + model (default `gemini-3.6-flash`, `thinking: "false"`) |
| `config/run.yaml` | ROM, ports, cadence, `vision_only`, `input_ready`, OptMem |
| `config/rules_red.yaml` | Nuzlocke clauses / level caps (hashed into manifest) |

Swap model without code changes — edit `config/agents.yaml` (e.g. `claude-sonnet-4-6` for stability).

## Layout

```text
nuzlocke/
  agents/           # prompts + role helpers
  environment/      # Nous Red HTTP adapter (observe / execute / input-ready)
  knowledge/        # walkthrough excerpt loader
  llm/              # cursor + openai_compatible providers
  memory/           # OptMem wrapper
  orchestration/    # RunLoop + ActionArbiter
  referee/          # rules stub
  state/            # pydantic contracts + event store
apps/orchestrator/  # CLI: nuzlocke smoke | run
.cursor/skills/     # pokemon-red-walkthrough
third_party/optmem/ # vendored memo CLI
config/
runs/               # per-run artifacts (gitignored)
```

## Known pitfalls (read before debugging)

1. **RAM lies on Red Star** — map may say “Red’s House” while the screen shows Oak text or a naming keyboard.
2. **Up/down house thrash** — model mislabels interior as Pallet outdoors; OptMem + walkthrough exist to break that loop.
3. **Battles without input-ready gating** waste many LLM turns on “Enemy used X!” text — gating must stay enabled.
4. **Naming screen** — walks move the letter cursor; must finish **END**.
5. pokemon-agent’s `a_until_dialog_end` checks a flat `dialog_active` key incorrectly; we prefer `hold_b_120` + `press_a` / our own ready loop.

## Cost (order of magnitude)

~1800 vision prompts / hour at 2s cadence on `gemini-3.6-flash`: roughly **~$10–15/hr** at Google list rates if thinking stays off (Cursor usage pool; Teams may add $0.25/M). Sonnet is several× more. Screenshots dominate tokens (~1120/image); keeping Cursor turns one-shot (no history bleed) matters more than prompt trimming after a few minutes.

## Tests / handoff checklist

```bash
uv run pytest -q          # expect unit tests green
uv run nuzlocke --help
# Live review:
uv run nuzlocke run --rom ./red-star-2020-08-18.gb
# STOP on dashboard when done
# Optional: --with-ram to include RAM JSON in prompts
```

Still stubbed vs `AGENT_READY_PLAN.md`: Encounter / Box / Team / Smogon calc / full referee / FireRed.
