# Run operations

See the [quick start](../README.md) for normal use.

### Headless sandbox

Try a fix on a real savestate without touching a live run:

```bash
# Scripted buttons, no LLM. Same savestate + same buttons = same frames.
uv run nuzlocke sandbox --from <run-id> --script "skip_dialog walk_down walk_right walk_up press_a wait_10*6"
# The real loop (planner + Jev) for N cycles; starts without waiting for START
uv run nuzlocke sandbox --from <run-id> --steps 30
# Omit --from to boot the ROM fresh (the intro)
uv run nuzlocke sandbox --script "wait_600 press_start wait_90 press_a wait_120 press_a wait_120 wait_240 press_a wait_180 skip_dialog*10"
```

- Sandbox loops still honor dashboard PAUSE/STOP. Watch `http://127.0.0.1:<port>/navigation` (or `/dashboard` for the Field Log); each private server shuts down when its command finishes. Use distinct `--port` values to watch concurrent sandboxes.
- Each call copies the source's `savestates/auto.state` (or `pokemon-agent-data/saves/auto.state`) into a new `runs/sandbox-<time>-<hex>/`, starts its own pokemon-agent on the first free port from 8791, and stops that server when it finishes. The source run's files and port are not touched
- Script tokens are any `GameAction` (they go through `execute`, with burst stops and `skip_dialog`) or a raw opcode (`press_X`, `walk_X`, `hold_X_N`, `wait_N`), comma- or space-separated; `token*N` repeats. Each row prints map, tile, facing, `box=text|prompt|-`, and world- and text-region digests (a changed `world=` with an unchanged tile is something else moving); frames go to `frames/NNN_<token>.png` and rows to `probe.jsonl`
- A script ends by saving its final state, so `--from sandbox-<id>` continues from the last row. Chain short scripts to reach a scene, then hand it to `--steps`
- Loop mode writes `summary.json` and `journal.jsonl`: cycles, planner looks, `looks_by_reason` (why each look happened), `planner_s` (median, p90, and total seconds per look), recoveries, median cycle time, distinct tiles, the last path, button counts, burst stops, Jev reasons, and a `jev` block (calls, confidence, unsure share, state size, latency). Every `plan` event carries `latency_s` and every `jev` event its `looks`, in live runs too. Loop mode makes real planner calls
- A script's final state is saved even mid-battle, so `--from` can start a loop at a battle; loop checkpoints also preserve mid-battle controller state
- The planner's prompts and answers for a loop are kept by the Cursor SDK outside the repo, under `~/.cursor/projects/<repo-path-with-dashes>-runs-<run-id>-agent-workspace/agent-transcripts/`. Deleting `runs/sandbox-*` does not remove them


## Checkpoints and legal continuation

```bash
uv run nuzlocke run --resume <run-id>
```

Each completed cycle writes an immutable savestate and controller record, then atomically publishes `checkpoints/current.json`. Controller state includes the encounter/death ledgers, battle eligibility and plans, navigation memory/trust, preparation/search state, pending move-learning and shop transactions, and lead rotation. Mid-battle commits are supported. `savestates/auto.state` is a convenience copy for diagnostics.

Resume validates ROM/rules identity, savestate checksum, and the chained rule-event history against its stored head. A pending-action marker, missing paired history, changed identity, corrupted history, or a terminal wipe refuses legal continuation. A crash during an action therefore may require diagnostic inspection instead of automatic resume. Checkpoint writes verify the named flat save through `/nuzlocke/saves/{name}` and compare its SHA-256 with the local mirrored file; they do not enumerate the full save history. `/saves` remains available for explicit listings.

Recovery requires evidence, not removal of `pending.json`. For the inspected Tower interruption, the completed arbiter action and journal were durable, and an orphan save survived. A private replay of that one recorded cycle reproduced the orphan save byte for byte and retained all rule and team state. The recovered controller was then paired with the existing state through the normal commit path. This is a specific audited repair, not automatic recovery for arbitrary interrupted actions.

`checkpoint.every_steps` and `checkpoint.enabled` remain legacy configuration fields; the active paired-commit path runs every completed cycle regardless of those values. Old unpaired states can be inspected with `sandbox --from`.

Servers launched by the adapter require an owner token for action, load, new-game, and preparation requests; competing writers receive HTTP 409. Read-only views and dashboard control remain available. This protects controller ownership, while the event chain detects inconsistent local history; it is not an external tamper-proof audit.

## Sandbox and acceptance

```bash
# Diagnostic replay from an existing run; private emulator and copied state
uv run nuzlocke sandbox --from <run-id> --steps 30

# Deterministic button probe, no LLM
uv run nuzlocke sandbox --from <run-id> --script "skip_dialog walk_down*2 wait_30"

# Choose an immutable saved state by name
uv run nuzlocke sandbox --from <run-id> --state commit-00000050 --steps 30

# Five sequential fresh runs through Brock
uv run nuzlocke benchmark --trials 5 --steps 1500 --output runs/brock-acceptance.json
```

Sandboxes use a new `runs/sandbox-<time>-<hex>/` directory and the first free port from 8791 unless `--port` is supplied. They do not change the source run or restart its server. Matching controller history is copied when available; legacy source states start with an empty controller. Source-state replays are diagnostics, not legal continuations or fresh acceptance trials.

Script probes write `probe.jsonl` and `frames/`; loop mode writes `summary.json`, `journal.jsonl`, events, and checkpoints. The benchmark retains every failed trial and exits nonzero if its aggregate `passed` value is false.

The current automated pass predicate requires every requested trial to complete Brock, without a wipe, exception, or rule alert. Inspect `policy_rejections`, deaths, and event-chain integrity as well when reviewing acceptance. `eligibility_alerts` describe Pokémon unavailable for future battles; they do not by themselves establish an illegal action. The summarizer classifies older outside-battle `rule_violation` events as eligibility notices, so raw event review remains useful.


| Artifact under `runs/<run-id>/` | Contents |
|---|---|
| `manifest.json` | Run configuration and provider metadata. |
| `events.jsonl`, `run.sqlite` | Events; ledger commits, candy grants/uses, wipes, and milestones carry a hash chain. |
| `journal.jsonl` | Per-cycle goal, buttons, outcome, and text for System 2. |
| `checkpoints/current.json`, `checkpoints/commit-*.json` | Latest paired controller record and immutable history. |
| `savestates/commit-*.state`, `savestates/auto.state` | Immutable emulator states and convenience copy. |
| `summary.json` | Sandbox/benchmark outcomes, planner latency, trigger counts, Jev confidence/latency, and navigation metrics. |
| `memory/notes.log` | OptMem notes when enabled. |

Provider transcripts also live outside the repo under Cursor's project agent-transcript directory; deleting a run directory does not remove them. Per-cycle states accumulate without automatic pruning.

