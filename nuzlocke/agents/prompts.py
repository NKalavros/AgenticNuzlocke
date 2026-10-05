"""Prompt and response-schema names shared by role adapters."""

from nuzlocke.assets import data, text

VISION_ONLY_SUFFIX = text("prompts/vision_only_suffix.md")
OVERWORLD_SYSTEM = text("prompts/overworld_system.md")
BATTLE_SYSTEM = text("prompts/battle_system.md")
RECOVERY_SYSTEM = text("prompts/recovery_system.md")
PLANNER_SYSTEM = text("prompts/planner_system.md")
MEMORY_ROLLUP_SYSTEM = text("prompts/memory_rollup_system.md")
OVERWORLD_SCHEMA = data("schemas/overworld_schema.json")
BATTLE_SCHEMA = data("schemas/battle_schema.json")
RECOVERY_SCHEMA = data("schemas/recovery_schema.json")
PLANNER_SCHEMA = data("schemas/planner_schema.json")
MEMORY_ROLLUP_SCHEMA = data("schemas/memory_rollup_schema.json")
