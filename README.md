# Agentic Nuzlocke Runner

Autonomous **Pokemon Red-family Nuzlocke** driven by configurable LLM role agents and a deterministic action/rules layer.

Emulation, REST API, and the live **Field Log** dashboard come from [NousResearch/pokemon-agent](https://github.com/NousResearch/pokemon-agent) (PyBoy). This repo owns orchestration, OptMem, the walkthrough skill, Nuzlocke bookkeeping stubs, and the LLM provider switch.

- **Operator / agent handoff:** `AGENTS.md` (start here for how to run and what not to break)
- **Long-form design intent:** `AGENT_READY_PLAN.md` / `PLAN.md` (aspirational; not all built)

---

## Current status (honest)

Working:

- Pokemon Red/Blue-style `.gb` via `pokemon-agent` + dashboard at `http://127.0.0.1:8765/dashboard`
- Configurable LLM backends (`cursor` default, `openai_compatible` stub for local models later)
- Vision turns: Overworld / Battle / Recovery attach the current **160×144** screenshot
- **Input-ready gating:** LLM is prompted only when the joypad is free; dialog/animations are auto-advanced or waited out
- **OptMem** durable memory per run (`runs/<id>/memory`) — wake before prompt, note after step
- **Walkthrough skill** (`.cursor/skills/pokemon-red-walkthrough/`) — excerpt injected when stuck; copied into agent workspace
- Optional **vision-only** mode: prompts get screenshot + memory (+ walkthrough when stuck), no RAM JSON
- Prompt cadence ~2s; announce actions → execute with 0.1s per-press gap
- Overworld: short bursts (~1–3 actions, max 8); Battle: up to 4 menu actions when input-ready
- Action Arbiter is the only writer of button presses; early-stop on dialog / battle / map change
- Append-only `runs/<run-id>/events.jsonl` + SQLite; dashboard events (`reasoning` / `decision` / `action` / …)
- Cursor provider retries (default 5) + agent recreate; orchestrator **fallback macro** if LLM still fails

Partial / stub:

- Encounter, Box, Team Planner, Smogon calc service, full referee ledgers
- FireRed / mGBA adapter (pokemon-agent marks FireRed as Phase 2)

Known pitfall:

- **ROM hacks (including Red Star) can make RAM lie.** Map/dialog flags may say “Red’s House” while the screen shows Oak text or the `YOUR NAME?` keyboard. Agents must **trust the screenshot**.

---

## Requirements

1. Python **3.12+** and [uv](https://github.com/astral-sh/uv)
2. A legally obtained **`.gb`** ROM (Red/Blue-compatible). Path via `--rom`, `NUZLOCKE_ROM`, or `config/run.yaml` → `rom_path`
3. For the default backend: `CURSOR_API_KEY` in the environment

`pokemon-agent` is installed from GitHub (not PyPI) via `uv` sources in `pyproject.toml`. Package files live under the project venv only:

`.venv/lib/python3.*/site-packages/pokemon_agent/`

Do **not** search `$HOME` for the package.

---

## Setup

```bash
cd /Users/nikolas/Desktop/Projects/260727_AgenticNuzlocke
uv sync
export CURSOR_API_KEY=...   # if not already set
```

Optional ROM env override:

```bash
export NUZLOCKE_ROM=/absolute/path/to/game.gb
```

---

## Watching a run

| What | Where |
|------|--------|
| Game + Field Log (THINK / DECIDE / ACT, objectives, START/PAUSE/STOP) | [http://127.0.0.1:8765/dashboard](http://127.0.0.1:8765/dashboard) |
| Cursor agent turns (tools / stream) | Cursor **Agents** → **Filter → Source → SDK** |

Press **START** on the dashboard if the orchestrator is waiting (`respect_dashboard_control: true`). Press **STOP** when done reviewing — runs continue until STOP by default (no step cap).

---

## Behavior reference

### Prompt cadence

Each ready cycle: **prompt → announce → execute (0.1s between presses) → wait** so the next prompt is ~every N seconds from the moment the game became input-ready.

| Source | Default |
|--------|---------|
| `config/run.yaml` → `prompt_interval_s` | `2.0` |
| `config/run.yaml` → `press_interval_s` | `0.1` |
| Env `NUZLOCKE_PROMPT_INTERVAL_S` | overrides prompt cadence |

### Input-ready gating

Configured under `config/run.yaml` → `input_ready`:

- `joy_ignore` bit 5 (`0x20`, dialog) → orchestrator auto-mashes B+A (no LLM)
- bit 6 (`0x40`, naming keyboard) → **prompt immediately** (never wait-spin)
- other nonzero bits → short `wait_30` (~3s timeout), then prompt
- Agents may emit **`skip_dialog`** to mash B+A through unlocked Red Star text / leftover narration

`skip_dialog` is a client-side macro (up to `skip_dialog_max_rounds`), stopping early on naming or when a dialog lock clears.

### Vision-only mode

Role LLMs omit RAM map/coords/collision/dialog JSON — screenshot + OptMem (+ walkthrough when stuck). Orchestrator still uses RAM for battle/boot routing and stuck scoring.

| Source | Default |
|--------|---------|
| `config/run.yaml` → `vision_only` | `false` |
| CLI `--vision-only` / `--with-ram` | overrides YAML |
| Env `NUZLOCKE_VISION_ONLY=1` | overrides YAML when CLI omitted |

### OptMem

[OptMem](https://github.com/VictorTaelin/OptMem) is vendored at `third_party/optmem/memo`. Each run uses `runs/<run-id>/memory/`. Orchestrator `wake` / `note` / auto-`nap`.

Disable: `memory.enabled: false` or `NUZLOCKE_MEMORY=0`.

### Walkthrough skill

`.cursor/skills/pokemon-red-walkthrough/` — early-game Red/Red-Star guide (`SKILL.md` + `reference.md`).

When stuck (`noop ≥ 2` or `stuck ≥ 3`), the orchestrator injects a relevant `walkthrough_hint`. The skill is copied into `agent_workspace/skills/` for on-demand `Read`.

### Screenshots / media resolution

Frames are native **160×144** RGBA PNGs. Cursor `SDKImage` supports optional pixel `dimension` metadata only — **no** Gemini `media_resolution` (low/medium/high) on this path. Vision-only does not by itself reduce image token cost; Gemini 3 often budgets ~1120 tokens per image at default settings.

### Cost (order of magnitude)

~1800 vision prompts / hour on `gemini-3.6-flash` with thinking off: roughly **~$10–15/hr** at Google list rates (Cursor usage pool; Teams may add $0.25/M). Sonnet is several× more.

---

## Commands

```bash
# No LLM — observe + walk a few tiles (env / arbiter / events smoke)
uv run nuzlocke smoke --rom /path/to/game.gb

# Autonomous segment — until dashboard STOP
uv run nuzlocke run --rom /path/to/game.gb

# Vision-only (screenshot + memory, no RAM in prompts)
uv run nuzlocke run --rom /path/to/game.gb --vision-only

# Optional cap for smoke / CI
uv run nuzlocke run --rom /path/to/game.gb --max-steps 20
```

Artifacts under `runs/<run-id>/`:

- `manifest.json` — game, model, vision_only, memory flag, rules snapshot
- `events.jsonl` / `run.sqlite` — proposals, observations, arbiter results
- `screenshots/latest.png` — last frame sent to vision
- `memory/` — OptMem LOG + TREE
- `agent_workspace/` — Cursor local cwd (includes walkthrough skill copy)

---

## LLM configuration (`config/agents.yaml`)

Default (fast vision + OptMem):

```yaml
provider: cursor
cursor:
  model: gemini-3.6-flash
  params:
    thinking: "false"
  max_retries: 5
```

More stable / slower:

```yaml
cursor:
  model: claude-sonnet-4-6
  params:
    thinking: "false"
```

Composer Fast:

```yaml
cursor:
  model: composer-2.5
  params:
    fast: "true"
```

Later local models:

```yaml
provider: openai_compatible
openai_compatible:
  base_url: http://127.0.0.1:8000/v1
  model: qwen3
```

Note: the OpenAI-compatible path is text-only today (screenshot paths are noted in the prompt but not uploaded).

---

## Run / rules config

| File | Role |
|------|------|
| `config/run.yaml` | ROM, ports, cadence, `vision_only`, `input_ready`, OptMem, milestones |
| `config/rules_red.yaml` | Nuzlocke clauses + level caps (hashed into the run manifest) |
| `config/agents.yaml` | Provider, model, retries |

---

## Architecture (MVP loop)

```text
Dashboard START/PAUSE/STOP
        │
        ▼
 wait_until_input_ready  (auto dialog / wait animations)
        │
        ▼
 RunLoop ──► OptMem wake ──► walkthrough_hint if stuck
        │
        ▼
 Director → Overworld / Battle / Recovery
        │     screenshot [+ RAM unless vision_only] + memory
        ▼
 announce → ActionArbiter → pokemon-agent /action
        │
        ▼
 OptMem note + events (+ Field Log)
```

Important behaviors:

- **Screenshot is ground truth** when RAM disagrees (ROM hacks).
- **Noop detection**: unchanged map/position/facing/dialog/screenshot fingerprint raises stuck score; Recovery may take over.
- **LLM failure**: provider retries → then safe fallback macro; run continues.
- Arbiter stops a macro early on dialog start, battle start, or map transition.

Layout:

```text
nuzlocke/
  agents/          # prompts + role helpers
  environment/     # Nous Red HTTP adapter + input-ready wait
  knowledge/       # walkthrough excerpt loader
  llm/             # cursor + openai_compatible providers
  memory/          # OptMem wrapper
  orchestration/   # arbiter + run loop
  referee/         # rules stub
  state/           # pydantic contracts + event store
apps/orchestrator/ # CLI: nuzlocke smoke | run
.cursor/skills/    # pokemon-red-walkthrough
third_party/optmem/
config/
runs/
```

---

## Tests

```bash
uv run pytest -q
```

Unit coverage: JSON extraction, arbiter owner enforcement, OptMem wrapper, walkthrough excerpts.

---

## Roadmap vs this tree

Next increments aligned with `AGENT_READY_PLAN.md`:

1. Encounter Agent + immutable encounter ledger
2. Battle Agent + `@smogon/calc` Gen 1 service
3. Box / rare-candy audit path + Team Planner dossier
4. Crash-only checkpoints (no outcome rollback)
5. FireRed adapter behind the same `GameEnvironment` protocol
