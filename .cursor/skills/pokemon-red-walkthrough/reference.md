# Pokemon Red / Red-Star — agent walkthrough (early game)

Route through Brock and the continuation toward Misty for the current three-system runner. **Red Star** keeps the same early beats but art/layouts can differ — trust the screenshot. System 3's current constraints and code objectives take priority over this guide; System 1 handles paths and menus.

## 0. Title / NEW GAME

- Title → wait and `press_start` until menus.
- NEW GAME → confirm.
- Intro Oak text → `skip_dialog`; stop when a prompt or naming menu appears.
- YOUR NAME / RIVAL NAME lists are menus. On the actual letter grid, `press_start` finishes the name. Do not treat it as a town or infer naming solely from RAM bit 6.

## 1. Red’s House 2F (bedroom)

Goal: reach **1F** via the **stairs**, not by “walking outside.”

- Stairs are a **floor warp tile** (often near a corner of the room), not the TV/plant/PC.
- If walks bounce or the screen looks like outdoors after going up, you likely misread furniture — try other walkable tiles systematically (left/right along the walkable row, then step onto stairs).
- After stairs: you should see Mom / living room (1F).

## 2. Red’s House 1F

- Optional: talk to Mom.
- Exit via the **south door** to Pallet Town (walk down onto the door mat / doorway).
- If `walk_down` on the mat **noops**, you are one tile off — sidestep onto the mat, then down. Do not walk north back into the house immediately after exiting.
- If you go back upstairs by mistake, reverse via the stairs.

## 3. Pallet Town

- Houses north; **Oak’s Lab** is the large building toward the south/center.
- North fence: if `walk_up` noops you are on a **post**. One tile left or right, then up. The exit is a vertical grass lane, not “walk north harder.”
- Walking onto **Route 1** (north grass) with **no Pokémon** triggers Oak; he walks you to the lab — page dialog with `skip_dialog`, and let explicit wait actions advance the escort.
- Enter Oak’s Lab through its door.

## 4. Oak’s Lab — starter

- The ball table is **two tiles tall**. Face a remaining ball from the **south**; empty table tiles and Oak’s sprite are noops.
- Read the displayed species, then accept **Bulbasaur**. Decline other species and approach another ball. B at YES/NO means NO.
- Nicknames are optional; the automated answer is NO. Preparation code configures SET and uses audited candies through normal menus to bring healthy lone Bulbasaur to level 8 before the rival.
- Rival picks the type-advantaged starter → short rival battle.
- System 2 supplies a trainer battle plan; System 1 chooses legal moves or switches using the active Pokémon, HP, PP, and the plan. Do not substitute blind A presses for battle decisions.
- Returning with Oak’s Parcel: talk to **Oak at the back of the room**, not the side aide (“trainers hold him in high regard”).

## 5. After starter — Viridian parcel loop

Typical order:

1. Leave lab → Pallet → Route 1 north (now legal).
2. Reach **Viridian City**; visit Pokémon Mart — clerk asks you to deliver Oak’s Parcel.
3. Return to Oak’s Lab with the parcel → talk to **Oak** (back of lab), not the aide → receive **Pokédex** / Poké Balls (hack may vary rewards).
4. Heal at Viridian Pokémon Center; preparation code brings the healthy party to level 12. After the Pokédex, buy Poké Balls at the Mart when needed.

## 6. Route 1 / Viridian Forest approach

- Once balls have ever been acquired, the referee freezes the **first eligible** wild encounter per area (Mt. Moon floors share one slot). Ever-owned evolution families reroll, including dead Pokémon's families. Follow System 3's catch/flee choice.
- Ledges: northbound must find the **gap**; `walk_up` into a ledge noops. Southbound can jump down.
- Viridian south entrance: a **one-tile gap** in the fence. Left/right wiggle without a single `walk_up` through the opening is the jam — sidestep onto the gap, then up.
- Use the configured preparation workflow. Non-capture wild battles are fled when candy preparation is enabled. Code searches Route 1, Route 22, Route 2, and Forest grass until the legal encounter is resolved. Duplicate-only ROM tables defer a slot without consuming it; a timeout never counts as completion.
- Road to Pewter: Viridian → Route 2 → Viridian Forest → Pewter.

## 7. Pewter / Brock

- Prepare the living party to level 14 at Pewter Center through normal candy menus. Enter the gym with full HP, healthy status, and restored observed PP; return to heal after the junior trainer.
- Brock's cap is 14 at battle entry. Levels earned during a legal battle are allowed; eligibility is checked again for the next battle. Use the actual enemy on screen and System 2's trainer plan.
- With the Boulder Badge, restock balls, heal, and prepare to level 18. Backtrack for unfinished earlier encounters, then head east onto Route 3. The run now targets Misty (`stop_after: misty`).

## 8. Route 3 / Mt. Moon / Cerulean

- Route 3 connects NORTH to western Route 4, at boundary tiles `(57..61, 0)` in the vanilla layout. It has no east connection. Use `navigation.reference_map.desired_exit` and the full reference layout; do not search the east wall or rediscover known exits. Live movement and map tables override mismatches in the vanilla reference.
- Resolve Route 3 before entering Mt. Moon. Western Route 4 has no reachable grass; its encounter waits until the eastern side after the cave.
- Mt. Moon has one encounter across all three floors. Use the current ROM's land table and reachable cave floor; do not seek a second catch downstairs.
- Vanilla route hints: 1F northwest ladder (5,5), B1F ladder (17,11), cross the main B2F room past the trainers/fossils to (5,7), then leave the separate B1F exit passage. These coordinates must match visible/observed warps; Red Star may differ.
- Cave floors can be separated by impassable elevation boundaries even when both cells read as floor. Use `terrain_blocked_edges` as well as tiles. Ladders sharing a destination map can belong to disconnected chambers: for healing from the main B2F area, use the reachable ladder `(21,17)` and then the B1F corridor to `(5,5)`; do not try to cross the boundary toward the isolated B2F ladder `(25,9)`.
- At the blocking fossil choice, select one fossil so the passage opens. Do not return to side chambers repeatedly.
- On Route 4, the eastern Mt. Moon exit is at (24,5). Continue east from that apron; do not return to the western cave entrance. Reach the eastern grass using `reference_map.ledge_jumps`: launch → landing is one way, so do not attempt to climb a drop in reverse. The measured (64,8) → (64,10) drop enters the grass.
- Resolve eastern Route 4 before Cerulean. Prepare at Cerulean Center to 19 (below the reserve band for Misty’s level-21 cap), resolve Route 24 and Route 25 through the northern bridge, then return to heal for the gym. The bridge rival is a trainer battle: System 2 plans it.
- Stop at the Cascade Badge. This extension is under live validation; full-game completion remains unverified.

## Stuck cheatsheet

| Screen looks like… | Do this |
|--------------------|---------|
| Letter grid | `press_start` to finish naming |
| Ordinary text box | `skip_dialog`; stop at prompts/menus |
| Evolution / level-up stats | Wait without B / close stats with A |
| Bedroom, can’t leave | Find stairs tile; don’t spam only up/down |
| Living room | Walk south out the door |
| Pallet, walk_up noops | On a fence post — one tile left or right, then up |
| Lab, A noops on table | Table is 2 tiles tall; face a ball from the south |
| Lab, aide chatter | Parcel goes to Oak at the back, not the side NPC |
| Route 1 ledge / Viridian fence | Find the one-tile gap; do not wiggle left-right |
| Oscillating indoors/outdoors | Stop; pick a new column; consult memory |

## Nuzlocke reminders

- Dupes / first encounter / faint = dead — follow referee rules.
- No trainer battle items; only legal capture balls in wild battles. Audited Rare Candies are an outside-battle preparation exception.
- Dead Pokémon stay dead after healing; use Center PC deposit menus. A wipe ends the run.
- When unsure, prefer healing and safer routes over risky grass.
