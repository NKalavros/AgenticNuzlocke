> **Historical design proposal.** For implemented behavior and commands, use [README.md](README.md) and [AGENTS.md](AGENTS.md); measured results are in [docs/validation.md](docs/validation.md). The current runner uses three systems and targets Brock. Separate specialist agents, a damage-calculation service, and FireRed below describe future scope.

## Recommendation

The original proposal was to start with **Pokémon Red** using Nous Research's `pokemon-agent`, then explore a FireRed adapter through mGBA. Its main architectural ideas were:

* **One Qwen server, multiple role prompts—not four agents simultaneously pressing buttons.**
* A deterministic **Nuzlocke Referee** and **Action Arbiter** between every agent and the emulator.
* Separate **Encounter Agent**, because encounter legality and capture strategy are distinct from normal battling.
* Privileged RAM may enforce rules, but gameplay agents receive only human-equivalent information.
* Rare candies are injected into inventory and used through normal menus—never by directly changing levels.
* Save states are for crash recovery only, with hash-chained irreversible events preventing death rollback.
* Team and Battle agents use the generation-aware `@smogon/calc`, which exposes programmatic damage rolls and ranges for each generation. ([GitHub][3])([GitHub][3]) The proposed default rules encode permanent death, first eligible encounter, level caps, and the optional Rare Candy Clause. ([Bulbapedia][4])

The multi-agent structure is also consistent with recent Pokémon-agent research emphasizing modular orchestration for long-horizon RPG play. ([arXiv][5])

## Retained design

The [standalone design document](AGENT_READY_PLAN.md) retains the original architecture, proposed contracts, and specialist-agent roles. The old generated ZIP and sandbox download links are not repository artifacts.

The current implementation uses the three-system approach described in [README.md](README.md). RAM-derived observations support deterministic controls and the referee; the default vision planner receives screenshots and contextual briefings without raw RAM JSON.

[1]: https://github.com/NousResearch/pokemon-agent/blob/main/README.md "pokemon-agent/README.md at main · NousResearch/pokemon-agent · GitHub"
[2]: https://mgba.io/2022/05/29/scripting/ "https://mgba.io/2022/05/29/scripting/"
[3]: https://github.com/smogon/damage-calc "https://github.com/smogon/damage-calc"
[4]: https://bulbapedia.bulbagarden.net/wiki/Nuzlocke_Challenge "https://bulbapedia.bulbagarden.net/wiki/Nuzlocke_Challenge"
[5]: https://arxiv.org/abs/2603.15563 "https://arxiv.org/abs/2603.15563"

