# Agentic Nuzlocke: agent handoff

Use this file and [README.md](README.md) for the current implementation. `PLAN.md` and `AGENT_READY_PLAN.md` are historical proposals.

## Work boundaries

- Preserve existing uncommitted work. Commit only when the user asks.
- Do not restart, stop, or send actions to a live run unless the user asks. Use a private sandbox for probes.
- Never commit ROMs, `.env`, credentials, or `runs/` artifacts.
- Find the emulator dependency under `.venv/lib/python3.*/site-packages/pokemon_agent/`; do not search the whole disk.
- Keep code, README, and these instructions consistent. Put detailed mechanics in the linked references.
- Do not add delegation or parallel agents unless the user requests them.

## Project and execution

Python 3.12+; dependencies and entry point are in `pyproject.toml`. `pokemon-agent` supplies PyBoy and the Field Log. This repo owns the controller, rules, navigation, provider adapters, and route dashboard. The configured ROM is Red Star.

```bash
uv sync
uv run pytest -q
uv run nuzlocke llm doctor
uv run nuzlocke --help
```

`config/agents.yaml` selects independent `system1` and `system2` providers. The default pair is Jev and Codex. Sol 6.1/Luna is an explicit override, not the checked-in default. Use `--system1-provider codex --system1-model gpt-6-luna --system2-provider codex --system2-model gpt-6.1-sol` when requested. See [providers](docs/providers.md) for authentication, supported combinations, and endpoint contracts. Credentials stay with vendor clients; API providers use separate keys. No silent fallback to another provider or billing method.

`config/run.yaml` controls ROM, port, timing, preparation, and `stop_after`; the default stop is `misty`. `config/rules_red.yaml` defines hashed rules and caps. Environment overrides are in `nuzlocke/config.py`. `.env` does not replace existing environment values. Leave `NUZLOCKE_RELAY` unset on an open network.

Use the printed Route monitor URL; port 8766 is only the configured default. `/navigation` shows screen, party, objectives, and routes. `/dashboard` is the Field Log. A normal run waits for START; a sandbox loop starts automatically. Provider failures pause dual-mode play until START retries.

## Controller contract

Order: settle → atomic observation → rule/ledger update → mandatory interventions and objectives → System 1 → System 2 when required → arbiter → fresh policy check → action → journal → paired checkpoint.

- System 1 owns paths, menus, and battle execution. System 2 owns strategic objectives and structured trainer plans. System 3 constrains both before decisions.
- Recovery routing is deterministic; it does not require a separate Director provider. Tiers 1/3 call the configured System 2 provider even with a fast System 1 actor; tiers 2/4 mechanically disengage. Do not silently send tier 1 back to the stale actor plan. An explicit tile target on a known warp uses that exit's route; incidental paths still exclude other warps. See [regression replay](docs/validation.md#recovery-handoff-and-explicit-door-targets-2026-10-05).
- Deaths and encounter outcomes are permanent. Capture identities, the balls-acquired latch, battle-entry eligibility, and event-chain history survive checkpoints.
- Only capture balls are legal battle items. Healing is Centers/Mom; candy preparation uses audited grants and normal menus. Never bypass the final arbiter to make a test pass.
- Healing, dead storage, preparation, and supplies take priority over optional pickups and progression. A mandatory healing objective persists when a route is unknown or blocked. System 2 may set route and field-move subgoals while the displayed healing objective stays locked. Check actual living move users and field permission; do not invent an ability. Only observed recovery releases healing. See [healing guidance](.cursor/skills/pokemon-red-walkthrough/fragments/healing.md).
- When Brock/Misty/Surge/Erika/Koga is ready to challenge, checkpointed `GymPreparation` inserts heal → prepare → challenge. Require nurse acceptance, restored living HP/status/observed PP, and closed text before preparation. Use audited candies at the leader's Center to the current cap (Surge 24, Koga 43); preserve the stage across planner updates and resumes. Leader A stays blocked until ready. Surge's verified open-lock flag can establish readiness in the gym, city, or Center; hidden can indices remain gym-only. Koga preparation starts on arrival in Fuchsia city/Center/gym, before its strong maze trainers.
- Pick up available items only with a complete legal approach. Off-screen NPCs can block paths. Do not repeatedly select an unreachable item or treat its absence as successful collection.
- Post-Rainbow guidance uses inventory-confirmed Lift Key → Silph Scope → Poké Flute, then the land route to Fuchsia and Koga. Observed arrival beyond Snorlax bypasses obsolete key errands. `stop_after: koga` ends only on Soul. Surf guidance requires positive HM03 inventory or SURF on a living member; field guidance additionally requires Soul. Do not inject Surf from keywords or add a Safari/sea-travel objective. See [Koga guidance](docs/runtime.md#guidance-after-erika).
- Retire objectives from observed evidence: badges, inventory, learned moves, and committed encounter outcomes. Planner prose cannot establish completion.
- Preserve trainer plan conditions, bans, allowlists, and opener counts. An opener is consumed only after observed PP loss. Malformed conditions invalidate the plan.

See [runtime reference](docs/runtime.md) for preparation targets, encounter coverage, routing, menu ownership, and the full loop. Scripted story beats end at Misty; final preparation covers leaders through Koga. This is not proof of full-game automation.

## Emulator facts that affect fixes

- The emulator freezes between `/action` calls. Send wait frames to advance text or transitions; Python sleep only changes wall time.
- Trust screenshots over Red Star RAM dialog/readiness flags. Use the decoded screen and pixel boxes; do not reintroduce RAM readiness polling.
- Ordinary `walk_*` moves one tile. Into a wall it can only turn. Do not add a second press for every facing change.
- Directed ledge drops are two-tile transitions from one walk press. They do not prove reverse traversal or open intermediate floor.
- B answers NO at YES/NO and can cancel evolution. Overworld speech uses released B rounds; battle narration uses one A page. Stop at menus and prompts.
- TM/HM teaching uses the visible ABLE/NOT ABLE list, not vanilla compatibility guesses. Raticate is NOT ABLE for CUT in the tested Red Star state. Preserve text-only planner goals through menus and pass the field objective to move replacement. See [CUT replay](docs/validation.md#cut-menu-execution-2026-10-05).
- Gym access is a separate objective stage from teaching CUT and solving the gym locks. Use a current-map `tile` target for the approach; arrival triggers the next planner decision. Verify the field-move result before selecting an exit behind the obstacle. See [runtime guidance](docs/runtime.md#guidance-after-misty).
- `surge_puzzle_assist: true` explicitly permits hidden RAM assistance for Surge's switches, including in vision-only runs. The reader is restricted to the verified Red Star ROM hash and gym layout. It reads the current first/second index and lock flags; normal arbiter-checked walking and A presses open the locks. Reread the second index after the first opens; do not enforce adjacency (vanilla has a nonadjacent-can bug). Healing and other mandatory beats retain priority. Stop can searches when both lock flags are open, verify the barrier passage, and require Thunder to complete the gym. See [replay](docs/validation.md#surge-ram-assistance-2026-10-05).
- The instant-text bit also appears on Pokédex and battle bag screens. Recognize the naming keyboard by its visible letter grid.
- Capture bags use shared `inventory.capture_ball_actions` in System 1 and the final arbiter. Infer the absolute cursor from the visible item label and full bag order; move one row per observation and select only a positive-quantity capture ball. Never substitute generic row choices or B while a legal catch requires scrolling. Close the bag when survival, encounter legality, or missing balls require another action. Do not trust scratch menu-scroll RAM over the visible cursor. See [Route 9 replay](docs/validation.md#off-screen-capture-balls-on-route-9-2026-10-07).
- `settle()` precedes observation. `/snapshot` reads under the action lock without advancing frames. Every internal action feeds rule tracking.
- Reference geometry is advisory. Observed terrain restrictions and directed blockers apply to all paths. Temporary bumps expire; never turn a held-input scene into permanent walls.
- Exploration history does not prove current walkability. `RoomMap.floor` refreshes observed geometry; successful floor/edge overrides are scoped to the current map visit and invalidated at either changed endpoint. Preserve remembered layouts and exploration history on reentry. Checkpoint `walked` and `active_map`; legacy `visited` must not become new traversal proof. Paths, waypoint admission and planner map rows share this evidence. Do not add tree-specific objectives to repair stale geometry.
- Partial routes reveal unknown geometry; unvisited but already mapped floor is not a frontier. Only full interaction routes retain a final A; `face` positions cannot use the blocked-door exception. Planner `route_plan` waypoints may approach an obstacle while preserving the code-owned destination. Final waypoint arrival with no full route triggers `route waypoint reached` immediately, without exploration cooldown or a temporary objective. Keep route identity separate from an empty route and include the interaction position and facing.
- Overworld menus receive the current planner execution text, bans and System 3 constraints alongside the unchanged destination objective. Do not drop execution intent when the destination is code-owned; doing so can turn a planned field action into START → EXIT.
- Overworld goal decisions receive the same execution text and bans. Restoring a reachable healing destination must retain the planner card. Planning does not erase unresolved goal failures; a burst that moves and then hits a blocker still counts the failed goal. Choice-only actors request System 2 after two failures rather than inventing a runner-up distribution.
- Ordinary speech retains recovery evidence, even when the D-pad is ignored. Only titles and script-held movement without a text box suspend recovery. Planning cooldown is scoped to the current map and mandatory objective. A rejected or mismatched route reports the current map/goal and rejection to System 2 immediately. Validate healing waypoints before declaring its exit blocked; keep the displayed healing objective locked.
- Collision decoding reads the active fixed-ROM list through `wTilesetCollisionPtr` (`D530`, FF terminator), with vanilla fallback for invalid pointers. This covers Red Star tileset 24 without assuming vanilla Facility geometry. Unknown floor cannot establish a complete path, a cached verified segment, or an item approach; probe it one tile at a time. See [handoff replay](docs/validation.md#system-1system-2-handoff-repairs-2026-10-10).

Read [debugging notes](docs/debugging.md) before changing movement or menus. They retain numbered historical pitfalls and replay evidence.

## Checkpoints and private tests

Each completed cycle commits an immutable emulator/controller pair and atomically updates `checkpoints/current.json`. The `auto.state` file is a convenience copy. `checkpoints/pending.json` marks an in-flight mutation. Never delete it to force legal resume. Resume checks ROM/rules hashes, state checksum, and the event chain. Wipes and unpaired legacy states refuse legal resume.

```bash
uv run nuzlocke sandbox --from RUN_ID --script "wait_60*3"
uv run nuzlocke sandbox --from RUN_ID --state commit-00000042 --script "walk_down press_a"
uv run nuzlocke sandbox --from RUN_ID --steps 30
```

Script mode makes no model calls. Loop mode does. Sandboxes copy source state and matching controller history, own a separate server, and leave the source untouched. Use a free port or explicit `--port` for concurrent probes. See [operations](docs/operations.md) for artifacts and summary metrics.

For controller changes, run relevant regression tests, then the full suite. Verify movement, dialog, and menu claims with a deterministic private emulator replay. Retain failures and record evidence in [validation](docs/validation.md). A replay is diagnostic evidence, not a fresh-run acceptance trial. The paid five-run benchmark is `uv run nuzlocke benchmark --trials 5 --steps 1500 --output runs/brock-acceptance.json`; do not claim it passed unless run and reviewed.

## Source budget and walkthroughs

The core limit is **strictly below 12,000 source lines**. Count every `.py` file in `nuzlocke/` and `apps/`, including walkthrough selectors, loaders, and adapters. Exclude blank lines, comments, and actual docstrings. Delimiter-only lines count. Tests, tools, and non-Python walkthrough/data files are outside the count. Do not move executable logic outside the core to evade the limit.

```bash
uv run python tools/core_loc.py --check
uv run python tools/walkthrough.py --check
uv run ruff check nuzlocke apps tools/core_loc.py tools/walkthrough.py
uv run ruff format --check nuzlocke apps tools/core_loc.py tools/walkthrough.py
uv run pytest -q
```

Ruff uses 132 columns and ignores magic trailing commas. Keep code readable; do not use semicolon packing or dynamic execution to reduce the count. The source-budget test enforces the limit.

Walkthrough content is in `.cursor/skills/pokemon-red-walkthrough/fragments/`; `manifest.json` defines ordered, reusable bundles and context matches. Edit fragments, then regenerate `reference.md` with `uv run python tools/walkthrough.py --write-reference`. Selectors remain in `nuzlocke/knowledge/walkthrough.py`. See [composition instructions](docs/walkthroughs.md).

Static story/healing catalogs are in `nuzlocke/assets/walkthrough/`. Static prompts, response examples, vendor settings, and reference tables are also under `nuzlocke/assets/`. Load them through `nuzlocke/assets.py`; treat cached values as read-only. Rule decisions and prerequisite checks remain Python. When a prompt includes an excerpt, the game agent must use it without rereading the whole skill.

## Code map

| Area | Owner |
|---|---|
| `apps/orchestrator/main.py` | CLI and commands |
| `nuzlocke/orchestration/` | Run loop, arbiter, ledger, checkpoint, journal, objectives, sandbox |
| `nuzlocke/agents/` | Systems 1–3, navigation, battle, menus, preparation, final policy |
| `nuzlocke/environment/` | Emulator adapter, server extensions, screen parsing, dashboard |
| `nuzlocke/knowledge/` | Stage selectors, encounters, items, maps, trainers |
| `nuzlocke/llm/` | Provider configuration, transports, decisions, diagnostics |
| `nuzlocke/referee/`, `state/`, `memory/` | Rules, typed contracts, event store, optional OptMem |

Known limits: later route validation, general box/team management, damage calculations, unusual duplicate capture identities, FireRed, and automatic checkpoint pruning. Consult the validation record before making acceptance claims.
