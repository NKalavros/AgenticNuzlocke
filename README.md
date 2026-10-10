# Agentic Nuzlocke Runner

This program plays Pokémon Red under Nuzlocke rules.
It uses language models to select objectives and actions.
The default game is Red Star, a modified version of Pokémon Red.

The emulator and the Field Log come from [pokemon-agent](https://github.com/NousResearch/pokemon-agent).
This project adds navigation, rule checks, battle plans, and saved run data.

## Before you start

You need these items:

- Python 3.12 or later.
- [uv](https://github.com/astral-sh/uv).
- A legally obtained Pokémon Red-compatible `.gb` ROM file.
- Access to the selected model providers.

A *provider* is the service or local client that connects the program to a model.
A *checkpoint* contains an emulator state and its related controller state.
A *sandbox* is a separate emulator for tests.

The default providers are Jev for System 1 and Codex for System 2.
Install the Codex CLI before you use this configuration.
See [provider setup](docs/providers.md) for the other providers.

## Install and start

Run these commands from the project directory.

1. Install the project dependencies.

   ```bash
   uv sync
   ```

2. Sign in to Codex with your ChatGPT account.

   ```bash
   codex login
   ```

3. Set your Jev API key.
   Replace `YOUR_JEV_API_KEY` with your key.

   ```bash
   export JEV_API_KEY=YOUR_JEV_API_KEY
   ```

4. Check the provider configuration.

   ```bash
   uv run nuzlocke llm doctor
   ```

5. Start a run.
   Replace `/path/to/game.gb` with your ROM path.

   ```bash
   uv run nuzlocke run --rom /path/to/game.gb
   ```

6. Open the **Route monitor** URL from the command output.
7. Select **START** on the dashboard.

The program also reads keys from `.env`.
Existing environment variables have priority over `.env` values.
Keep keys and ROM files out of version control.

## Watch and control a run

The default dashboard is [the route monitor](http://127.0.0.1:8766/navigation).
Use the printed URL if your configuration uses a different port.
The dashboard shows the game, party, objectives, and route.
The [Field Log](http://127.0.0.1:8766/dashboard) shows decisions and actions.

If movement repeats without progress, the program starts recovery.
System 2 reviews the scene at the first recovery stage.
The message **automatic recovery routing** describes this control step.

System 1 receives the route instructions and restrictions from System 2.
Repeated speech can start recovery.
The program tests one unknown tile at a time.
It collects an item only when the full approach path is known.

Select **PAUSE** to pause the run.
Select **START** to continue it.
Select **STOP** to end the run.

The default run ends at Misty's Cascade Badge.
A full party loss also ends the run.
You can set a different stopping point in [config/run.yaml](config/run.yaml).
Guidance through Lt. Surge, Erika, and Koga is available.
Full-game completion is not verified.

Help for the Lt. Surge switch puzzle is on in [config/run.yaml](config/run.yaml).
The program reads the correct switch from game memory.
It then walks to the can and presses A.
This help works with the verified Red Star ROM.
Set `surge_puzzle_assist: false` to turn it off.
Healing still has priority.

## Select models

Set `system1` and `system2` in [config/agents.yaml](config/agents.yaml).
You can also use command options.
This example uses Codex login for both systems:

```bash
uv run nuzlocke run --rom /path/to/game.gb \
  --system1-provider codex --system1-model gpt-6-luna \
  --system2-provider codex --system2-model gpt-6.1-sol
```

Use model names available to your account.
Model changes take effect when a new process starts.
See [provider configuration](docs/providers.md) for Claude, Antigravity, Gemini CLI, Cursor, and API connections.

If a provider fails in dual mode, the program pauses.
Correct the provider problem.
Then select **START**.

## Continue a saved run

Replace `RUN_ID` with the directory name under `runs/`.

```bash
uv run nuzlocke run --resume RUN_ID
```

Each completed cycle saves a checkpoint.
The program checks the ROM, rules, state checksum, and recorded rule events before it continues.
An interrupted action can prevent continuation.
Use a sandbox to inspect that state.
Do not remove checkpoint markers to force continuation.

## Test in a sandbox

This command copies a saved state into a separate run directory.
It sends wait actions without model calls.
The source run remains unchanged.

```bash
uv run nuzlocke sandbox --from RUN_ID --script "wait_60*3"
```

To test the full controller, use `--steps 30` instead of `--script`.
This mode makes real model calls.
See [run operations](docs/operations.md) for saved-state selection and test reports.

## How the program works

| Component | Function |
|---|---|
| System 1 | Selects legal actions and operates paths, menus, and battles. |
| System 2 | Reads screenshots and sets objectives and trainer battle plans. |
| System 3 | Applies encounter, death, healing, and level-cap rules. |
| Action Arbiter | Checks each proposed action against a fresh observation. |

The emulator advances only when it receives actions.
A delay in Python does not advance the game.

The rules permit capture balls in battle.
The program uses the full bag list to find a capture ball.
It scrolls one row at a time and checks the displayed selection before it throws the ball.
Other battle items are prohibited.
Healing uses Pokémon Centers or Mom.
The agent can clear a necessary obstacle on the route to healing.
It must check the required move and permission, then check the result.
The controller records Rare Candy grants and use during preparation.
When the next task is a gym leader challenge, the controller adds a healing objective.
It keeps this objective until the nurse restores HP, status, and move PP.
It then uses recorded Rare Candies to prepare the living party at the current level cap.
For Lt. Surge, this cap is 24.
The agent returns to the gym after preparation.
These preparation steps cover Brock, Misty, Lt. Surge, Erika, and Koga.
For Koga, the level cap is 43.
A recorded death remains permanent after healing or evolution.

Navigation uses observed terrain and reference maps.
Observed movement has priority over reference maps.
The program checks current terrain before it selects a route.
If the terrain changes, old movement data cannot keep the path open.
A return to a map also cancels old movement data for that map.
The program keeps its exploration history.
A partial path does not trigger the destination's interaction.
The agent can use route points to reach an obstacle and interact with it.
The main objective stays the same.
Walkthrough fragments supply guidance for the current stage.
Before Lt. Surge, the agent must use CUT and enter the gym.
A learned move does not confirm that the path is open.
After Erika, the agent obtains the Silph Scope and the Poké Flute.
It then follows the land route to Fuchsia and Koga.
Observed items and location select the next objective.
The Soul Badge confirms completion of Koga's gym.
Set `stop_after: koga` to stop at this badge.

Surf guidance starts when the agent detects HM03 in the bag or SURF on a living party member.
The agent must have a living SURF user and the Soul Badge before field use.
This guidance does not add a new travel objective.
See [walkthrough composition](docs/walkthroughs.md) to add or combine fragments.

## Change the code

Read [AGENTS.md](AGENTS.md) before you change the controller.
Run these checks after a change:

```bash
uv run pytest -q
uv run python tools/core_loc.py --check
uv run python tools/walkthrough.py --check
```

The core must contain fewer than 12,000 Python source lines.
The count includes all Python in `nuzlocke/` and `apps/`.
Blank lines, comments, and docstrings do not count.
Tests, tools, and walkthrough content do not count.
Python walkthrough loaders and selectors do count.

Use [runtime notes](docs/runtime.md) for controller details.
Use [debugging notes](docs/debugging.md) for known emulator problems.
Use [validation records](docs/validation.md) for measured results and remaining limits.
The old planning files describe proposals that can differ from the current code.

This guide uses the writing principles of [ASD-STE100](https://www.asd-ste100.org/about_STE.html).
Product names, game terms, paths, and code identifiers are technical names.
