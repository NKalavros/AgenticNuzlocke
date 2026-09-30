# Validation record

These are local development results for Red Star; run artifacts are gitignored and are not bundled with the repository. Navigation/display work landed in **`96a35b7`**. The evolution/encounter continuation below describes the subsequent implementation.

## Automated checks

- `uv run --no-sync pytest -q`: **401 passed** after Mart transactions and final gym preparation; previously 381 after ledge routing, 357 after Mt. Moon terrain and ladder regressions, 348 after known-map guidance, 338 after move learning, 330 after evolution/encounter continuation and 317 at `96a35b7`.
- `nuzlocke run --help` and `nuzlocke benchmark --help` checked against the documented flags.
- Unit tests cover policy, preparation guards, active battle state, navigation trust, duplicate families, persistent deaths, battle-entry eligibility, paired checkpoints, and rule-event chains.

## Historical five-run snapshot

Snapshot: **2026-09-29 16:47 UTC**, before the navigation update. The automated suite at that stage had 304 passing tests. The results below are historical; they do not establish fresh-run acceptance for `96a35b7`.

The acceptance target is five independent fresh boots through Brock, with no human gameplay intervention, illegal actions, rollback, or continuation after a wipe. Each trial below started with `sandbox --port <port> --steps 1500`, without `--from`; ports 8801–8805 were used concurrently. The `benchmark` command offers a sequential version of this workflow.

**3/5 had recorded the Boulder Badge at this snapshot.** Acceptance was incomplete. This table is not a live status page. Local progress is in `runs/brock-acceptance.json`; each active command prints its dashboard URL. Private dashboards close when their command finishes.

| Trial | Run ID | Outcome / latest location | Cycles | Planner looks | Deaths | Rule / eligibility alerts | Policy rejections | Rule-event chain |
|---|---|---|---:|---:|---:|---:|---:|---|
| 1 | `sandbox-20260929-121843-9b7c` | In progress: Route 2 (3,11) | 600 | 26 | 0 | 0 / 0 | 0 | Pending completion |
| 2 | `sandbox-20260929-121843-44e4` | Ended before Brock: Route 2 (3,11) | 637 | 20 | 0 | 0 / 0 | 0 | Verified |
| 3 | `sandbox-20260929-121843-ff06` | Boulder Badge | 774 | 19 | 0 | 0 / 3 | 0 | Verified |
| 4 | `sandbox-20260929-121843-68bc` | Boulder Badge | 871 | 26 | 0 | 0 / 2 | 0 | Verified |
| 5 | `sandbox-20260929-121843-1506` | Boulder Badge | 860 | 21 | 0 | 0 / 3 | 0 | Verified |

Summaries above were recomputed from `events.jsonl` using the current `summarize()` implementation. Finished trials' chained event hashes were checked against the SQLite integrity head. Existing per-run summary files from the launched processes may retain the older alert classification.

### How to interpret the evidence

- `party_ineligible` describes eligibility for the next battle. A Pokémon leveling above 14 during a legal Brock battle remains eligible for that battle; the gap before receiving the badge can produce an outside-battle eligibility notice.
- Older code called those notices `rule_violation`. The current summarizer treats older outside-battle notices as `eligibility_alerts`; it does not establish legality solely from the label. Keep the raw events available for review.
- The benchmark's automated `passed` predicate checks every trial's Brock completion, wipe, exception, and rule-alert fields. It does not itself verify the event chain or require zero policy rejections/deaths. Review those fields separately against the intended acceptance criteria.
- The batch recorded source SHA-256 `cc6e086f46ef665aebd82efb13ddc999c2f7e0df27da0ae2c9d981fe427226bc` at launch. An exhausted-PP menu recovery fix and alert-classification correction were made after launch; already-running processes do not pick up those Python changes. Documentation and walkthrough corrections followed. These results therefore do not claim five fresh passes on an immutable copy of the final worktree.

## Diagnostic evidence

Private emulator probes during implementation exercised verified Bulbasaur selection, level-8 lab preparation and the rival, level-12/14 Center preparation, healing menus, buying balls, early-route catches, party switching, evolution, and depositing a permanently dead identity. A snapshot/ownership probe confirmed that repeated reads do not advance frames and a competing action request receives HTTP 409.

`sandbox-20260929-120655-dd04` completed Brock with zero deaths and policy rejections from a Forest savestate. It is a diagnostic replay and is excluded from the fresh-run acceptance count.

An earlier fresh trial, `sandbox-20260929-115257-aa81`, wiped in the rival battle before level-8 lab preparation was added. Its failed development report remains in `runs/brock-acceptance-development.json`; it is not converted into a success by replaying its state.

## Remaining limits

- Full-game completion, broader team/box management, and FireRed are unverified or unimplemented.
- The gate-stall regression now has successful exact-state replays, and a broader Forest replay reached Pewter (below). Repeatability and navigation efficiency still need fresh-run measurement; these diagnostics do not establish efficient navigation on every route.
- Capture identity uses evolution family and trainer ID; unusual duplicate identities can be ambiguous.
- Checkpointing retains immutable state files every cycle without pruning. An action interrupted before the paired commit refuses legal resume.
- The rule-event chain is local integrity protection, not an externally anchored audit.
- The Misty extension is under live validation. Fishing, inaccessible areas, and gift encounters are not comprehensively scheduled. A failed legal capture stays forfeited; search persistence cannot guarantee that every capture succeeds.


## Navigation and display update

Validation on 2026-09-29, after the acceptance snapshot above:

- **317 tests pass**, including route reuse after JSON checkpoint restore, grass-weighted paths, waypoint rejection, directional blockers and expiry, terminal interaction preservation, and corrected type IDs.
- Exact stuck source: `20260929-124729-826a44`, checkpoint `commit-00000791`, Route 2 `(3,11)`. Its controller remembered north/east/west tiles as blocked. A private direct-action probe showed the north path was open: three up presses reached `(3,8)`.
- This confirms incorrect obstruction memory. Code inspection also found cached observations bypassing settling; the probes did not reproduce the exact cause of each original failed input.
- The updated real planner/Jev loop, `sandbox-20260929-132209-0aa4`, reached Pewter at cycle 9 from that checkpoint, including a wild encounter, then entered its Center. Across its 35 cycles: zero deaths, rule alerts, or policy rejections; two planner calls (blocked objective and a stalled text box).
- Deterministic actor route probes also reached Pewter from both just inside the gate (`commit-00000786`, sandbox `sandbox-20260929-132610-a28f`) and the stuck outside position (`commit-00000791`, sandbox `sandbox-20260929-132615-6c8d`). These are navigation diagnostics, not fresh acceptance runs.
- Broader Forest replay: `sandbox-20260929-132608-e402`, starting from the watched run’s Forest entrance checkpoint `commit-00000420`, first reached Pewter at cycle **138** and entered its Center within 180 cycles, with four planner calls, zero deaths, zero rule alerts, and zero policy rejections. This exercised encounters and trainer battles along Forest → north gate → Route 2 → Pewter.
- The loop now settles before every decision, even when it has a cached action result. Confirmed failed directions expire after six cycles; turns, dialogs, battles, and scripted transitions are excluded from wall evidence. Persistent routes and whole-map director context reduce repeated goal selection.
- Live HTTP checks confirmed `/navigation` and `/nuzlocke/navigation` return successfully, unowned telemetry writes receive HTTP 409, and the server reports Beedrill as **Bug/Poison**. The dashboard JavaScript passes `node --check`. Browser visual inspection was unavailable in this tool session.
- Damage calculations are intentionally deferred. This update does not claim five fresh successes on the new navigation code.

## Evolution and post-Brock continuation

- Watched run `20260929-133133-245f6b` earned Boulder with zero deaths. Its `commit-00000818` checkpoint has level-16 Bulbasaur, level-14 Pidgey and Beedrill, eight balls, and caught Route 1/Route 2 slots. The Forest search had reached its old 100-cycle limit; Route 22 was not scheduled. Neither unfinished area had consumed its encounter slot.
- Private replay `sandbox-20260929-140028-da1a`, from pre-evolution `commit-00000807`, used the corrected paging macro and reached **Ivysaur at level 16** after 28 diagnostic cycles. This confirms protection across the final battle page; it was not used to roll back the watched run.
- Private real-loop rehearsal `sandbox-20260929-140149-b7b3`, from the actual post-Brock checkpoint, ran 110 cycles: restocked balls, prepared the party to 18, evolved Bulbasaur into Ivysaur and Pidgey into Pidgeotto, and began the southbound encounter circuit. It recorded **zero planner calls, deaths, rule alerts, or policy rejections**.
- The original run resumes from `commit-00000818` with its ledgers intact. Its next preparation level can retry the canceled evolution normally. The new configured stopping point is Misty's Cascade Badge; the Brock benchmark explicitly retains its earlier stop.
- Regression tests cover evolution protection inside a macro and at the arbiter, partial evolution text, ordinary rival dialog, searches beyond the former limit, skipped Route 22, duplicate-only tables, shared Mt. Moon encounter identity, distinct cave ladders, healing priority, and badge-gated candy grants.
- Loaded land encounter tables use `wGrassRate`/`wGrassMons`, and cave ladder hints use the map object definitions in [pret/pokered](https://github.com/pret/pokered). The ROM's observed species and warps take precedence over vanilla hints.

- Live continuation verified at cycle 927: Ivysaur, Pidgeotto, and Beedrill at level 18; the run was leaving Pewter toward the unfinished encounter circuit. Cursor API connections were resetting at startup, so dual mode now creates the planner on its first requested look. A model failure pauses play with a paired checkpoint; START retries after connectivity returns. Jev remained reachable.

- By cycle **1002**, the original continuation had caught **Caterpie in Viridian Forest**, with zero deaths. It paused at a trainer-planning request because Cursor remained unreachable; the paired checkpoint was complete with no pending-action marker. Route 22 was still pending. No claim is made that every scheduled encounter or Misty is already complete.

## Move learning

- Source: watched run `20260929-133133-245f6b`, `commit-00001646`, paused at Butterfree's level-13 Poisonpowder prompt in Viridian Center. The candy handler proposed A+WAIT, while menu policy allowed only A; repeated rejections caused the stall. There was no dedicated learning handler. A first private probe also exposed the forget list overwriting the speech frame's upper-right border, hiding “Which move should be forgotten?” from the text reader.
- Private real-loop replay `sandbox-20260929-205003-fc88` completed **110 cycles** from that checkpoint: Poisonpowder replaced Harden, Stun Spore replaced String Shot, Sleep Powder replaced Poisonpowder, and Supersonic was declined. Each result was verified against the roster. Butterfree reached level 18 with Tackle / Stun Spore / Sleep Powder / Confusion, then the run reached Route 22.
- Replay totals: **zero policy rejections, casualties, rule alerts, recoveries or planner calls**; four Jev move-learning calls. This is a continuation diagnostic, not a fresh acceptance run or a rollback of the live run.
- Tests cover the actual overlapping frame, in/out-of-battle learning, learner identity distinct from the active Pokémon, checkpoint restoration, one-button policy agreement, decline confirmations, move protections, stale prompt rejection and retry after a model failure.
- Move facts and the learning flow follow the primary [pokered move table](https://github.com/pret/pokered/blob/master/data/moves/moves.asm) and [learning routine](https://github.com/pret/pokered/blob/master/engine/pokemon/learn_move.asm). ROM scratch fields are consulted only on recognized learning screens. Vanilla move facts can differ in ROM hacks; battle damage calculations remain deferred.
- The original watched run resumed from the same `commit-00001646`, independently verified all four learning outcomes above, and continued through Viridian City toward Route 22 by cycle 1738. Its level-18 Butterfree has Tackle / Stun Spore / Sleep Powder / Confusion; all four party members were healthy at this check.

## Route 3 navigation and known-map context

- Watched run `20260929-133133-245f6b` caught Nidoran♂ on Route 22 and Jigglypuff on Route 3. Later Spearow on Route 3 were correctly skipped because that area's catch was already used. The forced-run reason incorrectly always said low HP; it now distinguishes duplicates, ineligible catches and critical HP.
- At `commit-00002653` (cycle 2652), the player was looping on Route 3. The story beat incorrectly requested east although the live connection table contained only north and west. The edge search also alternated between a visited dead end and a perpendicular detour. Fixed the beat to north, rejected nonexistent connections even with a cached route, and made the fallback search prefer new frontier tiles.
- The first corrected-direction-only private replay still looped. After the frontier fix, replay `sandbox-20260929-210616-aa9d` left Route 3 and entered Mt. Moon. The source run stayed paused and unchanged during these diagnostics.
- Added a 31-map vanilla reference atlas, generated from primary [map headers](https://github.com/pret/pokered/tree/master/data/maps/headers), [map blocks](https://github.com/pret/pokered/tree/master/maps), [blocksets](https://github.com/pret/pokered/tree/master/gfx/blocksets), [objects](https://github.com/pret/pokered/tree/master/data/maps/objects) and [collision tables](https://github.com/pret/pokered/tree/master/data/tilesets). System 2's navigation payload now includes this full reference, the desired exit and an advisory shortest path. System 1 follows observed reachable segments toward the reference route. Tests cover actual Route 3 crossing coordinates, Forest entrance-to-exit routing, live wall/blocker overrides, reference/observation separation and dimension mismatches.
- Replay with the atlas, `sandbox-20260929-211231-9165`, entered Mt. Moon on step 15 (16 cycles from the paused battle). Across 35 cycles: zero casualties, rule alerts, policy rejections, recoveries or planner calls. This verifies System 1's guidance; System 2 payload inclusion is covered by tests, without an unnecessary paid planner call.
- Dashboard JavaScript passes `node --check`; browser visual inspection remains unavailable in this session. The atlas is a walking reference, not trainer-risk or damage calculation support.
- The original watched run resumed from `commit-00002653` with its encounter history intact and reached Mt. Moon 1F by cycle 2672. Live HTTP checks confirmed the reference payload and the dashboard's reference toggle were served. The encounter-search objective takes precedence over the cave-exit objective until that area's legal encounter is resolved.

## Mt. Moon terrain and ladder selection

- Source: watched run `20260929-133133-245f6b`, `commit-00004559` (cycle 4558), paused in a wild Paras battle at Mt. Moon B2F `(24,12)`. Earlier walking cycles repeatedly tried north across the elevation boundary at y=11/12 while seeking healing. The reference path excluded those crossings, but the actor's graph and cached paths only excluded short-lived bump evidence.
- Healing also picked the first ladder with destination B1F, `(25,9)`, although it lies in a disconnected chamber. Exit selection now ranks observed reachability and reference connectivity. The main-area return ladder `(21,17)` leads to the B1F corridor whose surface ladder is `(5,5)`.
- The initial replay after adding reference-edge constraints reached B1F but exposed a Red Star difference there: floor `0x05` beside `0x2A` was individually classified as walkable, although crossing between them is blocked. Live terrain IDs now supply persistent edge constraints using the primary [Gen-1 land tile-pair table](https://github.com/pret/pokered/blob/master/data/tilesets/pair_collision_tile_ids.asm). Successful crossings can override assumptions; battle/menu tilemaps cannot overwrite terrain memory.
- Corrected real-loop replay `sandbox-20260929-214039-7b34` left B2F on cycle 13 and returned to 1F on cycle 18, then continued toward the cave exit. Across **100 cycles**: zero deaths or rule alerts, one planner look (`no plan`), and four policy rejections of RUN while the over-cap lead required switching. These were blocked proposals; the resulting switches completed. The replay did not reach the Center within this budget, so healing is not claimed complete. The later battle was a wild Zubat, not a trainer.
- Nine new regression tests cover bidirectional cliff restrictions between open tiles, connected-ladder choice, remembered-wall preservation, live Red Star terrain, successful-crossing overrides, cached-route rejection, jump evidence, terminal warp constraints and controller checkpoint restoration. Terrain boundaries are displayed separately from temporary blockers; JavaScript syntax checked with `node --check`.
- The original watched run resumed from `commit-00004559`, left B2F through `(21,17)`, and was traversing B1F toward the correct `(5,5)` surface ladder by cycle 4574. The live navigation endpoint reported 44 terrain boundary edges on that floor. Its ledgers were preserved.

## XP headroom and the Mt. Moon NPC stall

- Source: watched run `20260929-133133-245f6b`, `commit-00017428`, stopped at Mt. Moon 1F `(16,24)`. Ivysaur was already level 22 against Misty's cap of 21. The controller misread NPC speech “What? I'm waiting for my friends…” as an evolution and repeatedly waited. The shared evolution detector now distinguishes partial species announcements from ordinary speech. A 30-cycle evolution watchdog pauses instead of waiting indefinitely.
- Added `level_cap_buffer: 1`: levels 20/21 are reserved before Misty, with legal necessity exceptions. Healthy suitable alternatives are preferred through both actor and arbiter. Routine candy preparation is clamped below the reserve band (12 before Brock, 19 before Misty). Hard battle-entry eligibility remains unchanged; this does not lower Ivysaur's existing level or erase its history.
- Lead rotation uses ordinary party menus, persists its target by capture identity, verifies the actual swap, and waits for menu closure. A trainer interruption discards the pre-battle target so post-battle health is reassessed. A 40-cycle watchdog pauses unexpected menu flows. Switching only after entering battle can still share XP; the buffer is a heuristic, not an XP or survival guarantee.
- Private replay `sandbox-20260929-234851-d0bd` paged the exact stuck dialogue and switched Ivysaur out for Nidorino in the triggered trainer battle. Its 70 cycles had zero deaths, rule alerts, or policy rejections; three planner calls. Continuation `sandbox-20260929-235358-5a1c` ran 80 more cycles, finished that battle, rotated the lead, reached the Mt. Moon Center, healed the entire party, and returned to the cave. It had zero deaths, rule alerts, or policy rejections and one planner call. Existing over-cap eligibility alerts remained present throughout both replays; they are not claimed resolved by the new buffer.
- Separate replay `sandbox-20260929-235023-8bba`, from the earlier `commit-00004559`, verified the complete Nidorino lead swap and continued from B2F into B1F. Across 45 cycles: zero deaths, rule alerts, policy rejections or planner calls. An earlier diagnostic exposed a partly redrawn START menu after B; closing now includes released wait frames before checking for overworld control.
- **367 tests pass**, including reserve thresholds, necessary-use exceptions, hard-ineligible lead replacement, matchup/health checks, catch/flee priority, actor/arbiter agreement, checkpointed menu rotation, interrupted rotation, ordinary “What?” speech and the evolution watchdog. Ruff checks for the added modules/tests pass.
- These are private diagnostics. The watched run remains stopped at its unchanged `commit-00017428`; no diagnostic state replaced it. Fresh Brock/Misty acceptance under the new preparation ceilings has not been established.


## Mt. Moon fossil context and interaction

- Watched run `20260929-133133-245f6b` was looping in B2F while targeting the northwest ladder. `/map/objects` already contained both sprite-75 fossils at `(12,6)` / `(13,6)`, but the actor called them generic people and discarded off-screen targets. The director's navigation payload omitted objects. The story text mentioned fossils while the machine target skipped straight to the exit.
- Added named object context, explicit slot targets that survive moving off screen, approach instructions and a fossil story step completed by bag evidence. Primary object identities and the collection sequence are from [pokered's Mt. Moon objects](https://github.com/pret/pokered/blob/master/data/maps/objects/MtMoonB2F.asm) and [map script](https://github.com/pret/pokered/blob/master/scripts/MtMoonB2F.asm); live coordinates and screenshots remain authoritative on Red Star.
- Initial private replay `sandbox-20260930-002221-7e43` reached the fossils and collected Dome, but exposed B paging declining Helix while its YES/NO was still appearing. A script probe from its `commit-00000010`, `sandbox-20260930-002302-75d0`, confirmed a released 60-frame wait turns that text frame into the active prompt. Actor, arbiter and paging macro now protect this transition; receipt text is acknowledged with A.
- Corrected replay `sandbox-20260930-002352-aa41` collected **Helix Fossil**, completed the scientist's script, reached B1F at cycle 27 and eastern Route 4 at cycle 29. Across 75 cycles: zero deaths, rule alerts, policy rejections or planner calls. Route 4's pending encounter search continued; Cerulean arrival is not established by this probe. Existing Ivysaur eligibility alerts remain.
- **373 tests pass**, including bag-confirmed story completion, named off-screen director context, actor slot identity, prompt/arbiter agreement, receipt handling and macro protection before YES/NO appears. Dashboard JavaScript passes `node --check`; browser visual inspection was not performed.

- Original watched run resumed from unchanged `commit-00018258` after the private tests, selected **Helix Fossil** at cycle 18268, and confirmed it in the live bag. The navigation endpoint serves named fossils and their coordinates. Ledgers and prior outcomes were preserved.


## Directed ledges and Route 4 objectives

- The continuation loop alternated between the cave-entry objective and generic exploration. The east/west test used x>25 even though Mt. Moon's eastern exit is at x=24. The actor had observed grass beyond a ledge but its route graph excluded jumps; encounter search fell back to exploration, while its blanket recovery exemption hid the navigation failure. Story, encounter and healing now share the east-region test based on the actual B1F exit. Approach-to-grass and pacing-in-grass are separate phases; only the latter suppresses loop recovery.
- Reference atlas generation now includes grass patches and directed ledge transitions from [pokered's ledge tile table](https://github.com/pret/pokered/blob/master/data/tilesets/ledge_tiles.asm). Live terrain overrides reference tile pairs. Actor routing, reference paths and cached-route validation share the directed transitions; blocked landings and unrelated warps stay excluded. A two-tile jump never establishes a walkable intermediate tile or a reverse edge. Execution sends the direction plus released wait frames, checks the actual landing and ends the burst before further movement.
- Private replay `sandbox-20260930-003635-eca7`, from the paused original checkpoint, crossed `(64,8)` → `(64,10)` on cycle 1, resolved Route 4's legal encounter by **catching Rattata**, reached Cerulean City on cycle 83 and entered its Center within 90 cycles. Totals: zero deaths, rule alerts, policy rejections or planner calls. Existing Ivysaur eligibility alerts remain; they are not new cap violations.
- Reverse emulator probe `sandbox-20260930-003704-2cd9`, from the replay's `commit-00000002`, pressed up twice at `(64,10)`. Both presses remained at `(64,10)`; the first only changed facing. This verifies the actual ledge is not climbable.
- **381 tests pass**. New tests cover down/left/right directed jumps, no reverse traversal, blocked landings, two-tile path coordinates, live reference contradictions, invalid cached jumps, encounter approach/pacing, the Route 4 exit apron, and execution stopping after a verified landing. Dashboard JavaScript passes `node --check`; blue arrows indicate allowed drops. Browser visual inspection was not performed.

- The original watched run resumed from its unchanged `commit-00018519` with the new routing. By cycle 18528 it was at `(65,12)` in Route 4's eastern grass after crossing the ledge. The live monitor serves the directed `(64,8)` → `(64,10)` transition. No private replay state replaced the original run.


## Verified Mart transactions and final gym preparation

- The watched Cerulean Mart loop treated the cursorless ×01 quantity picker as an inactive menu, canceled it with B, then reselected Poké Balls with A. Dedicated transaction stages now handle quantity before hollow-menu paging, and distinguish the two-page price question from its YES/NO overlay.
- Private replay `sandbox-20260930-005154-5776`, copied from the watched run, bought one Poké Ball: **9 → 10 balls, ¥3391 → ¥3191**, verified the purchase, exited the shop, and continued toward Route 24. Across 25 cycles: zero deaths, rule alerts, policy rejections, or planner calls. Existing Ivysaur over-cap eligibility alerts persisted (25); the replay does not resolve them.
- Live stock reading includes off-screen rows; tests cover Ultra/Great/Poké preference, affordability fallback, mixed-ball totals, scrolling, checkpointed confirmation, incorrect prices/receipts, and bounded failures. Cerulean's actual stock in this save has no Great/Ultra Balls; those purchase preferences have unit coverage, not a later-town emulator acceptance run.
- Final gym preparation now tops the living under-cap party to 14 before Brock / 21 before Misty at the leader's approach tile. Earlier trainers and travel retain the XP buffer. Tests cover all-member completion, withheld interaction, actor/arbiter agreement, healthy-party grants at exact unbeaten-leader positions, badge/position/cap rejection, and unchanged over-cap ineligibility.

- The watched run resumed its own paired checkpoint and independently recorded the same verified one-ball purchase before leaving the Mart and reaching the Cerulean rival battle. No private replay state replaced the live run.
