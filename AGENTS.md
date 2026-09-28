# AGENTS.md — Agentic Nuzlocke handoff

Operating notes for humans and coding agents working in this repo. Prefer this file + `README.md` over `PLAN.md` / `AGENT_READY_PLAN.md` for **what exists today**.

## What this project is

Autonomous **Pokemon Red-family Nuzlocke** runner:

- Emulation + Field Log dashboard: [NousResearch/pokemon-agent](https://github.com/NousResearch/pokemon-agent) (PyBoy)
- Our code: orchestration, Action Arbiter, the Nuzlocke referee (level caps + encounter/death ledgers), OptMem, walkthrough skill, Cursor planner / Jev actor / OpenAI-compatible LLM providers
- Default ROM in config: Red Star (`red-star-2020-08-18.gb`) — legally obtained ROMs are gitignored

## Quick start

```bash
cd /Users/nikolas/Desktop/Projects/260727_AgenticNuzlocke
uv sync
export CURSOR_API_KEY=...   # planner. JEV_API_KEY is read from .env for the default dual provider
# Startup sets NODE_USE_ENV_PROXY and the HTTP/2 preload only when a proxy
# is already configured, or when NUZLOCKE_RELAY=1 and gost is listening.
# On an open network leave NUZLOCKE_RELAY unset so Cursor connects directly.
uv run pytest -q
uv run nuzlocke run --rom ./red-star-2020-08-18.gb --vision-only
```

Watch: http://127.0.0.1:8765/dashboard — press **START** / **PAUSE** / **STOP**.  
Cursor SDK turns: Agents panel → Filter → Source → SDK.

Default run length: **until dashboard STOP** (`--max-steps -1`). Vision-only is the default in `config/run.yaml`.

After a crash, or when you don't want to replay the intro, continue the same run from its savestate:

```bash
uv run nuzlocke run --resume <run-id>
```

The state is `runs/<run-id>/savestates/auto.state`, written every 50 steps and again on dashboard STOP (not mid-battle, and not in the few steps after a death or encounter is committed). A resumed run loads that file and plays forward from there.

## Do / don’t

| Do | Don’t |
|----|--------|
| Look for `pokemon-agent` under `.venv/lib/python3.*/site-packages/pokemon_agent/` | Search `$HOME` or the whole disk for packages |
| Trust **screenshots** over RAM on Red Star | Blind-walk from map/coords alone, or gate behavior on `joy_ignore`/`dialog_active` |
| Let the emulator run in real time and just observe on a fixed cadence | Add back RAM-based readiness polling — it was removed after `dialog_active` was confirmed false while a real dialog was on screen |
| Keep changes scoped; update README/AGENTS when behavior changes | Restart a live run unless the user asks |
| Commit only when the user asks | Commit ROMs, `.env`, or `runs/*` artifacts |

## Runtime loop (truth)

```text
dashboard control
    → observe()   # screenshot, no RAM-based wait — game runs in real time
    → referee.advance(badges) → ledger.update (encounter/death)
    → OptMem wake
    → (if stuck) walkthrough_hint excerpt
    → Director (deterministic)
    → dual: Planner (screenshot) only when the plan is stale → Jev picks one legal button
      cursor: Overworld | Battle vision call
      stuck tier 1/3: Recovery vision call (becomes the next Jev plan in dual mode)
      stuck tier 2/4: mechanical disengage, plan dropped
    → announce actions → ActionArbiter → /action
    → OptMem note
    → (periodic, and again on STOP) continue savestate
    → sleep to prompt_interval_s
```

### Cadence (`config/run.yaml`)

- `prompt_interval_s: 0.5` — wall time between **prompt cycles** (`NUZLOCKE_PROMPT_INTERVAL_S`); no RAM-based readiness gating — the emulator just runs and each cycle looks at whatever is on screen
- `press_interval_s: 0.1` — tiny gap between buttons in a burst
- `max_actions_per_proposal: 12` — logical actions; `walk_*_2`…`_5` macros count as one
- Action **`skip_dialog`**: agent-requested mash through narrative text. **B-only, never A** — it stops when the text-box region of the frame stops changing (max 6 rounds), on naming lock, or on a map/battle transition; no walks after it in the same burst. `a_until_dialog_end` is served by the same macro (pitfall #5)
- Multi-tile walks: `walk_up_3` etc. expand client-side before `/action`

### Vision

- Screenshots: native **160×144** PNG from `GET /screenshot`
- Attached via Cursor `SDKImage.from_file` with `dimension=(160,144)` metadata only
- **No Gemini `media_resolution`** (low/medium/high) on this SDK path — vision-only does not change image token billing by itself
- `vision_only` default **true** — this is the only supported path. RAM is not used for prompt cadence, action gating, or dialog detection anymore (see known pitfall #6): `joy_ignore`/`dialog_active` were confirmed wrong on Red Star. RAM is still read for the Nuzlocke referee (badges/party/battle — deterministic bookkeeping, not shown to the LLM) since there's no reliable vision-only substitute for permadeath/encounter tracking
- Cursor provider keeps one durable agent (the planner, in dual mode); when context hits ``compact_at_tokens`` (default 250k) it asks for a short session summary, then recreates with that summary carried forward
- Dual mode (`config/agents.yaml`): Jev (`POST /v1/systemone`, key `JEV_API_KEY`) chooses one button per cycle from a code-built menu. It does not see pixels. The planner model (default `grok-4.7`, `reasoning_effort: low`) rewrites the plan from the screenshot on a scene change, a stale/done judgment, two low-confidence answers, every `plan_every_s` (45), or after about 6 cycles stuck on one tile with an overworld plan. An open text box is one press at a time (B, or A when the plan says so) and the planner looks again every few seconds. The RAM map is not the scene while someone is still speaking. A name list or other highlight menu is `press_a` on the highlighted row. The naming keyboard is one press per look: the plan's button runs once, then the screenshot is read again. A name list or other highlight menu is `press_a` on the highlighted row.

### Memory (OptMem)

- In-repo module: `nuzlocke/memory/optmem.py` — a capped, append-only `notes.log` per run (no external CLI)
- Per run: `runs/<run-id>/memory/notes.log`
- Orchestrator: `wake` before prompt (last `wake_lines` notes), `note` after step
- Short-term: orchestrator injects `recent` (last ~8 actions + outcomes) into each prompt
- Long-term OptMem: landmarks / rollups only (not every step). `rollup_every: 25`
- Agent may emit `objectives` + `landmarks` → dashboard / `LANDMARK` OptMem notes
- OptMem is off by default. Enable with `memory.enabled: true` or `NUZLOCKE_MEMORY=1`

### Walkthrough skill

- Project skill: `.cursor/skills/pokemon-red-walkthrough/` (`SKILL.md` + `reference.md`)
- Copied into `runs/<run-id>/agent_workspace/skills/pokemon-red-walkthrough/`
- On stuck (`noop ≥ 2`, `stuck ≥ 3`, `loop ≥ 3` left/right/tile ping-pong, or `no_progress ≥ 6`): orchestrator injects a relevant `walkthrough_hint`
- When a hint is injected, Cursor agents must **not** `Read` skill files (excerpt is enough)
- Director stays deterministic on any stuck path → Recovery (one vision LLM call, never Director+Recovery). Recovery must not repeat `failed_approaches`; discount stuck only after a non-noop recovery.

## Progress detection & the escalation ladder

Two independent signals, because they catch different failures:

| signal | means | blind to |
|---|---|---|
| `noop_streak` | whole frame byte-identical | dialogue loops — animating text changes the PNG every cycle |
| `no_progress_streak` | **world region** (frame rows 0–95, above the Gen 1 text box) identical | nothing relevant; opening/closing a text box does not move it |

`nuzlocke/environment/screen.py` splits every frame at `DIALOG_TOP = 96`. Degrades to whole-file hashing without Pillow/NumPy.

Tiers (`StuckTracker.escalation_tier`), in prompt cycles — roughly 1 / 2 / 3 / 6 minutes at the ~9s/cycle a real run achieves:

| tier | trigger | response |
|---|---|---|
| 1 | `no_progress ≥ 24`, or a long noop/stuck/loop | LLM Recovery only when Jev is not the actor. With Jev, a few wrong joystick presses stay on the stick |
| 2 | `no_progress ≥ 48`, or 40 cycles on one tile while the world region is also frozen, or `stuck_score ≥ 24` | **deterministic disengage — no LLM**: `press_b` + walk off the tile, rotating direction each time. A menu or cutscene keeps the same RAM tile while the picture changes; that does not skip Jev |
| 3 | `no_progress ≥ 72` | Recovery with `reframe`: "assume your objective is already complete, set a new one" |
| 4 | `no_progress ≥ 120` | disengage + drop the stale `primary` objective + `ANTI` note, then reset every streak |

Rollups are **suppressed while stuck** (`stuck ≥ 3` or `no_progress ≥ 3`): they are generated from `recent`, so rolling up mid-loop distills the loop into durable "facts" that `wake()` feeds back forever.

## Config map

| File | Purpose |
|------|---------|
| `config/agents.yaml` | Provider (`dual` default), planner model, Jev endpoint |
| `config/run.yaml` | ROM, ports, cadence (`prompt_interval_s`), `vision_only`, OptMem |
| `config/rules_red.yaml` | Nuzlocke clauses / level caps (hashed into manifest) |

Swap the planner without code changes — edit `config/agents.yaml` (`planner.model`, e.g. `gpt-5.6-sol` with `reasoning: high`, or `gemini-3.6-flash` with `effort`). Set `provider: cursor` to go back to one vision call per cycle.

## Layout

```text
nuzlocke/
  agents/           # prompts + role helpers
  environment/      # Nous Red HTTP adapter (observe / execute / checkpoints)
                    #   screen.py — world/text frame-region digests
  knowledge/        # walkthrough excerpt loader
  llm/              # cursor planner, jev actor, openai_compatible
  memory/           # OptMem (in-repo durable-notes store)
  orchestration/    # RunLoop, ActionArbiter, stuck/fallback/ledger/checkpoint helpers
  referee/          # level caps, encounter/death ledgers, Gen-1 type chart
  state/            # pydantic contracts + event store
apps/orchestrator/  # CLI: nuzlocke smoke | run [--resume <run-id>]
.cursor/skills/     # pokemon-red-walkthrough
config/
runs/               # per-run artifacts (gitignored)
```

## Known pitfalls (read before debugging)

1. **RAM lies on Red Star** — map may say “Red’s House” while the screen shows Oak text or a naming keyboard. Confirmed directly: `dialog.active=false, joy_ignore=0` while the screenshot showed an active Oak dialogue box mid-print, and 5 consecutive walk actions in that state produced zero position/facing change. This is why RAM-based input-ready gating was removed entirely — see the Cadence section above.
2. **Up/down house thrash** — model mislabels interior as Pallet outdoors; OptMem + walkthrough exist to break that loop.
3. **Battles waste turns on "Enemy used X!" text** if the agent doesn't `skip_dialog` — there's no orchestrator-side auto-advance anymore (RAM can't be trusted to detect it), so the Battle role playbook explicitly tells the agent to use `skip_dialog` when it sees narration.
4. **Naming screen** — walks move the letter cursor; must finish **END**. joy_ignore bit 6 (`0x40`) is the **one** RAM bit that has held up on Red Star — it was correct for 58 straight observations in run `20260821-164159-3c5a68` while the agent thought it was in a bedroom and walked the cursor around, naming the player "A". It's now stated outright to the agent as `hard_signal`, even in vision-only. Bit 5 (dialog) stays out; see #1.
5. pokemon-agent’s `a_until_dialog_end` reads a flat `state["dialog_active"]` that never exists (the real key is `state["dialog"]["active"]`), so it always breaks after **one** A press. `execute()` serves it from our own `skip_dialog` instead.
6. pokemon-agent’s `/save` writes into a **session-scoped** folder whenever a dashboard "game session" is active (e.g. New Game/Load clicked in the dashboard), but `/load` always reads the **flat** `data_dir/saves/` dir — `NousRedEnvironment.save_checkpoint` verifies the name shows up in `/saves` and raises loudly if not, rather than silently producing an unloadable checkpoint. Close any active dashboard session for `checkpoint:` auto-saves to work.
7. **Never end a dialogue mash on A.** A while facing an NPC re-opens the box that was just closed, so any A-terminated macro standing in front of an NPC is a fixed point, not an escape. Run `20260821-164159-3c5a68` spent its last 33 minutes and ~200 vision calls in that 2-cycle in front of Prof Oak. All blind macros (`skip_dialog`, recovery fallback, LLM-error fallback) are B-only and B-terminated: B advances Gen 1 text identically and starts nothing in the overworld.
8. **A goal can outlive its completion.** Oak keeps talking after handing over the Pokédex; the agent read that as "the parcel has not gone through yet". In dual mode Jev's `objective_done` judgment sends that back to the planner before the next press. Tiers 3–4 above remain the backstop when that still doesn't move.

## Cost (order of magnitude)

`provider: cursor` is ~1800 vision prompts / hour at 2s cadence on `gemini-3.6-flash`: roughly **~$10–15/hr** at Google list rates if thinking stays off (Cursor usage pool; Teams may add $0.25/M). Sonnet is several× more. Screenshots dominate tokens (~1120/image). Dual mode spends the 0.5s cycle on a Jev text decision; the vision planner runs when the scene actually changes (a text box closing, a battle, a name list), on the 45s cap, and on scene changes, so screenshot calls stay rare while the screen class is stable. The durable agent's periodic compaction (see Vision section above) still matters on long planner sessions.

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
