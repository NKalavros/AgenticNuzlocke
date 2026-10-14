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

6. **Inside Vermilion Gym:** keep two separate objectives: open the switch locks, then challenge Lt. Surge. When the controller supplies a **RAM assist** objective, follow its indicated can. It reads the active switch again after the first lock opens; do not substitute a random neighbor. Once both locks are reported open, stop searching cans and verify the barrier passage. Without assistance, search trash cans for the first switch and record its tile. After the first-switch confirmation, test an orthogonally adjacent can for the second; a diagonal can is not adjacent. Vanilla Red has a bug that can put the second switch in can 0 at (1,7) even when it is not adjacent; adjacency is not a guarantee for every Red-family ROM. A wrong second choice resets both locks: clear the remembered first-switch state and search again. Read each result before choosing the next can. Only the observed open barrier or successful crossing completes the puzzle. The controller inserts mandatory healing and preparation before the challenge: visit Vermilion Center, stand at (3,3) facing up across the nurse counter, accept HEAL/YES, and verify HP/status/PP recovery. It grants the exact audited Rare Candy deficit and uses normal menus to bring living members to the current cap (normally 24). Return to the gym, clear the respawned CUT tree if needed, verify the open barrier passage, then approach Surge from (5,2) facing up. Use observed enemy data. Finish the victory dialog and verify Thunder before advancing to Erika.

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

## 11. Koga — Rocket Hideout, Pokémon Tower, Fuchsia

After the observed Rainbow Badge, work toward Koga and the Soul Badge. Use inventory evidence to skip completed errands. The normal land route needs the Poké Flute to pass Snorlax. Obtain the Silph Scope in Celadon, rescue Mr. Fuji in Lavender, then travel through Routes 12–15 to Fuchsia. If already in Fuchsia or beyond Snorlax, continue from that observed location instead of returning for keys. Healing, death storage, supplies and the controller's encounter rules retain priority. Do not start Silph Co., Sabrina, sea travel or a Safari Zone errand for this chapter.

### Celadon: open the Rocket Hideout

Leave Erika's gym through its south door and heal at Celadon Center `(41,9)` → 133. After the controller reports full living HP/status/observed PP recovery and text is closed, continue to the Game Corner; use the supplied recovery facts without opening STATS to recheck them. Finish any mandatory nurse stage first. Trees can return after reentry; use the actual living CUT user's menu from the adjacent tile and verify the passage. Enter the Game Corner `(28,19)` → 135. Defeat the Rocket guarding the north-wall poster at `(9,5)`, then stand `(9,5)`, face up and press A at the poster `(9,4)`. This switch reveals the stairs `(17,4)` → Rocket Hideout B1F (199). If the stairs are already open, use them without repeating the poster battle. Slots, the Coin Case and prizes are not prerequisites. Aim for a reachable approach tile first if an interaction route is incomplete.

### Rocket Hideout: obtain the Lift Key

The stairs route is B1F (199) `(23,2)` → B2F (200); B2F `(21,8)` → B3F (201); B3F `(19,18)` → B4F (202). Coordinates refer to the current map and distinguish repeated stairs. Arrow floor tiles automatically slide the player until a stop tile. Send wait frames while sliding; do not assume one input gives one tile or turn a slide into a permanent wall. Use small current-map route waypoints to approach a chosen arrow/stop tile, observe its landing, then plan the next segment. An inaccessible reference path is advisory, not permission to walk through a wall.

On B4F's northwest side, defeat the Rocket `(11,2)`. **Talk to him again after the battle** to reveal the Lift Key at `(10,2)`; face the labeled item from an adjacent legal tile and pick it up. Verify positive Lift Key quantity in the bag before leaving. An absent item is not proof of collection. Leave bag space for this key and the later Silph Scope; use a Center PC to store optional non-key items if necessary. Return via B4F `(19,10)` → B3F, then `(25,6)` → B2F. The Lift Key opens elevator use; it does not itself reveal the Silph Scope.

### Rocket Hideout: obtain the Silph Scope

With the observed Lift Key, reach the elevator at B2F `(24,19)` / `(25,19)` → 203 through the arrow maze. In the elevator, face the panel `(1,1)` from an adjacent tile, press A and choose **B4F** from the visible floor list. The door then leads to B4F's eastern area. Defeat both doorway Rockets `(23,12)` and `(26,12)` to open the barrier. Approach Giovanni `(25,3)` and fight him with healthy legal members. Vanilla prior: Onix 25, Rhyhorn 24, Kangaskhan 29; actual enemy data overrides it. Grass/Water help against his Rock/Ground pair, but Kangaskhan needs a separate plan. No battle healing items.

After Giovanni leaves, pick up the revealed Silph Scope `(25,2)` and verify it in inventory. Do not confuse victory, the Lift Key, or the closed barrier with possession. Return to the elevator, select **B1F**, and exit B1F `(21,2)` → Game Corner, then the south door → Celadon. Heal before Lavender. If outside the hideout with the key but no Scope, reenter the already opened Game Corner stairs and return to the elevator.

### Lavender: rescue Mr. Fuji and receive the Poké Flute

Use the complete observed inventory supplied in constraints, including off-screen bag entries. A positive Silph Scope quantity with no Poké Flute means the rescue is unfinished; do not reopen PACK just to recheck it.

With the observed Silph Scope and no Poké Flute, leave Celadon EAST to Route 7 (18). Use its Underground Path building `(5,13)` → 77, descend to tunnel 121, travel EAST to stairs `(47,2)` → 80, exit to Route 8 (19), then go EAST to Lavender (4). Use this bypass; no Saffron guard errand is needed. Heal at Lavender Center `(3,5)` → 141, then enter Pokémon Tower `(14,5)` → 142. Expect the rival on 2F; heal first and trust observed teams.

Ascending stairs: 1F `(18,9)` → 143; 2F `(3,9)` → 144; 3F `(18,9)` → 145; 4F `(3,9)` → 146; 5F `(18,9)` → 147; 6F `(9,16)` → 148. Use each current-map destination, not a previous floor's target. Channelers and normal wild encounters obey the live ledger. The scripted level-30 Marowak ghost guarding 6F's last stairs cannot be caught; defeat it after the Silph Scope reveals it. Do not spend capture balls on this story ghost. Heal at the Center as needed; do not assume a healing-looking tile is an allowed substitute.

On 7F, defeat the three Rockets and speak to Mr. Fuji `(10,3)`. Finish his dialog to travel to his house (149). **Speak to Fuji again there** at `(3,1)` to receive the Poké Flute. If the house has no Fuji, the rescue is still unfinished: return to the Tower. Verify positive Poké Flute quantity in the bag. The Scope, arriving at 7F, or the house transfer alone does not finish this stage.

### Land route: Lavender → Routes 12–15 → Fuchsia

With the Poké Flute, return to Lavender by the Route 7/8 Underground Path if still in Celadon. From Lavender go SOUTH to Route 12 (23), through its gate if required. Follow the wooden paths south. At the blocking Snorlax, stand adjacent and use **Poké Flute from ITEM**; interacting with the sleeping sprite alone does not wake it. Resolve the resulting encounter under the current area's ledger, duplicate and survival rules, then verify the passage. Do not force a capture if that area's encounter is already committed. Keep the Flute after use.

Continue SOUTH from Route 12 to Route 13 (24), WEST to Route 14 (25), WEST to Route 15 (26), then WEST through the Route 15 gate (184) to Fuchsia (7). Route 14's western opening is toward its south end; follow the live map's connection alignment and avoid repeating a blocked edge at the wrong height. Route 15's main lane and gate work without the optional upper CUT shortcut. Heal for poison, low HP or exhausted PP; complete legal encounters and reachable labeled pickups while respecting higher-priority safety. This eastern route does not need a Bicycle. If already on Cycling Road with a Bicycle and the passage open, continue through Routes 17/18 to Fuchsia instead of returning east.

### Fuchsia: Center and gym access

In Fuchsia (7), heal at the southern Center `(19,27)` → 154. Keep capture balls and bag space available. The gym entrance is southwest at `(5,27)` → 157. Enter the gym and clear its invisible-wall maze; there is no trash-can switch puzzle here. Koga is the next badge goal. Do not leave for Safari Zone, Gold Teeth, the Warden, Silph Co. or a sea route. Arrival in Fuchsia starts the controller's persistent full nurse visit and audited level-43 preparation. Finish these stages at the Center before entering the maze's trainer battles; then follow the challenge objective to Koga.

### Koga: invisible walls and the Soul Badge

Fuchsia Gym (157) has invisible walls that can resemble open floor. From the southern entrance, the vanilla approach goes up the RIGHT outside corridor, across the TOP, then down the LEFT corridor into the center. Follow reference collision geometry, current terrain and observed blocked edges; a floor-colored tile or an old visit does not prove a passage. Use reachable current-map waypoints to approach the next bend. The trainers include Psychic attackers as well as Poison users; do not assume every trainer is weak to Psychic or bring a Poison lead into an observed Psychic threat. Heal between fights when required.

Koga stands at `(4,10)`; approach from `(4,11)` facing UP. Arrival in Fuchsia starts the persistent **heal → prepare → challenge** sequence before the maze trainers. Return to Fuchsia Center, accept the nurse, verify full living HP/status/observed PP and closed text, then use audited candies through normal menus to the current **43** cap. Do not initiate Koga before preparation is complete. Retrace the maze after healing; return damage can require another nurse visit.

Vanilla team: Koffing 37, Muk 39, Koffing 37, Weezing 43. Psychic or Ground attacks may help if the actual living roster knows them; Gen I Koffing/Weezing have no Levitate ability. Plan for poison/Toxic, accuracy loss and self-destructing foes using observed moves and HP; keep a safe legal switch and obey System 2's conditional trainer plan. Finish victory/reward dialog and verify the **Soul Badge**, not merely a trainer win or a conversation. Stop when `stop_after: koga` is configured.

Choose one machine target on the current map and verify the result before changing floors or selecting the next leg. Inventory, badges, learned moves and committed encounter outcomes establish progress; planner prose cannot. Vanilla coordinates and teams are priors. Red Star's screenshot, live objects, observed collision and enemy data take precedence.

Sources: [map objects](https://github.com/pret/pokered/tree/master/data/maps/objects), [Rocket key and Scope script](https://github.com/pret/pokered/blob/master/scripts/RocketHideoutB4F.asm), [Fuji reward script](https://github.com/pret/pokered/blob/master/scripts/MrFujisHouse.asm), [route connections](https://github.com/pret/pokered/tree/master/data/maps/headers), and [trainer teams](https://github.com/pret/pokered/blob/master/data/trainers/parties.asm).

## Surf: observed HM03, teaching still required

HM03 is observed in the bag, but no living party member is observed with SURF. Use ITEM → HM03 → USE, accept teaching, and select a living member marked **ABLE** in the visible compatibility list. Do not guess compatibility from vanilla species. If replacement is required, preserve needed field moves and the planner's move bans. Verify learned SURF in the party observation; a successful-looking text page alone is insufficient. This guidance does not add a new destination or release mandatory healing/preparation. Before field use, require the observed Soul Badge and a living user. Keep the Koga route as the main objective until Soul is earned.

## Surf: learned, field permission still locked

A living party member has SURF, but the Soul Badge is not observed. It can be a legal battle move; field use on water remains locked. Continue the current Koga objective and earn Soul before trying to cross water. A learned move and a visible water tile do not establish field permission.

## Surf: observed living user and Soul Badge

A living party member is observed with SURF and Soul is earned. For a water crossing required by the current objective, approach a reachable land tile adjacent to actual water and face the water. Open START → POKéMON → the living SURF user → SURF; accept a visible confirmation if asked. Verify the scene changes to surfing and the position enters water before targeting a farther water exit. Ordinary walking into water does not activate the move. Advance transitions with wait frames; if use fails, recheck the user, badge, facing and terrain. Landing on a reachable shore ends surfing; verify the mode and reobserve the map. Keep the existing destination and safety/encounter rules. This is conditional field guidance, not an instruction to start a new sea journey.

Source: [field-move menu and Soul Badge gate](https://github.com/pret/pokered/blob/master/engine/menus/start_sub_menus.asm).

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

## Team preparation and PC storage

Use the complete owned roster, permanent death ledger, current cap, actual moves, and the relevant trainer reference. A reference team is a prior; Red Star can differ. Preserve a living user of each currently available HM. A dead Pokémon must be stored and cannot fight, even if a nurse restores its displayed HP.

At a Pokémon Center, approach the PC at `(13,4)` facing up. Choose BILL's PC or SOMEONE's PC. DEPOSIT moves a party member into the active box; WITHDRAW appends a boxed member to the party. Select the intended nickname, then confirm DEPOSIT/WITHDRAW in its submenu. The list scrolls beyond the visible rows. CHANGE BOX asks to save before selecting another box. Keep at least one legal survivor in the party, keep space for withdrawals, and verify each transfer by capture identity. Do not use RELEASE. Leave all PC menus before healing or training.

Heal the selected party, then use audited Rare Candies through the normal bag and party menus. A target must not exceed the current cap. Allow evolution. During a move offer, use the planned replacement only when the displayed Pokémon and move agree. Keep HMs. For a TM/HM, check the displayed ABLE list; an incompatible request needs a new plan, not repeated menu attempts. Verify the final team, levels, moves and lead before returning to the challenge.

For Koga, compare a trained Drowzee/Hypno's actual Psychic attacks with the legal alternatives. Geodude's Rock typing can help against Selfdestruct, but a switch takes a turn. Do not assume a reference range guarantees survival: accuracy changes, critical hits, Toxic and undocumented Red Star moves remain risks. Gen I has no abilities. Use the Koga fragment for the trainer team and approach. Keep experience headroom if maze trainers remain.

## Nuzlocke reminders

- Dupes / first encounter / faint = dead — follow referee rules.
- No trainer battle items; only legal capture balls in wild battles. Audited Rare Candies are an outside-battle preparation exception.
- Dead Pokémon stay dead after healing; use Center PC deposit menus. A wipe ends the run.
- When unsure, prefer healing and safer routes over risky grass.
