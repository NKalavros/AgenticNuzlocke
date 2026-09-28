# Agentic Nuzlocke Runner

Autonomous **Pokemon Red-family Nuzlocke** driven by configurable LLM role agents and a deterministic action/rules layer.

Emulation, REST API, and the live **Field Log** dashboard come from [NousResearch/pokemon-agent](https://github.com/NousResearch/pokemon-agent) (PyBoy). This repo owns orchestration, the Nuzlocke rules engine (level caps, encounter/permadeath ledgers), OptMem, the walkthrough skill, and the LLM provider switch.

- **Operator / agent handoff:** `AGENTS.md` (start here for how to run and what not to break)
- **Long-form design intent:** `AGENT_READY_PLAN.md` / `PLAN.md` (aspirational; not all built)

---

## Current status (honest)

Working:

- Pokemon Red/Blue-style `.gb` via `pokemon-agent` + dashboard at `http://127.0.0.1:8765/dashboard`
- Configurable LLM backends (`dual` default: Cursor vision planner + Jev button choices; `cursor` single model; `openai_compatible` stub for local models later)
- Vision turns: Overworld / Battle / Recovery attach the current **160×144** screenshot
- **Fixed prompt cadence, no RAM-based readiness gating:** the emulator runs in real time and the orchestrator just observes + prompts every `prompt_interval_s` (default 0.5s) regardless of what's on screen — `joy_ignore`/`dialog_active` can be wrong on ROM hacks like Red Star, so nothing about *when to prompt* depends on them. An open text box is cleared with `skip_dialog` without another planner call.
- **Short-term `recent`** (last ~8 actions/outcomes) in each prompt; **OptMem** for long-term landmarks/rollups only
- **Walkthrough skill** (`.cursor/skills/pokemon-red-walkthrough/`) — excerpt injected when stuck; copied into agent workspace
- **Vision-only is how we actually run this** (default **on**; `--with-ram` still exists in code but isn't part of the supported path — RAM state on ROM hacks like Red Star can be wrong, so nothing here should depend on it): prompts get screenshot + memory (+ walkthrough when stuck), no RAM JSON
- Prompt cadence ~0.5s; announce actions → execute with 0.1s per-press gap
- Overworld: short bursts with optional multi-tile `walk_*_N` macros (max 12 logical); Battle: up to 4
- Agent-owned objectives + landmark notes; OptMem text rollup every 25 steps
- Action Arbiter is the only writer of button presses; early-stop on dialog / battle / map change
- Append-only `runs/<run-id>/events.jsonl` + SQLite; dashboard events (`reasoning` / `decision` / `action` / …)
- Cursor provider: **one durable agent for the whole run**, compacted (self-summarized + recreated) once input context passes `compact_at_tokens`, + retries; orchestrator **fallback macro** if LLM still fails
- Mid-burst execute uses light `/state` peeks; full screenshot only at cycle boundaries
- **Nuzlocke referee**: level cap advances automatically with badges earned (through Elite Four), deterministic first-encounter and permadeath ledgers (`nuzlocke/orchestration/ledger.py`) — no separate Encounter/Box/Team agent, just facts injected into the existing Overworld/Battle/Recovery prompts
- **Battle type hint**: lean Gen-1 type-effectiveness lookup (`nuzlocke/referee/type_chart.py`) surfaced per-party-member against the current enemy — a strategic signal, not a full damage calculator
- **Continue savestate**: `runs/<run-id>/savestates/auto.state` is written every 50 steps and again on dashboard STOP (not mid-battle, and not right after a committed death or encounter). `uv run nuzlocke run --resume <run-id>` loads it, so the intro does not have to be played again.
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
3. For the default `dual` backend: `CURSOR_API_KEY` in the environment, and `JEV_API_KEY` in the environment or `.env` (startup loads `.env` without overriding keys that are already set)

`pokemon-agent` is installed from GitHub (not PyPI) via `uv` sources in `pyproject.toml`. Package files live under the project venv only:

`.venv/lib/python3.*/site-packages/pokemon_agent/`

Do **not** search `$HOME` for the package.

---

## Setup

```bash
cd /Users/nikolas/Desktop/Projects/260727_AgenticNuzlocke
uv sync
export CURSOR_API_KEY=...   # planner (System 2). JEV_API_KEY can live in .env
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
| `config/run.yaml` → `prompt_interval_s` | `0.5` |
| `config/run.yaml` → `press_interval_s` | `0.1` |
| Env `NUZLOCKE_PROMPT_INTERVAL_S` | overrides prompt cadence |

`skip_dialog` is a client-side macro (agent-requested, up to 6 rounds internally) that mashes **B** through narrative text, stopping when the text-box region of the frame stops changing — or on naming lock / map / battle transition. Remaining walks/A in the same burst are dropped so a long mash cannot re-A a TV/NPC.

It is deliberately **B-only and B-terminated**. B advances Gen 1 text exactly like A, but B in the overworld starts nothing, while an A press while facing an NPC re-opens the box that was just closed. The earlier `hold_b_120 + press_a` version exited only on a `joy_ignore` bit-5 transition; that bit reads 0 through real dialog on Red Star, so the exit never fired, every call ran to completion, and the trailing A re-opened the NPC. That made `skip_dialog` a fixed point rather than an escape: run `20260821-164159-3c5a68` spent its final 33 minutes and ~200 vision calls alternating `skip_dialog` / `press_a` in front of Prof Oak. Termination is now visual and needs no RAM.

`a_until_dialog_end` is served by the same macro — pokemon-agent's version reads a `state["dialog_active"]` key that does not exist (the real one is `state["dialog"]["active"]`), so it always stops after a single A press.

### Vision-only mode

This is the only supported mode: role LLMs get the screenshot + OptMem (+ walkthrough when stuck), never RAM map/coords/collision/dialog JSON.

| Source | Default |
|--------|---------|
| `config/run.yaml` → `vision_only` | `true` |
| Env `NUZLOCKE_VISION_ONLY=0` | include RAM JSON (code path still exists, not part of the supported flow) |

### OptMem

`nuzlocke/memory/optmem.py` is a small in-repo durable-notes store (a capped, append-only `notes.log` per run — no external CLI). Each run uses `runs/<run-id>/memory/`. Used for durable landmarks/rollups only — not per-step history (that goes in prompt `recent`).

Off by default. Enable: `memory.enabled: true` or `NUZLOCKE_MEMORY=1`.

### Walkthrough skill

`.cursor/skills/pokemon-red-walkthrough/` — early-game Red/Red-Star guide (`SKILL.md` + `reference.md`).

When stuck (`noop ≥ 2`, `stuck ≥ 3`, `loop ≥ 3` ping-pong, or `no_progress ≥ 6`), the orchestrator injects a relevant `walkthrough_hint`. Director stays deterministic on any stuck path and routes to Recovery (one vision call). Skill files live in `agent_workspace/skills/` but agents should not `Read` them when a hint is already present.

### Progress detection

Hashing the whole frame cannot see a dialogue loop — animating text changes the PNG every cycle, so `noop_streak` stayed at 0 through ~200 wasted steps in run `20260821-164159-3c5a68`. `nuzlocke/environment/screen.py` splits each 160×144 frame at row 96, the top of the Gen 1 text box:

- **`noop_streak`** — whole frame byte-identical.
- **`no_progress_streak`** — the *world* region (rows 0–95) is identical. Opening or closing a text box does not move it, so an NPC re-talk loop reads as exactly what it is. Text advancing is not progress.

`no_progress` and the action signatures that keep failing are passed into the role prompts as evidence, and step outcomes are labelled `no_progress xN` instead of `ok`.

Escalation is tiered, because one undifferentiated Recovery call is not an escape hatch — it is the same vision agent looking at the same frozen screen (it fired 222 times in that run and proposed the same two actions every time):

| tier | trigger | response |
|---|---|---|
| 1 | `no_progress ≥ 6` or the noop/stuck/loop rules | Recovery vision call, now carrying `no_progress` evidence |
| 2 | `no_progress ≥ 12` or 20 cycles on one tile | **deterministic disengage, no LLM** — `press_b` then walk off the tile, rotating direction |
| 3 | `no_progress ≥ 20` | Recovery with `reframe`: assume the objective is already complete and set a new one |
| 4 | `no_progress ≥ 40` | disengage, drop the stale `primary` objective, write an `ANTI` note, reset every streak |

Memory rollups are suppressed while stuck. They are generated from `recent`, so rolling up mid-loop distils the loop itself into durable "facts" that `wake()` then feeds back every cycle — that run's `notes.log` restates "deliver Oak's Parcel" six times, long after the parcel was delivered.

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

# Continue that run from its savestate (skip the intro)
uv run nuzlocke run --resume <run-id>

# Include RAM JSON in prompts
uv run nuzlocke run --rom /path/to/game.gb --with-ram

# Optional cap for smoke / CI
uv run nuzlocke run --rom /path/to/game.gb --max-steps 20
```

Artifacts under `runs/<run-id>/`:

- `manifest.json` — game, model, vision_only, memory flag, rules snapshot
- `events.jsonl` / `run.sqlite` — proposals, observations, arbiter results
- `screenshots/latest.png` — last frame sent to vision
- `savestates/auto.state` — continue point for `--resume`
- `memory/` — OptMem `notes.log`
- `agent_workspace/` — Cursor local cwd (includes walkthrough skill copy)

---

## LLM configuration (`config/agents.yaml`)

Default is `dual`: a Cursor vision model writes a short plan from the screenshot (System 2), and [Jev](https://docs.typesafe.ai/concepts/system-one.md) picks one legal button per cycle from that plan (System 1). Jev is text-only, so it never sees the image. The planner looks again when the scene changes (naming, battle, the text box closing), when Jev says the plan is stale or already done, on two low-confidence answers, and at least every `plan_every_s` (default 45). While someone is speaking the loop presses one button and looks again every few seconds. The RAM map is not the scene during that speech. Stuck tiers 2 and 4 stay mechanical and drop the plan.

```yaml
provider: dual
planner:
  model: grok-4.7
  params:
    reasoning_effort: low
  plan_every_s: 45
jev:
  api_key_env: JEV_API_KEY
  model: jev-latest
```

Single vision model (planner and buttons are the same call):

```yaml
provider: cursor
cursor:
  model: gemini-3.6-flash
  params:
    effort: minimal
  max_retries: 5
```

Grok 4.5 medium (slower, more deliberate):

```yaml
cursor:
  model: grok-4.5
  params:
    effort: medium
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
| `config/agents.yaml` | Provider, planner model, Jev, retries |

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
 Director (deterministic) → stuck tiers, else:
        │     dual: Planner vision call only when the plan is stale
        │           → Jev picks one legal action
        │     cursor: Overworld / Battle vision call
        │     Recovery on stuck tiers 1 and 3 (screenshot + nuzlocke facts)
        ▼
 announce → ActionArbiter → pokemon-agent /action
        │
        ▼
 recent ring + optional landmark/rollup notes (+ Field Log)
        │
        ▼
 periodic continue savestate (outside battle, away from a fresh ledger commit)
```

Important behaviors:

- **Screenshot is the only thing the agent trusts** — RAM (`joy_ignore`/`dialog_active`) has been observed reporting no-dialog while a real dialog box was on screen, so nothing about pacing or gating depends on it. The agent recognizes what's on screen visually and proposes `skip_dialog` itself.
- **Noop / loop detection**: unchanged fingerprint raises `noop_streak`; left/right or two-tile ping-pong raises `loop_streak`. Recovery may take over. Repeated LANDMARK notes are not rewritten; noop walks are recorded as `ANTI` / `failed_approaches` so Recovery cannot replay them.
- **LLM failure**: provider retries → then safe fallback macro; run continues.
- Arbiter stops a macro early on dialog start, battle start, or map transition (best-effort — see known pitfall about RAM reliability above).

Layout:

```text
nuzlocke/
  agents/          # prompts + role helpers
  environment/     # Nous Red HTTP adapter + checkpoints
  knowledge/       # walkthrough excerpt loader
  llm/             # cursor, jev, openai_compatible providers
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
