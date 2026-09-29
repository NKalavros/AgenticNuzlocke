# Validation record

Current implementation: **`96a35b7`**, including persistent navigation, the route dashboard, and the type-decoder fix. These are local development results for Red Star; run artifacts are gitignored and are not bundled with the repository.

## Automated checks

- `uv run --no-sync pytest -q`: **317 passed** (0.86 s) before committing `96a35b7`.
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
