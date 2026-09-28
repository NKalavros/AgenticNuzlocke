# Pokemon Red / Red-Star — agent walkthrough (early game)

Vanilla Red route. **Red Star** keeps the same early beats but art/layouts can differ — trust the screenshot.

## 0. Title / NEW GAME

- Title → `press_a` until menus.
- NEW GAME → confirm.
- Intro Oak text → `hold_b_120` + `press_a` until naming.
- YOUR NAME / RIVAL NAME letter grid: pick letters with A, move cursor to **END** (usually bottom-right), `press_a`. Do not treat the grid as a town.

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
- Walking onto **Route 1** (north grass) with **no Pokémon** triggers Oak; he walks you to the lab — advance dialog (`hold_b_120` + `press_a`), do not fight the cutscene.
- Enter Oak’s Lab through its door.

## 4. Oak’s Lab — starter

- The ball table is **two tiles tall**. Face a remaining ball from the **south**; empty table tiles and Oak’s sprite are noops.
- Confirm starter choice (YES).
- Rival picks the type-advantaged starter → short rival battle.
- Battle: prefer `press_a` (Fight → move); keep it simple for Nuzlocke early.
- Returning with Oak’s Parcel: talk to **Oak at the back of the room**, not the side aide (“trainers hold him in high regard”).

## 5. After starter — Viridian parcel loop

Typical order:

1. Leave lab → Pallet → Route 1 north (now legal).
2. Reach **Viridian City**; visit Pokémon Mart — clerk asks you to deliver Oak’s Parcel.
3. Return to Oak’s Lab with the parcel → talk to **Oak** (back of lab), not the aide → receive **Pokédex** / Poké Balls (hack may vary rewards).
4. Heal at Viridian Pokémon Center as needed.

## 6. Route 1 / Viridian Forest approach

- First route encounter: for Nuzlocke, catch the **first eligible** wild (one per area rules).
- Ledges: northbound must find the **gap**; `walk_up` into a ledge noops. Southbound can jump down.
- Viridian south entrance: a **one-tile gap** in the fence. Left/right wiggle without a single `walk_up` through the opening is the jam — sidestep onto the gap, then up.
- Train lightly; avoid unnecessary trainer fights until ready.
- Road to Pewter: Viridian → Route 2 → Viridian Forest → Pewter.

## 7. Pewter / Brock

- Pewter Gym: Brock (Rock). Bring Grass/Water/Fighting coverage if possible.
- Level cap: respect run rules (see `config/rules_red.yaml`) — do not overlevel past the gym cap.
- After Brock: continue east toward Mt. Moon / Cerulean (standard Red).

## Stuck cheatsheet

| Screen looks like… | Do this |
|--------------------|---------|
| Letter grid | Navigate to END → A |
| Text box | hold_b_120 → A |
| Bedroom, can’t leave | Find stairs tile; don’t spam only up/down |
| Living room | Walk south out the door |
| Pallet, walk_up noops | On a fence post — one tile left or right, then up |
| Lab, A noops on table | Table is 2 tiles tall; face a ball from the south |
| Lab, aide chatter | Parcel goes to Oak at the back, not the side NPC |
| Route 1 ledge / Viridian fence | Find the one-tile gap; do not wiggle left-right |
| Oscillating indoors/outdoors | Stop; pick a new column; consult memory |

## Nuzlocke reminders

- Dupes / first encounter / faint = dead — follow referee rules.
- No trainer items in battle unless rules allow.
- When unsure, prefer healing and safer routes over risky grass.
