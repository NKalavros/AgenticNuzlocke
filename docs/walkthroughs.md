# Compose walkthrough guidance

The canonical guide lives in [the walkthrough skill](../.cursor/skills/pokemon-red-walkthrough/SKILL.md). Its [manifest](../.cursor/skills/pokemon-red-walkthrough/manifest.json) defines three parts:

- `fragments`: stable names mapped to Markdown files beneath the skill directory.
- `bundles`: ordered lists of fragment or bundle names.
- `matches`: context keywords and the bundles used for recovery excerpts.

`stage_hints` supplies the short prerequisite descriptions for the Surge stages. The Python selector reads observed badges, inventory, living party moves, and location. Text cannot establish progress or override System 3.

## Read only the needed parts

```bash
uv run python tools/walkthrough.py surge.bill
uv run python tools/walkthrough.py erika.rock_tunnel rules
uv run python tools/walkthrough.py koga.rocket_key
uv run python tools/walkthrough.py koga.gym team
```

In Python:

```python
from nuzlocke.knowledge.walkthrough import compose

hint = compose("surge.bill", "rules", max_chars=6000)
```

Composition expands nested bundles in order and includes each fragment once. Only selected files are read. Unknown IDs, include cycles, and paths outside the skill directory fail. A character limit truncates the final excerpt, including its truncation marker; it does not authorize skipping a game prerequisite.

## Add or change guidance

1. Edit a small file under `fragments/`, or add one with a stable ID in `manifest.json`.
2. Include it in the relevant bundle. Reuse existing fragments instead of copying their text.
3. Add it to `all` if it belongs in the complete guide.
4. For a new observed stage, update the selector in `nuzlocke/knowledge/walkthrough.py` and add a prerequisite test.
5. Regenerate and check the compatibility view:

   ```bash
   uv run python tools/walkthrough.py --write-reference
   uv run python tools/walkthrough.py --check
   uv run pytest -q tests/unit/test_walkthrough.py tests/unit/test_walkthrough_composition.py
   ```

`reference.md` remains available to older processes and manual readers. The check compares its text with `compose("all")`, ignoring whitespace differences. Runtime excerpts use the manifest and fragments. Do not hand-edit the compatibility view. The runner copies the skill directory into each new agent workspace.

## Keep decisions separate from text

`nuzlocke/assets/walkthrough/` holds static beat descriptions, targets, healing routes, and displayed progression objectives. `nuzlocke/knowledge/beats.py`, `agents/system3.py`, and `orchestration/objectives.py` select them using live evidence. Dynamic coordinates, legal choices, healing priority, and prerequisite checks remain Python.

Other static prompts and reference tables live under `nuzlocke/assets/` and ship in the Python package. The cached asset loader returns shared values; treat them as read-only or copy before mutation.

All Python loaders and selectors count toward the core source limit. Markdown and JSON content do not. See [the budget checker](../tools/core_loc.py) for the exact metric.

## Koga and conditional Surf

The `koga.*` stages share one observed selector with the Objectives panel. Add prerequisites to `knowledge/walkthrough.py`, stage prose to the fragments, and display text to `assets/walkthrough/objectives.json`. Inventory proves keys; map arrival can prove a blocked route has already been passed. Soul is the chapter's completion evidence.

`surf.teach`, `surf.locked` and `surf.field` belong in the complete reference but have no keyword recovery match. Runtime selection needs positive HM03 inventory or a living observed SURF move. Field use additionally needs Soul. Pass the current observation to `excerpt_for_context`; it preserves the current Koga stage and applies the Surf gate. A planner's mention of Surf cannot activate a bundle or change a destination.

System 4 composes the relevant challenge fragment with `rules` and `team`. Static species stats, learnsets, teaching-item IDs and challenge triggers live under `nuzlocke/assets/walkthrough/`; trainer reference moves stay with the trainer teams. Executable selection, legality, calculation and transfer logic remains counted core Python.
