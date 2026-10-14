# System 4: team and battle strategy

System 4 owns a persistent team preparation job and conditional battle lines. System 2 keeps the route and progression objective; System 1 executes menus and battles; System 3 and the final arbiter retain all rule authority. No new emulator write or direct storage operation is exposed. The existing audited candy endpoint is the only preparation grant.

## Activation and configuration

`system4.enabled` defaults to `true`. Unspecified provider settings inherit the resolved System 2 configuration, including CLI overrides. Set `system4.provider` and `system4.model`, or `--system4-provider` and `--system4-model`, to select an independent model. It uses a separate provider instance and run-local workspace. Disabling System 4 preserves the existing System 2 battle planner and fixed preparation path.

A recorded death starts one review. During battle, the review can select only surviving, eligible members already in the party. A second review after battle can choose boxed replacements. Wipe termination remains final. Readiness from `GymPreparation` starts reviews for Brock through Koga; the data catalog also marks the Cerulean rival, S.S. Anne rival and Rocket Hideout Giovanni. The catalog uses observed badge, inventory and location evidence. It does not claim every later boss is covered.

The job survives route-card changes and paired checkpoints. Its stages are review, roster, heal, levels, moves and ready. A changed provider or changed team requests a new review. A battle with no applicable legal line requests new lines. Ordinary wild encounters keep the capture policy unless a death has activated immediate recovery. A badge or catalog completion evidence retires the job. A completed death-only rebuild also retires it.

## Roster and execution

For the verified Red Star ROM, `/snapshot` reads the active box from WRAM and inactive boxes from banked SRAM under the action lock. Before the game's first box change, inactive boxes are uninitialized and are treated as empty. Other ROMs return an incomplete roster; team preparation pauses rather than guessing the layout. Box contents include species, nickname, level, moves, PP, trainer ID, DVs and stat experience. Future stats use reference base stats. No new hidden enemy stats, moves, RNG or opponent trainer data are read.

Identity uses evolution family, original trainer and DVs, with an upgrade path for old checkpoints. Ambiguous identities stop transfers. Permanent deaths and observed PP maxima follow the capture ID. Discovering storage contents does not create encounter outcomes.

The PC controller tracks one deposit, withdrawal or box change. It locates visible names in the full active roster, checks submenu ownership and verifies the resulting party and destination box. It closes menus before another transfer. Full boxes require a normal CHANGE BOX/save operation; a lone legal survivor requires a withdrawal before a deposit. RELEASE is never an operation. The transaction is checkpointed and reverified on resume.

Plans preserve currently living HM capabilities and exclude dead or ineligible members. Each member can have its own level target. Candy grants cover the remaining deficit in batches of at most 99; all use remains through normal menus and is audited against that member's target. Teaching uses owned items, level-up references and the visible ABLE list. Rejected compatibility or unavailable post-leveling moves cause a review. The existing move learner protects HMs and verifies replacements. The final review uses achieved levels, moves and lead.

Battle lines select by active capture ID, enemy species, HP threshold, optional enemy status and minimum recipient HP for switches. They retain `BattlePlan` move conditions, bans, allowlists and PP-confirmed openers. System 4 treats `switch_below: 1.0` as an immediate switch, including full HP. Soft experience-reserve preferences yield to these lines; hard cap eligibility, death and capture rules do not. Openers are scoped to an observed enemy epoch and persist through switches and checkpoints. Identical consecutive enemies are distinguished when the prior enemy's zero HP is observed.

## Calculation boundaries

`agents/calculations.py` implements bounded Gen I reference stat and damage estimates: physical/special types, STAB, effectiveness, damage rolls, critical damage, burn, paralysis speed and common multi-hit bounds. It reports unsupported special formulas as unknown. Explosion with overflowing stats is outside the verified bounds. Status, accuracy and damage bounds are separate facts, not win probabilities.

Observed owned stats take priority at their current level. Future stats assume the supplied DVs/effort and vanilla base stats. Enemy projections use documented teams and moves with maximum DVs and zero effort. No stage, screen, confusion, trapping, badge-boost or multi-turn simulator is implemented. Red Star may alter the baseline. Unknown incoming moves are never described as harmless. Twineedle and Double Kick use two-hit bounds; other supported multi-hit attacks use two-to-five-hit bounds. These limits are sent to the strategist with the comparisons.

The source tables derive from [pret/pokered at af519899719f0754965776faac0e836a3b906e6d](https://github.com/pret/pokered/tree/af519899719f0754965776faac0e836a3b906e6d). Team/learnset/TM data and PC guidance remain replaceable game content. The calculation fixture uses 20 cases from [Smogon's Gen I calculator](https://github.com/smogon/damage-calc/blob/master/calc/src/mechanics/gen12.ts), package `@smogon/calc` 0.12.0, installed only in a temporary validation directory. It is not a runtime dependency.

See [validation](validation.md) for private replay evidence and remaining acceptance limits.
