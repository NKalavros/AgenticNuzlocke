---
name: pokemon-red-walkthrough
description: >-
  Pokemon Red / Red-Star walkthrough through Erika for the Nuzlocke agent. Use when
  stuck (noop walks, looping in a house/town, cannot find stairs/doors/lab), when
  unsure of the next story beat, or when Recovery asks for a route hint. Prefer
  reading the matching bundle in manifest.json over inventing map layout.
---

# Pokemon Red walkthrough (stuck helper)

## When to use

Use the injected walkthrough excerpt when one is present; do not read skill files again during that turn. Otherwise, read this skill and the matching fragments only when:

- The same walks keep failing / bouncing (house ↔ “outdoors” hallucination)
- You cannot find stairs, a door, Oak’s lab, or the next NPC
- Naming / dialog is done but story progress is unclear
- Recovery or high stuck score is active

Do **not** load the whole guide every step. Use `manifest.json` to select a bundle. Read **only** its `fragments/*.md` files for the current screen (title, house, Pallet, lab, Route 1, Viridian, Pewter/Brock, Route 3/Mt. Moon, Cerulean/Misty, Lt. Surge prerequisites, or the route to Erika).

## How to apply

1. Identify what the **screenshot** shows (menu, dialog, overworld room, town).
2. Select a named bundle in `manifest.json`, then read its fragments in order.
   Bundles can include other bundles. Read each fragment once. The `surge.*` and `erika.*` bundles match the observed progression stage.
   The `healing` fragment takes priority over story bundles while healing is mandatory. It permits necessary obstacle subgoals without releasing the healing objective.
   `reference.md` remains the full compatibility view; edit fragments, then regenerate that view.
3. Return an objective with a machine target for System 1. Supply explicit steps only for a screen System 1 cannot handle; it owns ordinary paths, menus, and battle execution.
4. Remember Red Star may differ cosmetically; **screenshot wins** over vanilla memory.
5. Note lasting facts to OptMem (via the orchestrator): e.g. “2F stairs are X”, “door is south”.

## Hard rules

- Screenshot is ground truth.
- Furniture / TV / plants are not outdoors and usually not stairs.
- Naming keyboard → `press_start` finishes the name; do not walk as overworld. Identify the letter grid, not the instant-text RAM flag alone.
- Ordinary dialog → `skip_dialog` (B taps with released wait frames). Never append A after the box closes; it can reopen the NPC. Stop at YES/NO and menus. Battle narration uses one A page at a time. Evolution waits without B; completion text and level-up stat boxes use A.
- Follow the controller's legal choices and preparation targets. Verify Bulbasaur before accepting the starter; do not override SET, encounter, death, or battle-entry cap rules.
- The default target is Misty (Cascade Badge); an explicitly continued run proceeds to Lt. Surge and Erika using the prerequisite checklists and its configured stopping milestone. Complete pending accessible encounters before advancing; never abandon a legal slot just because a search has taken many cycles. Completed encounters must not force a return to a previous gym or prevent visiting Bill.
- If a walk already nooped, do not repeat it — one tile perpendicular, then retry.
