# Agentic Nuzlocke Runner

Autonomous **Pokemon Red-family Nuzlocke** driven by configurable LLM role agents and a deterministic action/rules layer.

Emulation, REST API, and the live **Field Log** dashboard come from [NousResearch/pokemon-agent](https://github.com/NousResearch/pokemon-agent) (PyBoy). This repo owns orchestration, the Nuzlocke rules engine (level caps, encounter/permadeath ledgers), OptMem, the walkthrough skill, and the LLM provider switch.

- **Operator / agent handoff:** `AGENTS.md` (start here for how to run and what not to break)
- **Long-form design intent:** `AGENT_READY_PLAN.md` / `PLAN.md` (aspirational; not all built)

---

## Current status (honest)

Working:

- Pokemon Red/Blue-style `.gb` via `pokemon-agent` + dashboard at `http://127.0.0.1:8765/dashboard`
- Three systems (`dual` default): **System 1** is [Jev](https://docs.typesafe.ai/concepts/system-one.md) plus code. Every cycle it chooses a goal (a door, a map edge, a person, explore) or a menu row, and code walks the A* path or moves the cursor. **System 2** is a Cursor vision director that is called only on a decision (no objective, objective done or unreachable, Jev unsure, a goal that keeps failing); it reads System 1's journal and sets the next objective. **System 3**, the Nuzlocke controller (`nuzlocke/agents/system3.py`), is deterministic: no items except Poké Balls; it buys balls in Viridian after the Pokédex, catches the first wild encounter in each area, runs from wild battles below 25% HP, heals at a Pokémon Center (or Mom) below 50% or when poisoned, briefs System 1 and 2 with the rules, the level cap, the next boss, and known trainers (`nuzlocke/knowledge/trainers_red.yaml`), and ends the run on a wipe. System 2 also writes a plan for every trainer battle. `cursor` (one vision model per cycle) and an `openai_compatible` stub remain
- Vision turns: planner / Overworld / Battle / Recovery attach the current frame as pokemon-agent's **4× grid overlay** (640×576, labelled A1..J9 walk cells, player boxed at E5); pixel checks use the native 160×144 frame
- **No RAM-based readiness gating:** `joy_ignore`/`dialog_active` can be wrong on ROM hacks like Red Star, so nothing about *when to prompt* depends on them. The emulator is **not** real time — pokemon-agent only advances frames inside `/action` — so text is given time to print with wait frames sent in the action, not by sleeping. An open text box with no prompt is mashed with `skip_dialog` (B taps until the box closes or settles; never A) without another planner call; a YES/NO or name list above it always gets a planner look first, because B there answers NO.
- **Short-term `recent`** (last ~8 actions/outcomes) in each prompt; **OptMem** for long-term landmarks/rollups only
- **Walkthrough skill** (`.cursor/skills/pokemon-red-walkthrough/`) — excerpt injected when stuck; copied into agent workspace
- **Vision-only is how we actually run this** (default **on**; `--with-ram` still exists in code but isn't part of the supported path — RAM state on ROM hacks like Red Star can be wrong, so nothing here should depend on it): prompts get screenshot + memory (+ walkthrough when stuck), no RAM JSON
- One `walk_*` press is one tile from any facing (a press into a wall only turns the player)
- System 1 reads RAM that describes what is drawn or placed: the tilemap text inside ┌─┐ frames (dialog and menus), and the warp, sign, sprite, size, and edge tables (`GET /map/objects`, served by `nuzlocke/environment/pa_serve.py`). It never gates input on RAM dialog flags
- Walk grid withheld on a map once real walks contradict it (`GridTrust`)
- Overworld: short bursts with optional multi-tile `walk_*_N` macros (max 12 logical); Battle: up to 4
- Agent-owned objectives + landmark notes; OptMem text rollup every 25 steps
- Action Arbiter is the only writer of button presses; a walk burst stops on an unchanged tile, a text box, a battle, or a map change
- Append-only `runs/<run-id>/events.jsonl` + SQLite; dashboard events (`reasoning` / `decision` / `action` / …)
- Cursor provider: **one durable agent for the whole run**, compacted (self-summarized + recreated) once input context passes `compact_at_tokens`, + retries; orchestrator **fallback macro** if LLM still fails
- Mid-burst execute peeks `/state` after each button and checks the screenshot before the next overworld walk; a full observe still runs once at the end of the cycle
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

No RAM-based readiness polling: each cycle is **observe (screenshot) → decide → announce → execute (0.1s between presses) → wait** until at least `prompt_interval_s` has passed since the cycle started. `joy_ignore`/`dialog_active` were found to be wrong on Red Star (RAM said no dialog was active while the screen clearly showed one) — so nothing about *when to prompt* trusts them anymore.

The emulator does **not** run between cycles. pokemon-agent runs PyBoy headless and only advances frames inside `/action` (`press_*` and `walk_*` are 20 frames, `wait_N` is N). The old 0.5s wait let nothing happen in the game, and a bare B press left the next line half-printed — the planner read "of POKEMON LEAGUE are rea". Text boxes are now paged with the button plus `wait_60`, so each press moves one whole box, and the wait between cycles only paces the run for a human watching.

A ▶ menu — NEW GAME, the NAME lists, the starter's YES/NO, START — is read from the decoded tilemap text, and Jev picks the row; code moves the highlight and presses A. Paging stops at a prompt by itself (checked on the emulator: a press or a held B stops at the prompt), but the next B answers NO and turns the starter down, so an unsure answer at a YES/NO goes to System 2 instead of being guessed.

| Source | Default |
|--------|---------|
| `config/run.yaml` → `prompt_interval_s` | `0.1` |
| `config/run.yaml` → `press_interval_s` | `0.1` |
| Env `NUZLOCKE_PROMPT_INTERVAL_S` | overrides prompt cadence |

`skip_dialog` is a client-side macro (agent-requested, up to 6 rounds internally) that taps **B** through narrative text: each round is `hold_b_30` then `wait_30` with B released. It stops when the box closes, when the whole frame stops changing for two rounds (the blinking ▼ is masked out), when a prompt appears, or on naming lock. The picture above the box counts: in battle, "CHARMANDER used SCRATCH!" sits unchanged while the move and the HP bar animate, and B does nothing until they finish. A new box is paged before any planner look, battle narration included; the FIGHT menu and the move list do not read as a text box, so the mash stops there. Remaining walks in the same burst are dropped, and no walk is pressed while a box is open. If a mash leaves an open box unchanged, the next cycle asks the planner and presses its button. The Pokédex page before the starter's YES/NO sets the naming bit, so `skip_dialog` leaves it alone; A turns it.

Why taps: pokemon-agent's `hold_X_N` releases with no frames after it, and nothing runs between `/action` calls, so two holds in a row are one unbroken press and Gen 1 text advances only on a new press. Four `hold_b_120` never closed Oak's "which POKéMON do you want?"; two tap rounds did. `execute` now sends `wait_12` after every `hold_*`, and `wait_30` after a burst's last `press_a`, because the box A opens is drawn only after `press_a` returns.

B advances ordinary Gen 1 text, and B in the overworld starts nothing, while an A press while facing an NPC re-opens the box that was just closed. A fallback that tapped A when a box seemed to ignore B re-opened Oak every cycle in run `20260928-205856-f65040`; the box had only been fed one long hold. The earlier `hold_b_120 + press_a` version exited only on a `joy_ignore` bit-5 transition; that bit reads 0 through real dialog on Red Star, so the exit never fired, every call ran to completion, and the trailing A re-opened the NPC. That made `skip_dialog` a fixed point rather than an escape: run `20260821-164159-3c5a68` spent its final 33 minutes and ~200 vision calls alternating `skip_dialog` / `press_a` in front of Prof Oak. Termination is now visual and needs no RAM.

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

The early-game beat script (`nuzlocke/knowledge/beats.py`) owns the objective from Red's bedroom through leaving Pallet onto Route 1. Its short hint is attached to every overworld planner call. The planner cannot replace that objective. When stuck, a longer `walkthrough_hint` excerpt is appended. Director stays deterministic and uses the current beat instead of aiming at the next gym. Skill files live in `agent_workspace/skills/` but agents should not `Read` them when a hint is already present.

### Progress detection

Hashing the whole frame cannot see a dialogue loop — animating text changes the PNG every cycle, so `noop_streak` stayed at 0 through ~200 wasted steps in run `20260821-164159-3c5a68`. `nuzlocke/environment/screen.py` splits each 160×144 frame at row 96, the top of the Gen 1 text box:

- **`noop_streak`** — whole frame byte-identical.
- **`no_progress_streak`** — the *world* region (rows 0–95) is identical. Opening or closing a text box does not move it, so an NPC re-talk loop reads as exactly what it is. Text advancing is not progress. Water and NPC animation do change this region, so a walk into the shore can look like progress.
- **`immobile_streak`** — a walk left `(map, x, y)` and the facing unchanged. That direction is blocked on the current tile only, the step is labeled `immobile` instead of `ok`, and the next cycle asks the planner again. The blocked set is cleared when the player leaves the tile, when a text box opens, and when a fourth side would be blocked: a scripted scene (the rival walking to his ball) refuses every walk without there being any wall. Before a walk counts as immobile, `execute` checks whether the picture is still moving; if it is, it sends `wait_30` rounds until it is still, then presses the walk once more. A first press into a wall turns the player and is not counted: that is how a path faces a ball, and the `press_a` after that turn goes out in the same burst.

`no_progress`, `blocked_on_tile`, and the action signatures that keep failing are passed into the role prompts as evidence.

Escalation is tiered, because one undifferentiated Recovery call is not an escape hatch — it is the same vision agent looking at the same frozen screen (it fired 222 times in that run and proposed the same two actions every time):

| tier | trigger | response |
|---|---|---|
| 1 | `no_progress ≥ 24` or the noop/stuck/loop rules | Recovery vision call when Jev is not the actor. An immobile walk still forces a planner refresh |
| 2 | `no_progress ≥ 48`, 40 frozen cycles on one tile, or `immobile ≥ 12` | **deterministic disengage, no LLM** — `press_b` then walk off the tile, skipping directions blocked on this tile |
| 3 | `no_progress ≥ 72` | Recovery with `reframe`: assume the objective is already complete and set a new one |
| 4 | `no_progress ≥ 120` | disengage, drop a stale planner `primary`, write an `ANTI` note, reset every streak. A code-owned beat stays |

Memory rollups are suppressed while stuck. They are generated from `recent`, so rolling up mid-loop distils the loop itself into durable "facts" that `wake()` then feeds back every cycle — that run's `notes.log` restates "deliver Oak's Parcel" six times, long after the parcel was delivered.

### Screenshots / media resolution

Frames are native **160×144** RGBA PNGs for every pixel check. Vision calls attach `GET /screenshot/grid?scale=4` instead: the same frame at 640×576 with labelled A1..J9 walk cells and the player boxed at E5, so the model can count cells to a door or a ball. On a raw 160×144 frame the planner said the player faced "the middle Poké Ball" from the lab's top-left corner. The grid frame is fetched only when a vision call runs, and an older server without the endpoint falls back to the native frame. Cursor `SDKImage` gets the file's real pixel size as `dimension` metadata — **no** Gemini `media_resolution` (low/medium/high) on this path. Gemini 3 often budgets ~1120 tokens per image at default settings.

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

# Headless sandbox: a private emulator on a copy of a run's savestate
uv run nuzlocke sandbox --from <run-id> --script "skip_dialog walk_down*2 wait_30"
uv run nuzlocke sandbox --from <run-id> --steps 30   # the real loop, no dashboard
```

`nuzlocke sandbox` never touches the source run: it copies the savestate into a new `runs/sandbox-*` folder and starts its own pokemon-agent on the first free port from 8791, then stops it. `--script` presses buttons with no LLM and prints map, tile, facing, and whether a text box or prompt is up after each one. It saves frames to `frames/` and ends by saving the final state, so `--from sandbox-<id>` continues from the last row. `--steps N` runs the real planner and Jev headless for N cycles and writes `summary.json` (planner looks and why each happened, planner seconds per look, median cycle time, tiles visited, burst stops, and Jev's confidence, unsure share, state size, and latency). Omit `--from` to boot the ROM fresh. See AGENTS.md → Headless sandbox.

Artifacts under `runs/<run-id>/`:

- `manifest.json` — game, model, vision_only, memory flag, rules snapshot
- `events.jsonl` / `run.sqlite` — proposals, observations, arbiter results
- `screenshots/latest.png` — last frame sent to vision
- `savestates/auto.state` — continue point for `--resume`
- `memory/` — OptMem `notes.log`
- `agent_workspace/` — Cursor local cwd (includes walkthrough skill copy)

---

## LLM configuration (`config/agents.yaml`)

Default is `dual`. **System 1** runs every cycle with no vision call: Jev picks one goal from a menu built in `nuzlocke/agents/goals.py` (`exit_N`, `edge_<dir>`, `talk_N`, `explore`, `heading_<dir>`, `wait`), each option carrying its facts (path length, CURRENT OBJECTIVE, went nowhere before), and code presses the A* path as one burst of up to 8 walks. Menus are answered the same way from the decoded screen text, text boxes are paged with `skip_dialog`, the title is START, and a cutscene (the game ignores the D-pad or walks the player, read from `wJoyIgnore` and `wStatusFlags5` bit 7) is waited out. **System 2** (the `planner` model) looks at the grid screenshot only on a trigger: no objective, objective not on this map, objective done, Jev unsure twice, a goal failed three times, an unsure YES/NO, or text that did not page. It reads `runs/<run-id>/journal.jsonl` since its last look and returns an objective (`target`: exit / edge / npc / cell, and `done_when`), not buttons. The early-game beat script owns the objective until Route 1, each beat with a machine target, so the intro needs no System 2 look. In battle Jev picks FIGHT / PKMN / ITEM / RUN and then the move, from options that carry HP, type matchup, and PP (`nuzlocke/agents/battle.py`). Before any decision the adapter runs frames until there is one to make (`settle()`): a step, a cutscene, or a battle animation is never decided on. The beat script owns the objective from the bedroom through Oak's Parcel and Viridian Forest to Brock. Paths use every screen seen on the map, and exploration heads for the edge of the known map. After a System 2 look, overworld triggers wait 8 cycles. pokemon-agent's enemy data, type ids, and map names are wrong in places; see AGENTS.md pitfalls #26–#28. A goal that ends in the same text twice (someone blocking a road) counts as failed. Only the naming keyboard still uses the older planner-card path. Stuck tiers 2 and 4 stay mechanical.

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

## Architecture

```text
Dashboard START/PAUSE/STOP
        │
        ▼
 observe() — screenshot (blank-LCD wait), then RAM: /state, walk grid, /map/objects
        │
        ▼
 RunLoop ──► referee.advance(badges) ──► ledger.update (encounter/death)
        │     beat script (early game) ──► objective with a machine target
        │     stuck tiers 2/4: disengage · tiers 1/3: Recovery vision call
        ▼
 System 1 (agents/system1.py, Jev + code, no vision)
        │     menu row · skip_dialog · START · overworld goal → A* burst
        │     battle / naming → older planner-card path
        │     a decision it cannot make → trigger
        ▼
 System 2 (vision director) ── only on a trigger: screenshot + journal → objective
        │
        ▼
 ActionArbiter → pokemon-agent /action
        │
        ▼
 room map · goal failures · journal line · (periodic) continue savestate
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
  knowledge/       # walkthrough excerpts + early-game beat script
  llm/             # cursor, jev, openai_compatible providers
  memory/          # OptMem (in-repo durable-notes store)
  orchestration/   # RunLoop, arbiter, stuck/fallback/ledger/checkpoint helpers
  referee/         # level caps, encounter/death ledgers, Gen-1 type chart
  state/           # pydantic contracts + event store
apps/orchestrator/ # CLI: nuzlocke smoke | run [--resume] | sandbox
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
