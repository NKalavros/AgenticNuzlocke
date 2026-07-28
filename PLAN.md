## Recommendation

Start with **Pokémon Red**, then port the environment adapter to FireRed. Nous Research’s `pokemon-agent` already provides supported Red/Blue emulation, structured state, screenshots, button actions, WebSockets, sessions, and a live dashboard. FireRed is presently marked “Phase 2,” ([GitHub][1])ypted-memory reader still listed as unfinished. ([GitHub][1])([GitHub][1]) FireRed, the proposed second-stage adapter uses mGBA’s scripting capabilities for memory access, button input, save states, screenshots, frame advancement, and callbacks while retaining a visible emulator window. ([mGBA][2])([mGBA][2]) most important architectural choices in the plan are:

* **One Qwen server, multiple role prompts—not four agents simultaneously pressing buttons.**
* A deterministic **Nuzlocke Referee** and **Action Arbiter** between every agent and the emulator.
* Separate **Encounter Agent**, because encounter legality and capture strategy are distinct from normal battling.
* Privileged RAM may enforce rules, but gameplay agents receive only human-equivalent information.
* Rare candies are injected into inventory and used through normal menus—never by directly changing levels.
* Save states are for crash recovery only, with hash-chained irreversible events preventing death rollback.
* Team and Battle agents use the generation-aware `@smogon/calc`, which exposes programmatic damage rolls and ranges for each generation. ([GitHub][3])([GitHub][3])e default rules encode permanent death, first eligible encounter, level caps, and the optional Rare Candy Clause. ([Bulbapedia][4])

The multi-agent structure is also consistent with recent Pokémon-agent research emphasizing modular orchestration for long-horizon RPG play. ([arXiv][5])

## Artifacts

[Download the complete agent-ready blueprint](sandbox:/mnt/data/nuzlocke_runner_blueprint.zip)

[Read the standalone implementation plan](sandbox:/mnt/data/nuzlocke_runner_blueprint/AGENT_READY_PLAN.md)

The bundle contains the architecture diagram, Red and FireRed rulesets, JSON contracts, Pydantic models, and ready-to-use prompts for the Director, Overworld, Encounter, Box, Team, Battle, and Recovery agents.

The first design choice to settle is whether **RAM-derived visible state and collision maps** count as realistic enough, or whether gameplay agents should receive screenshots and visible menu information only.

[1]: https://github.com/NousResearch/pokemon-agent/blob/main/README.md "pokemon-agent/README.md at main · NousResearch/pokemon-agent · GitHub"
[2]: https://mgba.io/2022/05/29/scripting/ "https://mgba.io/2022/05/29/scripting/"
[3]: https://github.com/smogon/damage-calc "https://github.com/smogon/damage-calc"
[4]: https://bulbapedia.bulbagarden.net/wiki/Nuzlocke_Challenge "https://bulbapedia.bulbagarden.net/wiki/Nuzlocke_Challenge"
[5]: https://arxiv.org/abs/2603.15563 "https://arxiv.org/abs/2603.15563"

