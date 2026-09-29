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

### Headless sandbox

Try a fix on a real savestate without touching a live run:

```bash
# Scripted buttons, no LLM. Same savestate + same buttons = same frames.
uv run nuzlocke sandbox --from <run-id> --script "skip_dialog walk_down walk_right walk_up press_a wait_10*6"
# The real loop (planner + Jev) for N cycles, dashboard ignored
uv run nuzlocke sandbox --from <run-id> --steps 30
# Omit --from to boot the ROM fresh (the intro)
uv run nuzlocke sandbox --script "wait_600 press_start wait_90 press_a wait_120 press_a wait_120 wait_240 press_a wait_180 skip_dialog*10"
```

- Each call copies the source's `savestates/auto.state` (or `pokemon-agent-data/saves/auto.state`) into a new `runs/sandbox-<time>-<hex>/`, starts its own pokemon-agent on the first free port from 8791, and stops that server when it finishes. The source run's files and port are not touched
- Script tokens are any `GameAction` (they go through `execute`, with burst stops and `skip_dialog`) or a raw opcode (`press_X`, `walk_X`, `hold_X_N`, `wait_N`), comma- or space-separated; `token*N` repeats. Each row prints map, tile, facing, `box=text|prompt|-`, and world- and text-region digests (a changed `world=` with an unchanged tile is something else moving); frames go to `frames/NNN_<token>.png` and rows to `probe.jsonl`
- A script ends by saving its final state, so `--from sandbox-<id>` continues from the last row. Chain short scripts to reach a scene, then hand it to `--steps`
- Loop mode writes `summary.json` and `journal.jsonl`: cycles, planner looks, `looks_by_reason` (why each look happened), `planner_s` (median, p90, and total seconds per look), recoveries, median cycle time, distinct tiles, the last path, button counts, burst stops, Jev reasons, and a `jev` block (calls, confidence, unsure share, state size, latency). Every `plan` event carries `latency_s` and every `jev` event its `looks`, in live runs too. Loop mode makes real planner calls
- A script's final state is saved even mid-battle, so `--from` can start a loop at a battle; a loop's own savestate is not written mid-battle
- The planner's prompts and answers for a loop are kept by the Cursor SDK outside the repo, under `~/.cursor/projects/<repo-path-with-dashes>-runs-<run-id>-agent-workspace/agent-transcripts/`. Deleting `runs/sandbox-*` does not remove them

## Do / don’t

| Do | Don’t |
|----|--------|
| Look for `pokemon-agent` under `.venv/lib/python3.*/site-packages/pokemon_agent/` | Search `$HOME` or the whole disk for packages |
| Trust **screenshots** over RAM on Red Star | Blind-walk from map/coords alone, or gate behavior on `joy_ignore`/`dialog_active` |
| Remember the emulator is frozen between `/action` calls — give text time with wait frames inside the action | Add back RAM-based readiness polling — it was removed after `dialog_active` was confirmed false while a real dialog was on screen |
| Measure movement and dialog claims on the emulator with `nuzlocke sandbox` (a private copy of a run's savestate; see Headless sandbox) | Press B at a YES/NO — it answers NO (at the starter it turns the Pokémon down) |
| Keep changes scoped; update README/AGENTS when behavior changes | Restart a live run unless the user asks |
| Commit only when the user asks | Commit ROMs, `.env`, or `runs/*` artifacts |

## Runtime loop (truth)

Three systems. **System 1** (Jev + code) presses every button. **System 2** (the vision director, `planner` in `config/agents.yaml`) is called only when there is a decision to make: it sets the next objective after reading System 1's journal, and it writes a plan for each trainer battle. **System 3** (the Nuzlocke controller, `nuzlocke/agents/system3.py`, deterministic) runs first; see System 3 below.

### System 3: the Nuzlocke rules

**No items**, except Poké Balls for catching. Healing is Pokémon Centers or Mom only.

- **Catch**: the first wild encounter in each area, once the player has Poké Balls (`LedgerTracker.first_encounter`; earlier encounters do not count), gets ITEM → the Poké Ball row, without asking Jev. "Give a nickname?" is answered NO. First caught: a Weedle in Viridian Forest, 0 System 2 looks.
- **Run**: in a wild battle with the lead below 25% HP, RUN is pressed. A trainer battle cannot be fled.
- **Heal**: below 50% HP, poisoned, or with anyone fainted, the objective becomes the nearest Pokémon Center and its nurse (face the counter, A, YES), or Mom before the first Center. Poison takes 1 HP every 4 steps outside battle and can faint: run `20260929-095253-004c14` wiped walking poisoned at 3/24 HP.
- **Shop**: after the Pokédex, with no Poké Balls and ¥200 or more, a beat walks to the Viridian Mart and buys as many as the money allows (BUY → POKé BALL → the ×01 box set by code → YES), then backs out with B and QUIT. Nothing else is bought.
- **Wipe**: the whole party at 0 HP, or the blackout warp home with a healed party, ends the run (#29).
- **Briefing** (`constraints` for System 1 and System 2): the rules, the level cap, the next boss, and the known trainers on this map with their teams, from `nuzlocke/knowledge/trainers_red.yaml`. That file is vanilla Red through Misty: Red Star may differ, and the RAM enemy wins in battle.

System 2 plans each **trainer battle** once, at its first menu (trigger `trainer battle`). It gets the field, our moves with types and PP, the party, and the briefing, and returns `battle_plan`: moves in order, `switch_to`, and `switch_below` (the lead's HP fraction). System 1 tags those options ("System 2's plan: choice 1"). The plan is dropped when the battle ends.

```text
dashboard control
    → settle()    # run 20-frame waits (at most 300) until there is something to decide:
                  #   control, a text box, or a ▶ menu. A step, a cutscene, or a battle
                  #   animation is not a decision point; nothing (Jev or System 2) is asked mid-frame
    → observe()   # screenshot first (blank-LCD wait), then RAM: /state, walk grid, /map/objects
    → GridTrust / ObjectTrust withhold a map's grid or objects once real walks contradict them
    → referee.advance(badges) → ledger.update (encounter/death)
    → a wipe (the whole party fainted, or the blackout warp home) ends the run (#29)
    → System 3's heal objective when the lead is below half HP, else the beat script from the
      bedroom through Oak's Parcel, Viridian Forest, and Pewter to Brock, each beat with a
      machine target, chosen from the map id, the bag, and `has_pokedex`
    → stuck tiers 2/4: mechanical disengage (no LLM); tiers 1/3: Recovery vision call
    → System 1 (agents/system1.py), no vision call:
        ▶ menu in the decoded screen text → Jev picks a row, code moves the cursor + A
        open text box, no menu           → skip_dialog (B only)
        title / intro splash              → wait + START
        cutscene (D-pad ignored, or a script walks the player) → wait_60; text still pages
        overworld                         → Jev picks a goal (agents/goals.py), code walks it
                                            as one A* burst (≤8 walks)
        battle (agents/battle.py)         → Jev picks FIGHT / PKMN / ITEM / RUN, then the move,
                                            from options with HP, matchup, PP; code moves the cursor
        Pokédex page (HT/WT on screen)    → A
        naming keyboard, unreadable screens → the older fallback (jev_policy.choose_fast_action)
      or a trigger for System 2 (overworld triggers wait 8 cycles after a look; System 1
      explores meanwhile): no objective · objective not on this map · objective done
        (Jev noul) · Jev unsure twice · goal failed 3x · Jev unsure at a YES/NO · text did not page
    → System 2 (roles.propose_plan): grid screenshot + journal since its last look + trigger
        → ObjectiveCard: target {exit|edge|npc|cell}, done_when, and `steps` only for a
          screen System 1 cannot handle; System 1 retries at once with the new objective
    → ActionArbiter → /action (burst stops: text box, prompt, battle, map change, immobile walk)
    → room map + goal failures + one journal line (runs/<run-id>/journal.jsonl)
    → (periodic, and again on STOP) continue savestate
```

### Cadence (`config/run.yaml`)

- **The emulator is not real time.** pokemon-agent runs PyBoy headless and only advances frames inside `/action` (`press_*` and `walk_*` are 20 frames each, `wait_N` is N). Nothing happens between cycles, so waiting in Python does not let text print or a scene settle — send wait frames in the action instead
- `prompt_interval_s: 0.1` — minimum wall time per cycle (`NUZLOCKE_PROMPT_INTERVAL_S`). It only paces the run for a human watching
- `press_interval_s: 0.1` — tiny gap between buttons in a burst
- `max_actions_per_proposal: 12` — logical actions; `walk_*_2`…`_5` macros count as one
- **One `walk_*` press is one tile**, from any facing. A press into a wall only turns the player. Gen 1 has no turn-in-place, and the old second press after a turn moved two tiles (57 of 63 turning walks in run `20260927-235608-cc25eb`)
- **Paging text**: an open text box with no prompt is `skip_dialog`, checked before any planner look — a new box does not get a look first. Battle narration ("Enemy SQUIRTLE used TACKLE!") is paged the same way; the FIGHT menu and the move list do not read as a text box, so the mash stops at them. The planner is not called between lines. After four pages on one tile (B presses or `skip_dialog` mashes) the director stops calling it speech, so the beat stays the goal; only single B presses force a look every fourth page, since a mash already runs until the box closes or stalls. A YES/NO is not paged this way, and neither is a text box that belongs to a menu the plan opened (the party list draws one; B would leave it). A text box is the white panel in the double black frame (`screen.text_box_open`). A fade to black fills the same rows and is not speech
- **Scripted scenes**: a walk that neither moves nor turns the player, while the world region keeps changing, is a scene holding the input (the rival walking to his ball, then to the exit). `execute` sends `wait_30` rounds, up to 10, until the world region is still for two rounds, then presses that walk once more. A text box, a battle, or a map change during the wait ends the burst there. A still picture after the first round is a wall: it costs 30 frames and no second press. Each planner look during those scenes used to buy 20 frames
- **Menus and prompts**: any ▶ menu in the decoded screen text (NEW GAME, the NAME lists, YES/NO, START) goes to Jev as one option per row, and code moves the highlight and presses A. A row the goal names is tagged "the goal names this row". Name lists offer no B. An unsure answer at a YES/NO goes to System 2, because B there answers NO. Paging stops at a prompt by itself; the *next* B answers it
- Action **`skip_dialog`**: agent-requested mash through narrative text, **B only**. Each round is `hold_b_30` then `wait_30` released, so every round is a new press (pitfall #13). It stops when the box closes, when the whole frame stops changing for two rounds (max 6 rounds; the blinking ▼ is masked out), when a prompt appears, or when naming locks. The world region counts: in battle a line sits unchanged while the move and the HP bar animate above it, and B does nothing until they finish. No walks after it in the same burst, and no walk is pressed while a box is open — the D-pad does nothing until it closes. If a `skip_dialog` left an open box unchanged, the next cycle takes a planner look and presses its button. It does not page the Pokédex page before the starter's YES/NO (bit 6 is set there, pitfall #4); A turns that page. `a_until_dialog_end` is served by the same macro (pitfall #5)
- **Holds and A**: `execute` sends `wait_12` released after every `hold_*`, and `wait_30` after a burst's last `press_a`, so the look after it sees the box A opened (pitfall #14). A walk that only turns the player stops the path, unless it turned toward that walk's direction and the next step is `press_a`: then that A goes out, since it is what the turn was for (`walk_up` into the table, then A on the ball)
- Multi-tile walks: `walk_up_3` etc. expand client-side before `/action`

### Vision

- Screenshots: native **160×144** PNG from `GET /screenshot` for every pixel check (digests, text box, prompt box)
- Vision calls (planner, Recovery, cursor-mode roles) instead attach pokemon-agent's `GET /screenshot/grid?scale=4`: the same frame at **640×576** with labelled A1..J9 walk cells and the player boxed at E5. It is fetched only for a vision call (`NousRedEnvironment.vision_frame`) and falls back to the native frame on an older server. The prompts tell the model each cell is one walk tile; the `map.grid` ASCII uses the same cells
- Attached via Cursor `SDKImage.from_file` with the file's real pixel size as `dimension` metadata
- **No Gemini `media_resolution`** (low/medium/high) on this SDK path — vision-only does not change image token billing by itself
- `vision_only` default **true**: no RAM JSON goes to the vision director, and nothing gates input on `joy_ignore`/`dialog_active` (pitfall #1). System 1 is text-only and does read RAM that describes what is drawn or placed: the tilemap text (`wTileMap`, trusted only inside a ┌─┐ frame, and speech only when the pixel check sees a text box), the warp/sign/sprite tables, map size, and edge connections (`GET /map/objects`, pitfall #18), and the cutscene flags (`wJoyIgnore`, `wStatusFlags5` bit 7; pitfall #22). The referee reads badges, party, and battle
- Cursor provider keeps one durable agent (the planner, in dual mode); when context hits ``compact_at_tokens`` (default 250k) it asks for a short session summary, then recreates with that summary carried forward
- Dual mode (`config/agents.yaml`) is System 1 + System 2 (see Runtime loop and System 1 below). System 2's `steps` are pressed only when it wrote them for a screen System 1 could not handle (the naming keyboard, a stuck menu): they are pressed before System 1 runs again, as a burst in the overworld and one button per cycle in menus and naming. In battle the older path still applies: the planner looks when its card is spent and Jev picks buttons from a fixed menu
- Walk grid trust: `map.grid` (pokemon-agent's tilemap read, vanilla pokered collision tables) is shown to the planner and Jev and drives heading/sidestep choices, but it is not "the authority". On Red Star's Oak's Lab it drew all four neighbors as `#` while the player walked freely. `GridTrust` counts each walk in a burst that lands on a tile the grid called `#` on the same map; after two, that map's grid is withheld from prompts and the step picker for the rest of the run. Door mats read `#` too, but walking down from one changes the map, so that never counts — and named steps are still pressed into `#`, or nobody could leave a house

### System 1: goals, menus, and the journal

Built the way the Jev harnesses that finished Red built theirs ([christianmat/jev-pokemon](https://github.com/christianmat/jev-pokemon), [milanboers/jev-plays-pokemon](https://github.com/milanboers/jev-plays-pokemon)): Jev chooses between legal options, each carrying the facts that decide it, and code does the pathing.

- **Goals** (`nuzlocke/agents/goals.py`), rebuilt every overworld cycle: `exit_N` (each warp, labelled with the destination from `MAP_NAMES`), `edge_<dir>` (each side that joins another map), `talk_N` (on-screen NPCs, balls, signs; the path ends facing them with A), `explore` (nearest unvisited tile), `heading_<dir>` (the beat's story direction), and `wait`. Each option says its path length or "no known path", whether it is the CURRENT OBJECTIVE, whether it goes back the way the player came, and how often it was picked on this map with no progress.
- **Keys stay put** while the player moves: `exit_<dest map>`, `talk_<sprite slot>`, `sign_<x>_<y>`, `edge_<dir>`, so failure counts and Jev's history follow the same door or person.
- **Off-screen targets**: with no full path, a goal walks the reachable route that gets closest to its target as one burst ("walks 7 steps closer"); only when nothing reachable is closer does it try one blind step, and an objective with neither asks System 2. From run `20260929-022135-035cb9`'s old-man savestate this took Viridian → Mart → parcel → Route 1 in 40 cycles and 3 System 2 looks, where the first try took 12 looks.
- **Map memory**: `RoomMap` keeps the walk grid of every screen seen on each map, so paths run across the whole known map. A target with no known path heads for the known map's frontier (a reachable tile next to one never seen) nearest the target. Screen-only paths walked Viridian Forest's maze into the same dead-end pocket for hours; with the memory, from the same savestate it crossed the forest in about 70 cycles and 1 System 2 look.
- **Paths**: one BFS per cycle (`goals.Routes`) over the remembered map and the trusted walk grid, plus every tile the player has stood on (`RoomMap`), minus tiles a walk bumped into (for 40 cycles, so a wandering NPC is not a permanent wall), NPC tiles, and every warp that is not the goal (a door on the way is a map change). On a map whose grid is withheld (Oak's Lab) unknown on-screen tiles are tried and each bump is remembered. A warp is walked onto, then one more step toward the map edge it sits on, since a door mat only warps when walked off.
- **Objective**: the beat's `target` (`{"kind": "warp", "dest_map": 37}`, `{"kind": "edge", "dir": "up"}`, `{"kind": "npc", "picture": 74}`, `{"kind": "wait"}`), else System 2's card. A beat is done by its map check, not by Jev's word; a System 2 objective is done by `done_when` or Jev's `objective_done` noul.
- **A goal that went nowhere**: no move, or the same text as the last time it was tried (the old man's "You can't go through here!" each time `edge_up` walked into him, 20 times in run `20260929-022135-035cb9`). Its option then says "picked 2x on this map with no progress" and "last time it ended in the text '…'", Jev's runner-up replaces it after two, and System 2 is asked after three, with the text in the journal. System 2's prompt says a road that answers with the same text each time is closed until a story event.
- **Battle** (`nuzlocke/agents/battle.py`): the FIGHT / PKMN / ITEM / RUN grid and the move list are read from their rows (their boxes overlap the text box, so the frame parser cannot). The menu options carry both POKéMON's HP; RUN is offered only in a wild battle; PKMN and ITEM list what is there. Move options carry the type (remembered from the TYPE/ box each time a move is highlighted), effectiveness against the enemy from the type chart, and PP left. An unsure answer is FIGHT and the first move with PP. A battle text box is always paged with B, even when the last page left it unchanged (an animation still running). Run `20260929-022135-035cb9`'s rival battle took a planner look per turn; from the same savestate, Jev fought it with no look.
- **Gate**: Jev's pick is pressed when TypeSafe's confidence clears `confidence_floor` or the top option leads the runner-up by 0.25 (`jev_policy.MIN_MARGIN`). Confidence is the spread over every option, so a clear 0.66 / 0.29 pick on a three-row menu scores only 0.48. An unsure overworld answer takes the objective goal once, then asks System 2. A goal that failed twice on this map yields to Jev's runner-up; three times asks System 2.
- **Journal** (`runs/<run-id>/journal.jsonl`, `orchestration/journal.py`): one line per cycle, for example `c24 Red's House 2F (3,6): exit_0 p=0.87 (door or stairs to Red's House 1F) | pressed walk_down, walk_right x2, walk_up x5 | moved 8 tiles`. System 2 gets the lines since its last look instead of `recent`.
- **Every Jev call** is also a `jev_call` event (scene, options with their facts, state size, full distribution, confidence, nouls, accepted, latency). The sandbox `summary.json` has a `jev` block.

Measured on fresh boots (`nuzlocke sandbox --steps 60`): boot → NEW GAME → RED / BLUE → bedroom stairs → front door → Pallet Town in 28 cycles with **no** System 2 look, where run `20260929-010148-e32792` spent 32 looks and 670 of 701 s in the planner. From that run's Route 1 savestate, Route 1 → Viridian City took 14 cycles and 4 looks (two "no objective" after the beat script ends, two from the battle fallback).

### Memory (OptMem)

- In-repo module: `nuzlocke/memory/optmem.py` — a capped, append-only `notes.log` per run (no external CLI)
- Per run: `runs/<run-id>/memory/notes.log`
- Orchestrator: `wake` before prompt (last `wake_lines` notes), `note` after step
- Short-term: orchestrator injects `recent` (last ~8 actions + outcomes) into each prompt
- Long-term OptMem: landmarks / rollups only (not every step). `rollup_every: 25`
- Early-game primary/secondary/tertiary come from the beat script (`nuzlocke/knowledge/beats.py`), not from the planner. Planner objective text is ignored while a beat applies. After Route 1 the seeded milestones in `config/run.yaml` take over
- Agent landmarks still go to OptMem when memory is on. Objective text from the agent is kept only once the beat script is finished
- OptMem is off by default. Enable with `memory.enabled: true` or `NUZLOCKE_MEMORY=1`

### Walkthrough skill

- Project skill: `.cursor/skills/pokemon-red-walkthrough/` (`SKILL.md` + `reference.md`)
- Copied into `runs/<run-id>/agent_workspace/skills/pokemon-red-walkthrough/`
- The current beat's short hint is attached to every overworld planner call. On stuck (`needs_recovery`: noop/stuck/loop/no_progress at the tier-1 thresholds) a longer `walkthrough_hint` excerpt is appended
- When a hint is injected, Cursor agents must **not** `Read` skill files (excerpt is enough)
- Director stays deterministic on any stuck path → Recovery (one vision LLM call, never Director+Recovery). Recovery must not repeat `failed_approaches`; discount stuck only after a non-noop recovery.

## Progress detection & the escalation ladder

Three signals, because they catch different failures:

| signal | means | blind to |
|---|---|---|
| `noop_streak` | whole frame byte-identical | dialogue loops — animating text changes the PNG every cycle |
| `no_progress_streak` | **world region** (frame rows 0–95, above the Gen 1 text box) identical | water and NPC animation — the picture changes while the tile does not |
| `immobile_streak` | a **walk** left `(map, x, y)` and facing unchanged | dialog, battle, and the naming grid (those walks are not counted), and a first press into a wall that turns the player |

`nuzlocke/environment/screen.py` splits every frame at `DIALOG_TOP = 96`. Degrades to whole-file hashing without Pillow/NumPy. An immobile walk is labeled `immobile` in `recent`, and that direction is blocked on the current tile only. Leaving the tile clears the set, and so does an open text box or a fourth blocked side: a scripted scene holds the player still, and the player reached this tile, so one side is open (pitfall #15). Jev's menu hides those directions until the tile changes; a failure on an earlier tile does not remove the button for the rest of the run.

Tiers (`StuckTracker.escalation_tier`), in prompt cycles — roughly 1 / 2 / 3 / 6 minutes at the ~9s/cycle a real run achieves:

| tier | trigger | response |
|---|---|---|
| 1 | `no_progress ≥ 24`, or a long noop/stuck/loop | LLM Recovery only when Jev is not the actor. With Jev, a few wrong joystick presses stay on the stick. An immobile walk still forces a planner refresh on the next cycle |
| 2 | `no_progress ≥ 48`, or 40 cycles on one tile while the world region is also frozen, or `stuck_score ≥ 24`, or `immobile ≥ 12` | **deterministic disengage — no LLM**: `press_b` + walk off the tile, rotating direction, skipping any direction blocked on this tile. A menu or cutscene keeps the same RAM tile while the picture changes; that does not count as immobile and does not skip Jev |
| 3 | `no_progress ≥ 72` | Recovery with `reframe`: "assume your objective is already complete, set a new one" |
| 4 | `no_progress ≥ 120` | disengage + drop the stale `primary` objective + `ANTI` note, then reset every streak. A code-owned beat is not dropped |

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
  knowledge/        # walkthrough excerpts + early-game beat script
  llm/              # cursor planner, jev actor, openai_compatible
  memory/           # OptMem (in-repo durable-notes store)
  orchestration/    # RunLoop, ActionArbiter, stuck/fallback/ledger/checkpoint helpers
  referee/          # level caps, encounter/death ledgers, Gen-1 type chart
  state/            # pydantic contracts + event store
apps/orchestrator/  # CLI: nuzlocke smoke | run [--resume <run-id>] | sandbox
.cursor/skills/     # pokemon-red-walkthrough
config/
runs/               # per-run artifacts (gitignored)
```

## Known pitfalls (read before debugging)

1. **RAM lies on Red Star** — map may say “Red’s House” while the screen shows Oak text or a naming keyboard. Confirmed directly: `dialog.active=false, joy_ignore=0` while the screenshot showed an active Oak dialogue box mid-print, and 5 consecutive walk actions in that state produced zero position/facing change. This is why RAM-based input-ready gating was removed entirely — see the Cadence section above. Part of this is pokemon-agent reading the wrong flag rather than the ROM lying: its `dialog.active` is bit 5 of `0xD730` ("ignore joypad input"), which ordinary Gen 1 text does not set (see #4).
2. **Up/down house thrash** — model mislabels interior as Pallet outdoors; OptMem + walkthrough exist to break that loop.
3. **Battles waste turns on "Enemy used X!" text** if the agent doesn't `skip_dialog` — there's no orchestrator-side auto-advance anymore (RAM can't be trusted to detect it), so the Battle role playbook explicitly tells the agent to use `skip_dialog` when it sees narration.
4. **Naming screen** — walks move the letter cursor; `press_start` finishes the name (it worked at once in run `20260927-235608-cc25eb` after 3 minutes of one-look-per-cursor-move). The `joy_ignore` pokemon-agent reports is really `0xD730` (`wStatusFlags5` in pokered), not `wJoyIgnore`: bit 6 (`0x40`) means "print text with no letter delay" and bit 5 means "ignore joypad input". Bit 6 is set on the letter grid — correct for 58 straight observations in run `20260821-164159-3c5a68` — **and on the Pokédex page shown before the starter's YES/NO**, where START does nothing and A turns the page. `is_naming_lock` still keys off it, so that page is classified as naming; the `hard_signal` text now names both screens. Bit 5 (dialog) stays out; see #1.
5. pokemon-agent’s `a_until_dialog_end` reads a flat `state["dialog_active"]` that never exists (the real key is `state["dialog"]["active"]`), so it always breaks after **one** A press. `execute()` serves it from our own `skip_dialog` instead.
6. pokemon-agent’s `/save` writes into a **session-scoped** folder whenever a dashboard "game session" is active (e.g. New Game/Load clicked in the dashboard), but `/load` always reads the **flat** `data_dir/saves/` dir — `NousRedEnvironment.save_checkpoint` verifies the name shows up in `/saves` and raises loudly if not, rather than silently producing an unloadable checkpoint. Close any active dashboard session for `checkpoint:` auto-saves to work.
7. **Never mash dialog with A.** A while facing an NPC re-opens the box that was just closed, so an A after the box has closed, standing in front of an NPC, is a fixed point. Run `20260821-164159-3c5a68` spent its last 33 minutes and ~200 vision calls in that 2-cycle in front of Prof Oak. Run `20260928-205856-f65040` hit it again through an A fallback for boxes that "ignored B" (they did not; see #13). `skip_dialog`, Recovery, and the LLM-error fallback are all B-only.
8. **A goal can outlive its completion.** Oak keeps talking after handing over the Pokédex; the agent read that as "the parcel has not gone through yet". In dual mode Jev's `objective_done` judgment sends that back to the planner before the next press. Tiers 3–4 above remain the backstop when that still doesn't move.
9. **Walks moved two tiles after a turn** (fixed). Commit `2d90ff0` sent a second press whenever facing changed, on the belief that Gen 1 turns in place. It does not: 57 of 63 turning walks in run `20260927-235608-cc25eb` moved two tiles, so "walk_right one tile to stand south of a starter ball" went (5,5)→(7,5) and "walk_left one tile" went back, for the rest of the run. On the emulator from that savestate, (5,3,up) → `walk_down` → (5,4) → `walk_right` → (6,4) → `walk_up` faces the ball → `press_a` opens its Pokédex page.
10. **B at a YES/NO says NO.** Paging text with B is safe up to the prompt — a press or a held B stops there — but the next B turns down the starter. Prompts are detected from pixels and always get a planner look (see Cadence).
11. **The walk grid can be wrong.** Oak's Lab drew every neighbor as `#` while the player walked; the prompt used to call it "the authority for the next tile". See walk grid trust under Vision.
12. **The vision planner could not tell where the player stood on a 160×144 frame.** At (1,2) in the lab's top-left corner it reported "facing the middle Poké Ball" and pressed A into a sign, then paged it 86 times. Vision calls now get the 4× labelled grid frame.
13. **Two holds in a row are one press.** pokemon-agent's `hold_X_N` presses, runs N frames, and releases with no frames after, and nothing runs between `/action` calls. So `hold_b_120, hold_b_120` reaches the game as one unbroken B, and Gen 1 text only advances on a new press. From Oak's Lab ("which POKéMON do you want?"), four `hold_b_120` never closed the box, and the walk after them was swallowed. Three `press_b` closed it, and so did two `hold_b_30 + wait_30` rounds. This is why the box looked like it ignored B.
14. **A box that A opens is drawn late.** `press_a` is 8 frames held and 12 released. Oak's box and a starter's Pokédex page appear up to 10 frames after that, so a screenshot taken right after A shows nothing new. The planner read that as "A did nothing" and walked away from the ball. `execute` adds `wait_30` after a burst's last `press_a`.
15. **A scripted scene blocks every direction.** While the rival walks to his ball, and again for his "Wait, RED!" walk to the exit, the player's walks do not move. Each one was recorded as a wall on that tile. In a sandbox loop from run `20260928-205856-f65040`'s Oak's Lab savestate, all four sides of (6,4) were blocked, every walk the planner named was refused, and Jev pressed B for the last 10 of 30 cycles. Blocked directions are now tried again after a text box and when a fourth side would be blocked, and a walk held by a scene is waited out before it counts (Cadence → Scripted scenes).
16. **Planned battle steps were proposed as the overworld agent.** The director gives a battle to the battle agent and the arbiter rejects anyone else's buttons, so every planned A in the rival battle was rejected: 10 looks, no presses. `choose_fast_action` now proposes as the battle agent whenever RAM says a battle is on.
2a. The thrash came back with System 1 (fixed): the path north from Red's front door ran over the door tile, so every burst walked back inside. Warps that are not the goal are now impassable in `goals.collision_map`.
17. **B cancels an evolution.** Gen 1 stops an evolution when B is pressed during it, and `skip_dialog` pages every narrative box with B, including "What? CHARMANDER is evolving!". Not handled yet. Caterpie and Weedle evolve at level 7, so this matters by Viridian Forest.
18. **Doors read as walls, and the warp table is RAM.** pokemon-agent's walk grid shows door mats and stairs as `#`, so nothing on it says where the exits are. `nuzlocke/environment/pa_serve.py` runs pokemon-agent's own server with one more route, `GET /map/objects`, which returns pokered's `wWarpEntries`, `wSignCoords`, and sprite slots (`wSpriteStateData1/2`). The adapter starts the server as `python -m nuzlocke.environment.pa_serve serve …`. On Red Star, Oak's Lab read exactly as in pokered: the door warps at (4,11)/(5,11), the three balls at x 6–8 y 3, Oak at (5,2). Pallet Town read the pokered warps (5,5), (13,5), (12,11), its sign, Oak, the girl, and the fisherman; map size 20×18 and connections north/south matched too. `ObjectTrust` withholds a map's objects for the rest of the run after two map changes that did not start on or next to a listed warp. An older server without the route leaves the lists empty.

19. **RAM read before the screen settled.** `observe()` read `/state` and the objects first, then took the screenshot, and after a door fade it added `wait_60` for a blank LCD. The first observation on a new map then carried the old map's warp table and x/y (Pallet read Red's House 1F's (2,7)/(3,7)/(7,1)). RAM is now read after the screenshot and its wait, and a warp table identical to the previous map's right after a map change is dropped for that cycle.
20. **The names before the naming lists are NINTEN and SONY**, not blank. `beats.is_intro_boot` counts those as unnamed; otherwise the rival list got the bedroom goal and Jev answered it with B.
22. **Cutscenes have a real RAM signal, unlike dialog.** Traced every 20 frames through Oak's escort on Red Star: `wJoyIgnore` (0xCD6B) is 0x00 while the player is free, 0xFC while Oak talks (only A/B accepted), 0xFF or 0xFC while he walks the player to the lab, and 0x00 again when control returns; `wStatusFlags5` (0xD730) bit 7 is set exactly while a script walks the player, with `wSimulatedJoypadStatesIndex` (0xCD38) counting 16 → 0. `/map/objects` returns them as `input`, and `PlayerObservation.cutscene` is "D-pad ignored (0xF0 of wJoyIgnore) or bit 7". System 1 then waits (`wait_60`) instead of choosing goals whose walks the game ignores; a text box still pages with B. This is not the bit-5 `dialog_active` of pitfall #1, which pokemon-agent reads from the wrong byte. Before this, the escort counted as goal failures and pulled System 2 looks, and the scripted movement was logged as System 1's own progress.
23. **A starter ball faced from the side ignores A.** From (5,3) facing right at the ball on (6,3), A did nothing for three cycles. Balls (sprite picture 74) are approached from below, like signs.
24. **The old man blocks Viridian's north road until Oak's Parcel is delivered.** System 2 set "north edge to Route 2" and System 1 walked into him 20 times: each try moved a tile and opened text, which counted as progress. The beat script now runs the errand (Viridian Mart → back to Oak → Pokédex → Route 2), keyed on the parcel in the bag and pokemon-agent's `has_pokedex` flag, and a goal that ends in the same text twice counts as failed.
25. **Deciding mid-frame wasted calls.** A look or a Jev call taken during a step, a cutscene, or a battle animation read a frame that was about to change; the old battle path spent one press per animation ("press_a | no progress"). `NousRedEnvironment.settle()` runs before every observation. `wWalkCounter` (0xCFC5) counts 7 → 5 → 1 during a step and is 0 after a full `walk_*`; with the cutscene flags (#22) and `wIsInBattle` (0xD057, battle with no text and no menu = an animation) it says when nothing can be decided yet.
26. **pokemon-agent's `battle.enemy` is not the POKéMON on the field.** It reads the enemy party, which in wild battles still held the rival's fainted Squirtle: Jev saw "vs Squirtle lv5 0/20 HP" at both fatal turns of run `20260929-030330-de1d51` and chose FIGHT at 3/23 and 1/29 HP. `/map/objects` returns `enemy` from pokered's `wEnemyMon` (0xCFE5 species, +1 HP, 0xCFF3 level, 0xCFF4 max HP), checked in a forest battle (Weedle lv4 17/17 while pokemon-agent still said Squirtle).
27. **pokemon-agent's type ids are off by one from Bug on.** Its `TYPE_NAMES` has Bug at 6 and Ghost at 7; pokered has the unused bird type at 6, Bug at 7, Ghost at 8 (Weedle read "Ghost/Poison"). Types now come from the species through `referee/type_chart.py`.
28. **pokemon-agent's map names are shifted from id 50.** Its table leaves out Viridian Forest South Gate, so the gate read "Viridian Forest", the forest "Pewter Museum 1F", and Pewter Gym "Pewter House". System 2 read those names ("re-enter Pewter Museum", and half an hour of "walk off the mat into Pallet Town" inside the gate). `nuzlocke/environment/maps.py` has pokered's names for 46–73, confirmed by map sizes and warps.
29. **Faints and blackouts were invisible to the referee.** It counted a death when a status read `FNT`, which pokemon-agent never reports (a fainted POKéMON is "OK" at 0 HP), and Gen 1 heals the party and warps home on a wipe, so the fainted party is never observed. Run `20260929-030330-de1d51` blacked out at minute 21 and at hour 4 and went on for six hours. A faint is now HP 0, and a wipe is either the whole party at 0 or a battle at ≤20% HP followed by a healed party on another map; the run then stops (`nuzlocke_wipe` event).
30. **System 2 was asked 1,393 times in that run, 5.5 of 6.1 hours.** 1,200 of the looks were "objective not on this map" or "objective path blocked", one after another, after the beat script ended at Viridian. Overworld triggers now wait 8 cycles after a look (System 1 explores meanwhile), a cell target is dropped once the player leaves the map it was read on, and the beat script now runs to Brock.
31. **The battle bag sets the naming keyboard's flag.** 0xD730 bit 6 ("instant text", pitfall #4) is also set on the bag list in battle, so System 1 stepped aside there and the fallback backed out of the bag with B. The keyboard is now recognised by its letter grid on screen.
32. **System 2's steps went ahead of System 1.** Steps left by an earlier look were pressed before System 1 ran, and when they ran out the old path looked again ("plan spent"), for example in the battle bag and the Mart. System 1 now runs first; System 2's steps are pressed only when System 1 cannot act or is about to ask for another look, and a cycle that already looked waits instead of looking twice.
33. **The Mart's lists.** The BUY/SELL/QUIT box stays drawn with a hollow `▷` under the item list's `▶`, and each price (`¥200`) or bag count (`× 3`) sits on its own line under its item. The active menu is the box whose `▶` starts a row, and price or count lines fold into the row above. The ×01 quantity box is not a ▶ menu, so it is also cursor mode for `execute`.
21. **Nuzlocke encounter rules**: handled by System 3 (catch, nickname NO); the duplicates and species clauses in `rules_red.yaml` are not enforced yet. In the Route 1 sandbox the battle fallback chose RUN on the first wild encounter. Catching is System 3's job, which is still a hook.

## Cost (order of magnitude)

`provider: cursor` is ~1800 vision prompts / hour at 2s cadence on `gemini-3.6-flash`: roughly **~$10–15/hr** at Google list rates if thinking stays off (Cursor usage pool; Teams may add $0.25/M). Sonnet is several× more. Screenshots dominate tokens (~1120/image at native size; the 4× grid frame may cost more, depending on how the model budgets images). Dual mode's time is dominated by the vision planner: in run `20260927-235608-cc25eb`, 85% of active time (30 of 36 minutes) was spent waiting on planner/Recovery calls (median 6s, p90 14s), while Jev answered in ~0.2s. That run looked roughly once per button. A planned path is now one burst per look, and narrative text is mashed without a look between lines. The durable agent's periodic compaction (see Vision section above) still matters on long planner sessions.

Pace is set by the number of looks, not by the buttons. Two headless sandbox loops from Oak's Lab (planner `grok-4.7`, reasoning low) took a planner look on 48 of 50 cycles. The planner took nearly all of the ~10 minutes: a median of 10–11 s per look, anywhere from 4 s to 35 s, and no slower late in the session than early. Pressing buttons took about 4 s in total. Each prompt is 6–7.5k characters, mostly the same instructions every time, plus a 640×576 frame. The looks that bought nothing were one per new text box (before `skip_dialog`), one per walk during a scripted scene (20 frames each), one after a walk that turned to face a ball, and four per battle turn on narration. Those are gone (Cadence → Paging text, Scripted scenes, Holds and A). Measured again on the same savestates:

| stretch | before | after |
|---|---|---|
| Nickname prompt → rival battle starts | 20 cycles, 19 looks, not reached | 8 cycles, 5 looks |
| Rival battle, 25 cycles (after the pitfall #16 fix) | 25 looks, 92 s, not finished | 14 looks, 57 s, won |
| Oak's box → starter chosen, nickname declined | 12 cycles, 12 looks | 12 cycles, 9 looks; ball faced and A pressed in one burst |

A battle turn is now two looks (FIGHT, then the move). Planner latency stays noisy on `grok-4.7`: the first look of a fresh agent takes 12–42 s, and later ones mostly 2–10 s with occasional 30–100 s calls. The sandbox summary reports it as `planner_s` and the cause of each look as `looks_by_reason`.

## Tests / handoff checklist

```bash
uv run pytest -q          # expect unit tests green
uvx ruff format <files>   # 100 columns, no magic trailing comma (pyproject.toml)
uv run nuzlocke --help
# Live review:
uv run nuzlocke run --rom ./red-star-2020-08-18.gb
# STOP on dashboard when done
# Optional: --with-ram to include RAM JSON in prompts
```

Still stubbed vs `AGENT_READY_PLAN.md`: Encounter / Box / Team / Smogon calc / full referee / FireRed.
