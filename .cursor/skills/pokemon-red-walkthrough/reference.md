# Pokemon Red / Red-Star — agent walkthrough through Erika

Route through Brock and Misty, with planner guidance through Lt. Surge and Erika. **Red Star** can change layouts and teams — trust the screenshot and live battle data. System 3's current constraints and code objectives take priority over this guide; System 1 handles paths and menus. Later routes are guidance, not a claim of completed live validation.

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
- Stop at the Cascade Badge only when configured to do so. For a continuation after Cascade, follow the Lt. Surge prerequisites below. Full-game completion remains unverified.

## 9. Lt. Surge — Bill, Underground Path, S.S. Anne, CUT

Use only after Cascade and before Thunder. Follow the next unmet prerequisite; do not repeat a completed stage. System 3 safety, encounters and legal actions take priority. These are vanilla route hints: verify doors, objects and terrain on Red Star before using coordinates.

1. **No S.S. Ticket / HM01 / learned CUT: visit Bill first.** Leave the gym, go NORTH from Cerulean over Nugget Bridge onto Route 24, then EAST onto Route 25. Follow the trainer path to Bill's cottage at the far eastern end (vanilla door `(45,3)`, destination map 88). A resolved Route 25 encounter does NOT mean Bill was helped. Inside, speak to the creature/Bill, answer YES, let him enter the machine, use his PC to run the separation, then speak to the restored human Bill for the **S.S. Ticket**. Verify receipt; talking once or entering the house is insufficient.

2. **Ticket obtained: return to Cerulean.** Enter the robbed house in the northeast (front door `(27,11)`, destination 62). Exit via its broken BACK wall (interior warp `(3,0)`), defeat the Rocket outside, finish the TM28 receipt, then follow the eastern path SOUTH toward Route 5. Do not keep circling the southern buildings or walking into the CUT tree from the central city. If the officer still blocks the front door, finish Bill's ticket conversation first.

3. **Route 5 → Vermilion:** use the small Underground Path building on the eastern side (vanilla door `(17,27)`, destination 71), descend, traverse the north-south tunnel, ascend at the Route 6 end, then head south through Route 6 to Vermilion. The central Saffron gate is blocked by a thirsty guard; it is not the route for this objective.

4. **No HM01 yet:** heal, then board the S.S. Anne from Vermilion's southern dock using the ticket. Find the stairs to 2F and the captain's corridor, prepare for the rival battle, then talk to the captain to obtain **HM01 CUT**. Verify receipt before leaving. The ship departs after obtaining CUT and exiting, so do not leave required ship work unfinished.

5. **HM01 held, CUT not learned:** use HM01 from the bag on a compatible living party member. Trust the visible ABLE/NOT ABLE menu over vanilla compatibility guesses. Verify CUT in that member's observed moves before closing teaching menus. Owning HM01 or selecting USE does not complete teaching. Next, approach and clear the tree at Vermilion Gym using the separate gym-access objectives. Cascade permits field CUT.

### Gym access: CUT learned does not mean the entrance is open

Complete these objectives in order, using current observations. Safety and healing still take priority.

1. **Approach the blocking tree.** If outside Vermilion, return there. In Vermilion, first reach the accessible side of the gym tree, not the gym door behind it. The verified Red Star approach is map 5, tile `(14,18)`, facing RIGHT toward the tree at `(15,18)` (tile ID `0x3D` before CUT). The gym door is `(12,19)`. Use a current-map tile target for the approach, or a reachable screenshot cell toward it if absolute tile targets are unavailable. A gym-exit goal cannot walk through this obstacle. The southern dock and S.S. Anne do not provide a route around it. A completed approach means the observed player is beside the tree, not that the gym is accessible.
2. **Use the learned field move.** At the tree, close any teaching menus. Face RIGHT, open START → POKéMON, choose the living member whose observed moves include CUT, then choose CUT from its field menu. Name that member and CUT in the plan so System 1 can select the menu rows. Use a buttons-only target with short steps to open START or set facing when needed; do not keep an active walking target while opening the field menu. Do not reopen HM01 or select a Pokémon merely because an earlier plan named it. Ordinary A interaction is not proof that CUT was used.
3. **Verify and enter.** Read the CUT result and confirm the tree disappears or its tile becomes traversable. If CUT reports failure, check adjacency, facing, learned move and badge; revise that subgoal instead of walking around town. Only then target the gym exit (map 92). If the entrance is already visibly open, enter directly. Trees can return after leaving the map, so check the current obstacle rather than treating a past CUT action as permanent evidence.
4. **Inside the gym.** Only an observed transition into Vermilion Gym completes the entrance objective. Then use the switch-puzzle guidance. Only the observed Thunder Badge completes Surge; a claimed win or an open entrance does not start the Erika route.

Keep the current subgoal until its evidence is observed. A failed path is a reason to inspect the blocker, not permission to replace the objective with arbitrary exploration. If the picture is blank or unreadable, report that uncertainty, wait for a settled view or use the observed map to approach a known landmark; do not call it a naming screen without a visible letter grid.

6. **Inside Vermilion Gym:** keep two separate objectives: open the switch locks, then challenge Lt. Surge. Search trash cans for the first switch and record its tile. After the first-switch confirmation, test an orthogonally adjacent can for the second; a diagonal can is not adjacent. A wrong second choice resets both locks: clear the remembered first-switch state and search again. Read each result before choosing the next can. Only the observed open barrier or successful crossing completes the puzzle. Heal before challenging Surge; use the controller's current cap (normally 24) and observed enemy data. Do not invent a candy grant at an unsupported location or assume the later-gym preparation menus are automated. Finish the victory dialog and verify Thunder before advancing to Erika.

Cerulean → Route 24 is a NORTH map edge: use `{"kind":"edge","dir":"up"}`, not a warp to map 35. Route 24 → Route 25 is an EAST edge: use `{"kind":"edge","dir":"right"}`. Doors use `kind: warp` with the observed destination map.

Return one concrete current-map objective at a time: the Route 24 edge, Bill's house door/NPC, the robbed-house front/back warp, Underground Path entrance, captain, or gym. On a blocked route, reconsider the prerequisite or doorway instead of repeatedly reissuing a generic south-edge goal. Use explicit menu steps only where System 1 cannot execute the task itself.

Useful vanilla landmarks (verify against current objects): Vermilion Center `(11,3)` → map 89; dock `(18/19,31)` → 94; gym `(12,19)` → 92. S.S. Anne 1F stairs `(2,6)` → 96, then 2F captain stairs `(36,4)` → 101. The rival blocks that corridor; heal before entering it. With Bulbasaur as the starter, expect Pidgeotto 19, Raticate 16, Kadabra 18 and Charmeleon 20, subject to live correction. The captain is at `(4,2)`. Do not confuse room doors with deck stairs.

Surge's vanilla team is Voltorb 21, Pikachu 18, Raichu 24. Avoid exposing Flying/Water members to Electric attacks; a living legal Ground type is immune to Electric damage, but must still withstand other moves. Use observed moves and structured battle plans, not a type-only guarantee. The gym trainers include Pikachu 23, two Pikachu 21, and Voltorb/Magnemite/Voltorb 20. Finish the post-battle badge dialog and verify **Thunder** before switching to the Erika route.

## 10. Erika — CUT, Rock Tunnel, Lavender, Celadon

After Thunder and before Rainbow, follow the current location along this route. Keep a living compatible **CUT** user. If none knows it, use held HM01 through the bag and verify the learned move. Do not discard or overwrite needed attacks casually; HM moves cannot be forgotten normally in Red. Center healing restores HP/status/PP but never reverses a ledger death. Later-gym candy top-ups are not automated: use only preparation explicitly allowed by the controller, and never assume a level grant occurred.

1. **Vermilion → Cerulean:** heal, leave north to Route 6, enter its Underground Path building (map 74), take the north-south tunnel (119) to Route 5's building (71), leave and go north to Cerulean. Saffron's guards still block the direct gates. Do not head east along Route 11 toward the sleeping Snorlax as the route to Lavender.

2. **FLASH is helpful, not a story requirement.** If already learned, use it from the party menu inside Rock Tunnel; Boulder enables field FLASH. HM05 is available from Oak's aide in Route 2's gate (49) after **10 owned species**, not 10 seen or 10 party slots. Optional detour: Vermilion east → Route 11's Diglett's Cave entrance (85) → cave (197) → Route 2 entrance (46); follow the eastern Route 2 strip south, using CUT as needed, to the gate. Speak to the aide, verify HM05, and teach it to a compatible living member. Respect first-encounter and duplicate rules; do not catch illegal extras to meet the count. If unavailable, proceed without it using reference geometry and verified movement, with short goals; do not loop endlessly asking the aide or claim the cave is lit. Return through Diglett's Cave/Underground Path to Cerulean after the detour.

3. **Cerulean → Route 9 → northern Route 10:** use CUT on the eastern exit tree, then the EAST edge to Route 9 (20). Follow the passable eastbound path; ledges are one way and trainer sight can interrupt. Route 9's EAST edge leads to Route 10 (21). Heal at the northern Center `(11,19)` → 81, then enter Rock Tunnel `(8,17)` → 82. The southern cave door `(8,53)` is on a disconnected region and cannot be reached by walking through the mountain outside.

4. **Rock Tunnel (1F 82 / B1F 232):** use FLASH if available. Both floors share one encounter slot. Record each ladder's coordinates and arrival chamber; repeated destination IDs are not interchangeable. Use the reachable onward ladder, not simply the nearest ladder back to the entrance. Vanilla forward sequence from the north entrance: 1F `(37,3)` → B1F `(33,25)`; cross to B1F `(27,3)` → 1F `(5,3)`; cross to 1F `(17,11)` → B1F `(23,11)`; cross to B1F `(3,3)` → 1F `(37,17)`; cross the final chamber to the southern exit `(15,33/35)`. Check the reference route and live geometry at each leg. Trainers and status/PP attrition matter; backtrack along the recorded sequence for healing when necessary, rather than pushing an unsafe battle. Do not walk blindly through a dark screenshot or assume RAM walkability overrides a bump.

5. **Southern Route 10 → Lavender:** after the south exit, head SOUTH to Lavender (4), heal at its Center (141), then leave WEST onto Route 8 (19). Pokémon Tower, the ghost, the Poké Flute and Rocket Hideout are not prerequisites for Erika; do not get diverted into them.

6. **Route 8 → Celadon:** travel west along Route 8 to the Underground Path building `(13,3)` → 80, not the Saffron gate. Descend into the east-west tunnel (121), go WEST to its Route 7 stairs `(2,5)` → 77, exit onto Route 7 (18), then take the WEST edge to Celadon (6). This is a different tunnel from the north-south Route 5/6 passage. No drink/Tea errand is required for this bypass; Tea belongs to the remakes, not vanilla Red.

7. **Celadon preparation and gym:** heal at the northeast Center `(41,9)` → 133. Keep balls and bag space available; collect reachable labeled items without dropping required key items. Department-store shopping, Eevee, Fly, Game Corner and Rocket Hideout are optional, not Erika prerequisites. Use CUT to access the southwest gym at `(12,27)` → 134. Inside, navigate around hedges, use CUT at the required tree, and approach Erika in the north-center at `(4,3)` from a reachable adjacent tile. Expect trainers on the approach; heal between fights if needed. Do not reuse Surge's trash-can puzzle here.

8. **Erika battle:** obey the current cap (normally **29**). Vanilla team: Victreebel 29, Tangela 24, Vileplume 29. Flying, Fire or Psychic attacks may help depending on the actual species/moves; Grass resists Water/Electric/Grass. Account for sleep, poison, paralysis and trapping moves; preserve PP and choose healthy legal members. Use System 2's conditional battle plan and System 1's legal choices, with no battle healing items. After victory, finish the reward dialog and verify the **Rainbow Badge**. Stop here when `stop_after: erika` is configured; do not infer victory merely from speaking to her or defeating a junior trainer.

At every stage, healing/status/PP needs and permanent-death restrictions outrank travel. If code has no healing route for a later map, the director must explicitly route to the named Center using observed exits. Choose one current-map machine target (`edge`, `warp` with coordinates when ladders repeat, `npc`, or a verified interaction tile) and verify its outcome before the next leg. Actual enemy data and visible scene changes override this vanilla guide.

Sources: [pret/pokered map objects](https://github.com/pret/pokered/tree/master/data/maps/objects), [map connections](https://github.com/pret/pokered/tree/master/data/maps/headers), [trainer teams](https://github.com/pret/pokered/blob/master/data/trainers/parties.asm), [FLASH aide script](https://github.com/pret/pokered/blob/master/scripts/Route2Gate.asm), and [Erika script](https://github.com/pret/pokered/blob/master/scripts/CeladonGym.asm).

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

## Mandatory healing: clear necessary obstacles, then resume the route

The parent objective is **restore the living party at a Pokémon Center or Mom**. Keep that objective active until observed HP, status and PP satisfy the controller. Entering a city, clearing an obstacle, or claiming success does not complete healing. Defer badges, optional items, encounter searches and training until healing is complete. Do not use healing items or bypass Nuzlocke rules.

You may set temporary route or field-move subgoals needed to reach care. The controller's Center/exit target is the destination, not a demand to keep walking into a blocker. When the full walking route is blocked, inspect the current screen and observed geometry. Approach a reachable side of the obstacle, perform the supported interaction, verify the result, then continue toward the healing destination. Do not repeatedly target an unreachable Center door or wander around the same enclosed area.

Use CUT for a cuttable tree, Strength for a movable boulder, or Rock Smash for a breakable rock **only if that mechanic exists in this ROM and its prerequisites are observed**. Check that a living, usable party member actually knows the move and that any required badge or field permission is present. HM ownership alone is insufficient. Do not invent Rock Smash support, a missing move, or an unlocked field ability. If the action is unavailable, seek a different safe route; if none exists, report the exact blocker instead of claiming it is clear. Do not start a new badge or HM-acquisition quest while healing is mandatory.

Choose one concrete subgoal at a time:

- Approach a reachable tile adjacent to the obstacle, using a current-map tile target. Confirm adjacency and the required facing. Previous entry coordinates may now be on the inaccessible side.
- Use a buttons-only target to face the obstacle and open START. In POKéMON, select the verified living move user and the actual field-move row. Include the member's name and move in the plan so System 1 can select them. Preserve useful moves; do not reopen the teaching menu for an already learned move.
- For a Strength boulder, inspect the required push and the space beyond it before pushing. Avoid trapping the boulder or blocking the healing exit. Verify the changed position before the next push. Use Rock Smash only on a verified breakable obstacle with an offered action.
- Read the result and verify the tree/rock disappears, the boulder moves, or the crossing becomes traversable. A failed action requires checking facing, adjacency and availability. Resume the healing route after success. For a Center door, use an exit target naming that Center; a floor-tile target is for its approach, not the door warp itself. The controller resumes a fully reachable healing exit automatically.

Obstacles may reset on map transitions. Recheck them when leaving a building or cave. In the tested Vermilion gym enclosure, the tree returns at `(15,18)` after leaving the gym. From the **gym side**, approach `(15,19)` and face **UP**; the earlier town-side approach `(14,18)` facing right is across the obstacle. Cut it using the living learned-CUT user, verify passage, then continue to Vermilion's Center `(11,3)`, destination map 89. Do not go back into the gym or attempt its switches while healing is active. These coordinates are a checked local example; use observed geometry for other obstacles.

Prefer the shortest safe route. Poison can cause fainting during travel, so unnecessary steps are dangerous. If menu or narration is still open, complete that interaction before walking. The existing battle, death, level-cap and final action checks always apply.

## Nuzlocke reminders

- Dupes / first encounter / faint = dead — follow referee rules.
- No trainer battle items; only legal capture balls in wild battles. Audited Rare Candies are an outside-battle preparation exception.
- Dead Pokémon stay dead after healing; use Center PC deposit menus. A wipe ends the run.
- When unsure, prefer healing and safer routes over risky grass.
