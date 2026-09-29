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
- Loop mode writes `summary.json`: cycles, planner looks, `looks_by_reason` (why each look happened), `planner_s` (median, p90, and total seconds per look), recoveries, median cycle time, distinct tiles, the last path, button counts, burst stops, and Jev reasons. Every `plan` event carries `latency_s` and every `jev` event its `looks`, in live runs too. Loop mode makes real planner calls
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

```text
dashboard control
    → observe()   # native screenshot + RAM; the emulator is frozen until the next /action
    → walk grid withheld on maps where real walks contradicted it (GridTrust)
    → referee.advance(badges) → ledger.update (encounter/death)
    → OptMem wake
    → beat script owns the early-game objective (bedroom → Route 1)
    → that beat's hint on every planner call; longer walkthrough excerpt if stuck
    → Director (deterministic; uses the beat instead of "toward Pewter")
    → dual: Planner looks at the grid screenshot only when the plan is stale and
      returns `steps` (≤6 buttons); the whole path is pressed in one burst
      a new YES/NO or name list forces a look before anything is pressed
      open text box without a prompt (battle narration too): skip_dialog, B taps
        only, before any look; the look waits until the box closes
      a skip_dialog that left the box unchanged: one look, and its button
      Jev picks only when the plan names no step and no single button
        (its options carry the facts: grid tile, first A* step toward each target,
        presses already spent on this tile; see Jev input)
      cursor: Overworld | Battle vision call
      a walk that neither moves nor turns while the picture moves: wait frames
        until it is still (a scripted scene), then that walk once more
      a walk that turns to face the next step's press_a: the press_a goes out
      an immobile walk (tile and facing unchanged) forces the next planner look
      stuck tier 1/3: Recovery vision call (becomes the next Jev plan in dual mode)
      stuck tier 2/4: mechanical disengage, plan dropped, skipping directions blocked on this tile
    → announce actions → ActionArbiter → /action
    → OptMem note
    → (periodic, and again on STOP) continue savestate
    → sleep to prompt_interval_s
```

### Cadence (`config/run.yaml`)

- **The emulator is not real time.** pokemon-agent runs PyBoy headless and only advances frames inside `/action` (`press_*` and `walk_*` are 20 frames each, `wait_N` is N). Nothing happens between cycles, so waiting in Python does not let text print or a scene settle — send wait frames in the action instead
- `prompt_interval_s: 0.1` — minimum wall time per cycle (`NUZLOCKE_PROMPT_INTERVAL_S`). It only paces the run for a human watching
- `press_interval_s: 0.1` — tiny gap between buttons in a burst
- `max_actions_per_proposal: 12` — logical actions; `walk_*_2`…`_5` macros count as one
- **One `walk_*` press is one tile**, from any facing. A press into a wall only turns the player. Gen 1 has no turn-in-place, and the old second press after a turn moved two tiles (57 of 63 turning walks in run `20260927-235608-cc25eb`)
- **Paging text**: an open text box with no prompt is `skip_dialog`, checked before any planner look — a new box does not get a look first. Battle narration ("Enemy SQUIRTLE used TACKLE!") is paged the same way; the FIGHT menu and the move list do not read as a text box, so the mash stops at them. The planner is not called between lines. After four pages on one tile (B presses or `skip_dialog` mashes) the director stops calling it speech, so the beat stays the goal; only single B presses force a look every fourth page, since a mash already runs until the box closes or stalls. A YES/NO is not paged this way, and neither is a text box that belongs to a menu the plan opened (the party list draws one; B would leave it). A text box is the white panel in the double black frame (`screen.text_box_open`). A fade to black fills the same rows and is not speech
- **Scripted scenes**: a walk that neither moves nor turns the player, while the world region keeps changing, is a scene holding the input (the rival walking to his ball, then to the exit). `execute` sends `wait_30` rounds, up to 10, until the world region is still for two rounds, then presses that walk once more. A text box, a battle, or a map change during the wait ends the burst there. A still picture after the first round is a wall: it costs 30 frames and no second press. Each planner look during those scenes used to buy 20 frames
- **Prompts**: a menu box above an open text box (YES/NO, the NEW NAME / RED / ASH / JACK list) is detected from pixels (`screen.prompt_box_open`: the double-line border Gen 1 draws on every menu box). It forces a planner look and switches the scene to the menu, whose unsure fallback is A. Paging stops at a prompt by itself; the *next* B answers it
- Action **`skip_dialog`**: agent-requested mash through narrative text, **B only**. Each round is `hold_b_30` then `wait_30` released, so every round is a new press (pitfall #13). It stops when the box closes, when the whole frame stops changing for two rounds (max 6 rounds; the blinking ▼ is masked out), when a prompt appears, or when naming locks. The world region counts: in battle a line sits unchanged while the move and the HP bar animate above it, and B does nothing until they finish. No walks after it in the same burst, and no walk is pressed while a box is open — the D-pad does nothing until it closes. If a `skip_dialog` left an open box unchanged, the next cycle takes a planner look and presses its button. It does not page the Pokédex page before the starter's YES/NO (bit 6 is set there, pitfall #4); A turns that page. `a_until_dialog_end` is served by the same macro (pitfall #5)
- **Holds and A**: `execute` sends `wait_12` released after every `hold_*`, and `wait_30` after a burst's last `press_a`, so the look after it sees the box A opened (pitfall #14). A walk that only turns the player stops the path, unless it turned toward that walk's direction and the next step is `press_a`: then that A goes out, since it is what the turn was for (`walk_up` into the table, then A on the ball)
- Multi-tile walks: `walk_up_3` etc. expand client-side before `/action`

### Vision

- Screenshots: native **160×144** PNG from `GET /screenshot` for every pixel check (digests, text box, prompt box)
- Vision calls (planner, Recovery, cursor-mode roles) instead attach pokemon-agent's `GET /screenshot/grid?scale=4`: the same frame at **640×576** with labelled A1..J9 walk cells and the player boxed at E5. It is fetched only for a vision call (`NousRedEnvironment.vision_frame`) and falls back to the native frame on an older server. The prompts tell the model each cell is one walk tile; the `map.grid` ASCII uses the same cells
- Attached via Cursor `SDKImage.from_file` with the file's real pixel size as `dimension` metadata
- **No Gemini `media_resolution`** (low/medium/high) on this SDK path — vision-only does not change image token billing by itself
- `vision_only` default **true** — this is the only supported path. RAM is not used for prompt cadence, action gating, or dialog detection anymore (see known pitfall #6): `joy_ignore`/`dialog_active` were confirmed wrong on Red Star. RAM is still read for the Nuzlocke referee (badges/party/battle — deterministic bookkeeping, not shown to the LLM) since there's no reliable vision-only substitute for permadeath/encounter tracking
- Cursor provider keeps one durable agent (the planner, in dual mode); when context hits ``compact_at_tokens`` (default 250k) it asks for a short session summary, then recreates with that summary carried forward
- Dual mode (`config/agents.yaml`): the planner returns `steps`, up to 6 buttons (`walk_*`, `press_a`, `press_b`, `press_start`). An overworld path is pressed in one burst, with a screenshot between walks. The burst stops when a walk leaves the tile unchanged (a wall turn or a stuck press), when a text box or prompt appears, or on a battle or map change — and it does not then press the `press_a` that followed, unless the walk turned the player toward it. A stuck press while something else moves is waited out first (see Scripted scenes). Planned steps in a battle are the battle agent's, so the arbiter accepts them. It looks again after that. A step whose walk already failed on this tile is not pressed. Naming and menu steps stay one button per cycle: those walks move a cursor, so an unchanged map tile does not abort them. With no steps, a named step that is not the beat's heading is one press, then another look. On a trusted grid the beat heading is a run of the open tiles that way, up to `walk_*_5`; a blocked heading sidesteps once. An untrusted grid does not invent that run. An unsure Jev answer does not cancel a planned walk. Mechanical disengage is one step toward that heading, not a random circle. On the naming keyboard the steps can type a name and finish it with `press_start`.
- Walk grid trust: `map.grid` (pokemon-agent's tilemap read, vanilla pokered collision tables) is shown to the planner and Jev and drives heading/sidestep choices, but it is not "the authority". On Red Star's Oak's Lab it drew all four neighbors as `#` while the player walked freely. `GridTrust` counts each walk in a burst that lands on a tile the grid called `#` on the same map; after two, that map's grid is withheld from prompts and the step picker for the rest of the run. Door mats read `#` too, but walking down from one changes the map, so that never counts — and named steps are still pressed into `#`, or nobody could leave a house

### Jev input

Jev (TypeSafe System One) reads text only, and each call is judged by itself. It chose a safe B on 31% of its answers in run `20260927-235608-cc25eb`, because the facts that decide a button were spread across the state. The input is now built the way the Jev harnesses that finished Red built theirs:

- **The facts go on the options.** Each overworld `walk_*` criterion says whether the grid shows that tile open, which targets it is the first A* step toward ("first step toward exit (door or stairs out) (6 tiles)"), whether it is the story heading, and how often it was already pressed on this tile with no move. `press_a` says what it talks to, or "nothing in front". TypeSafe: "write descriptions that separate the options from each other".
- **Targets** (`nuzlocke/agents/targets.py`) are the planner's `target` cell (turned into a map tile when the card is stamped, so it stays right while the player walks), plus the map's warps, signs, and on-screen NPCs from WRAM. The path is `pokemon_agent.pathfinding.find_path` over the on-screen grid. A door counts as the goal even though its mat reads `#`, and a person is walked up to and faced. The targets only label options; nothing auto-walks.
- **The state is cut to the scene.** Overworld: plan, goal, `where` (map, x, y, facing, grid), targets, last 4 `recent` as `actions -> outcome`. Battle: plan, both mons' species, level, HP, and types, our moves and PP, and the type matchup. Menu, naming, dialog: plan, `hard_signal`, last 2 recent. `memory`, `failed_approaches`, and Nuzlocke bookkeeping go to the planner only. Each scene has its own `action.instructions`, and the `plan_stale` / `objective_done` nouls are asked only in overworld and dialog.
- **Every call is logged** as a `jev_call` event: the scene, the menu with its criteria, the state size, the full probability distribution, confidence, nouls, whether it was accepted, and latency. The sandbox `summary.json` has a `jev` block (calls, confidence p10 and p50, unsure share, mean state bytes, latency).
- Confidence is TypeSafe's spread measure, `(n·p_max − 1)/(n − 1)`. The same floor asks more of a 2-option menu than of a 6-option one.

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
17. **B cancels an evolution.** Gen 1 stops an evolution when B is pressed during it, and `skip_dialog` pages every narrative box with B, including "What? CHARMANDER is evolving!". Not handled yet. Caterpie and Weedle evolve at level 7, so this matters by Viridian Forest.
18. **Doors read as walls, and the warp table is RAM.** pokemon-agent's walk grid shows door mats and stairs as `#`, so nothing on it says where the exits are. `nuzlocke/environment/pa_serve.py` runs pokemon-agent's own server with one more route, `GET /map/objects`, which returns pokered's `wWarpEntries`, `wSignCoords`, and sprite slots (`wSpriteStateData1/2`). The adapter starts the server as `python -m nuzlocke.environment.pa_serve serve …`. On Red Star, Oak's Lab read exactly as in pokered: the door warps at (4,11)/(5,11), the three balls at x 6–8 y 3, Oak at (5,2). Outdoor maps and signs have not been checked on the emulator yet. `ObjectTrust` withholds a map's objects for the rest of the run after two map changes that did not start on or next to a listed warp. An older server without the route leaves the lists empty.

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
