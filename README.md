# Agentic Nuzlocke Runner

Autonomous **Pokemon Red-family Nuzlocke** driven by configurable LLM role agents and a deterministic action/rules layer.

Emulation, REST API, and the live **Field Log** dashboard come from [NousResearch/pokemon-agent](https://github.com/NousResearch/pokemon-agent) (PyBoy). This repo owns orchestration, the Nuzlocke rules engine (level caps, encounter/permadeath ledgers), OptMem, the walkthrough skill, and the LLM provider switch.

- **Operator / agent handoff:** `AGENTS.md` (start here for how to run and what not to break)
- **Long-form design intent:** `AGENT_READY_PLAN.md` / `PLAN.md` (aspirational; not all built)

---

## Current status (honest)

Working:

- Pokemon Red/Blue-style `.gb` via `pokemon-agent` + dashboard at `http://127.0.0.1:8765/dashboard`
- Configurable LLM backends (`cursor` default, `openai_compatible` stub for local models later)
- Vision turns: Overworld / Battle / Recovery attach the current **160×144** screenshot
- **Fixed prompt cadence, no RAM-based readiness gating:** the emulator runs in real time and the orchestrator just observes + prompts every `prompt_interval_s` (default 2s) regardless of what's on screen — `joy_ignore`/`dialog_active` can be wrong on ROM hacks like Red Star, so nothing about *when to prompt* depends on them. The agent recognizes dialog/menus visually and proposes `skip_dialog` itself.
- **Short-term `recent`** (last ~8 actions/outcomes) in each prompt; **OptMem** for long-term landmarks/rollups only
- **Walkthrough skill** (`.cursor/skills/pokemon-red-walkthrough/`) — excerpt injected when stuck; copied into agent workspace
- **Vision-only is how we actually run this** (default **on**; `--with-ram` still exists in code but isn't part of the supported path — RAM state on ROM hacks like Red Star can be wrong, so nothing here should depend on it): prompts get screenshot + memory (+ walkthrough when stuck), no RAM JSON
- Prompt cadence ~2s; announce actions → execute with 0.1s per-press gap
- Overworld: short bursts with optional multi-tile `walk_*_N` macros (max 12 logical); Battle: up to 4
- Agent-owned objectives + landmark notes; OptMem text rollup every 25 steps
- Action Arbiter is the only writer of button presses; early-stop on dialog / battle / map change
- Append-only `runs/<run-id>/events.jsonl` + SQLite; dashboard events (`reasoning` / `decision` / `action` / …)
- Cursor provider: **one durable agent for the whole run**, compacted (self-summarized + recreated) once input context passes `compact_at_tokens`, + retries; orchestrator **fallback macro** if LLM still fails
- Mid-burst execute uses light `/state` peeks; full screenshot only at cycle boundaries
- **Nuzlocke referee**: level cap advances automatically with badges earned (through Elite Four), deterministic first-encounter and permadeath ledgers (`nuzlocke/orchestration/ledger.py`) — no separate Encounter/Box/Team agent, just facts injected into the existing Overworld/Battle/Recovery prompts
- **Battle type hint**: lean Gen-1 type-effectiveness lookup (`nuzlocke/referee/type_chart.py`) surfaced per-party-member against the current enemy — a strategic signal, not a full damage calculator
- **Crash-recovery checkpoints**: periodic `/save` outside battle and away from a just-committed ledger event; `nuzlocke run --resume <run-id>` reloads the latest checkpoint (never used to undo a committed death — see `no_outcome_rollback`)
- Milestones extend through all 8 gyms + Elite Four + Champion (`config/run.yaml`)

Partial / stub:

- FireRed / mGBA adapter (pokemon-agent marks FireRed as Phase 2)
- No generation-aware damage calculator (only the lean type-chart hint above)

Known pitfall:

- **ROM hacks (including Red Star) can make RAM lie.** Map/dialog flags may say “Red’s House” while the screen shows Oak text or the `YOUR NAME?` keyboard. Confirmed live: `dialog.active`/`joy_ignore` read `false`/`0` (no dialog) while the screenshot clearly showed an active Oak dialogue box mid-print. This is why the orchestrator no longer uses RAM for prompt-cadence or action-gating decisions — it's screenshot-only, on a fixed timer. Agents must **trust the screenshot**.

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

No RAM-based readiness polling: each cycle is **observe (screenshot) → prompt → announce → execute (0.1s between presses) → wait** so the next prompt is ~every N seconds from the start of the cycle, regardless of what's mid-animation on screen. `joy_ignore`/`dialog_active` were found to be wrong on Red Star (RAM said no dialog was active while the screen clearly showed one) — so nothing about *when to prompt* trusts them anymore. The agent recognizes dialog/menus/animations visually and proposes `skip_dialog` itself when it sees scrolling text.

| Source | Default |
|--------|---------|
| `config/run.yaml` → `prompt_interval_s` | `2.0` |
| `config/run.yaml` → `press_interval_s` | `0.1` |
| Env `NUZLOCKE_PROMPT_INTERVAL_S` | overrides prompt cadence |

`skip_dialog` is a client-side macro (agent-requested, up to 30 rounds internally) that mashes B+A through narrative text, stopping early on naming or when the dialog lock clears — it's still convenient to use `joy_ignore` as a *mechanical* stop condition inside that mash loop (worst case it mashes a few extra/too-few times), which is a much lower-stakes use than gating whether to act at all.

### Vision-only mode

This is the only supported mode: role LLMs get the screenshot + OptMem (+ walkthrough when stuck), never RAM map/coords/collision/dialog JSON.

| Source | Default |
|--------|---------|
| `config/run.yaml` → `vision_only` | `true` |
| Env `NUZLOCKE_VISION_ONLY=0` | include RAM JSON (code path still exists, not part of the supported flow) |

### OptMem

`nuzlocke/memory/optmem.py` is a small in-repo durable-notes store (a capped, append-only `notes.log` per run — no external CLI). Each run uses `runs/<run-id>/memory/`. Used for durable landmarks/rollups only — not per-step history (that goes in prompt `recent`).

Disable: `memory.enabled: false` or `NUZLOCKE_MEMORY=0`.

### Walkthrough skill

`.cursor/skills/pokemon-red-walkthrough/` — early-game Red/Red-Star guide (`SKILL.md` + `reference.md`).

When stuck (`noop ≥ 2` or `stuck ≥ 3`), the orchestrator injects a relevant `walkthrough_hint`. Director stays deterministic on stuck/noop ≥ 2 and routes to Recovery (one vision call). Skill files live in `agent_workspace/skills/` but agents should not `Read` them when a hint is already present.

### Screenshots / media resolution

Frames are native **160×144** RGBA PNGs. Cursor `SDKImage` supports optional pixel `dimension` metadata only — **no** Gemini `media_resolution` (low/medium/high) on this path. Vision-only does not by itself reduce image token cost; Gemini 3 often budgets ~1120 tokens per image at default settings.

### Cost (order of magnitude)

~1800 vision prompts / hour on `gemini-3.6-flash` with thinking off: roughly **~$10–15/hr** at Google list rates (Cursor usage pool; Teams may add $0.25/M). Sonnet is several× more. The durable agent's periodic self-summarize-and-recreate compaction keeps history+prior-image token growth bounded over long runs.

---

## Commands

```bash
# No LLM — observe + walk a few tiles (env / arbiter / events smoke)
uv run nuzlocke smoke --rom /path/to/game.gb

# Autonomous segment — until dashboard STOP (vision-only by default)
uv run nuzlocke run --rom /path/to/game.gb

# Include RAM JSON in prompts
uv run nuzlocke run --rom /path/to/game.gb --with-ram

# Optional cap for smoke / CI
uv run nuzlocke run --rom /path/to/game.gb --max-steps 20
```

Artifacts under `runs/<run-id>/`:

- `manifest.json` — game, model, vision_only, memory flag, rules snapshot
- `events.jsonl` / `run.sqlite` — proposals, observations, arbiter results
- `screenshots/latest.png` — last frame sent to vision
- `memory/` — OptMem `notes.log`
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
| `config/run.yaml` | ROM, ports, cadence (`prompt_interval_s`), `vision_only`, OptMem, milestones, `checkpoint` |
| `config/rules_red.yaml` | Nuzlocke clauses + level caps (hashed into the run manifest) |
| `config/agents.yaml` | Provider, model, retries |

---

## Architecture (MVP loop)

```text
Dashboard START/PAUSE/STOP
        │
        ▼
 observe() — screenshot, every prompt_interval_s (no RAM-based wait)
        │
        ▼
 RunLoop ──► recent + OptMem wake ──► walkthrough_hint if stuck
        │     referee.advance(badges) ──► ledger.update (encounter/death)
        ▼
 Director → Overworld / Battle / Recovery
        │     screenshot + memory + nuzlocke facts
        │     (Battle also gets a type-effectiveness hint)
        ▼
 announce → ActionArbiter → pokemon-agent /action
        │
        ▼
 recent ring + optional landmark/rollup notes (+ Field Log)
        │
        ▼
 periodic crash-recovery checkpoint (outside battle, away from a fresh ledger commit)
```

Important behaviors:

- **Screenshot is the only thing the agent trusts** — RAM (`joy_ignore`/`dialog_active`) has been observed reporting no-dialog while a real dialog box was on screen, so nothing about pacing or gating depends on it. The agent recognizes what's on screen visually and proposes `skip_dialog` itself.
- **Noop detection**: unchanged map/position/facing/dialog/screenshot fingerprint raises stuck score; Recovery may take over.
- **LLM failure**: provider retries → then safe fallback macro; run continues.
- Arbiter stops a macro early on dialog start, battle start, or map transition (best-effort — see known pitfall about RAM reliability above).

Layout:

```text
nuzlocke/
  agents/          # prompts + role helpers
  environment/     # Nous Red HTTP adapter + checkpoints
  knowledge/       # walkthrough excerpt loader
  llm/             # cursor + openai_compatible providers
  memory/          # OptMem (in-repo durable-notes store)
  orchestration/   # RunLoop, arbiter, stuck/fallback/ledger/checkpoint helpers
  referee/         # level caps, encounter/death ledgers, Gen-1 type chart
  state/           # pydantic contracts + event store
apps/orchestrator/ # CLI: nuzlocke smoke | run [--resume]
.cursor/skills/    # pokemon-red-walkthrough
config/
runs/
```

---

## Tests

```bash
uv run pytest -q
```

Unit coverage: JSON extraction, arbiter owner enforcement, OptMem wrapper, walkthrough excerpts, stuck/noop tracker, LLM-error fallback, referee cap/encounter/death ledger, type chart, checkpoint gating.

---

## Roadmap vs this tree

`AGENT_READY_PLAN.md` is the original, larger aspirational design (separate Encounter/Box/Team LLM agents, a `@smogon/calc` microservice, a hash-chained ledger). This tree deliberately implements a leaner version of the same rules — deterministic bookkeeping in the referee/ledger, surfaced into the existing role prompts, rather than more agent roles — since encounter legality and permadeath tracking don't need model judgment. Remaining gap:

1. FireRed adapter behind the same `GameEnvironment` protocol (pokemon-agent itself marks FireRed as Phase 2)
2. A real generation-aware damage calculator, if the lean type-chart hint proves insufficient
