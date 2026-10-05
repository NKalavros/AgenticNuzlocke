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

Select **PAUSE** to pause the run.
Select **START** to continue it.
Select **STOP** to end the run.

The default run ends at Misty's Cascade Badge.
A full party loss also ends the run.
You can set a different stopping point in [config/run.yaml](config/run.yaml).
Guidance through Lt. Surge and Erika is available.
Full-game completion is not verified.

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
Other battle items are prohibited.
Healing uses Pokémon Centers or Mom.
The agent can clear a necessary obstacle on the route to healing.
It must check the required move and permission, then check the result.
The controller records Rare Candy grants and use during preparation.
A recorded death remains permanent after healing or evolution.

Navigation uses observed terrain and reference maps.
Observed movement has priority over reference maps.
Walkthrough fragments supply guidance for the current stage.
Before Lt. Surge, the agent must use CUT and enter the gym.
A learned move does not confirm that the path is open.
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
