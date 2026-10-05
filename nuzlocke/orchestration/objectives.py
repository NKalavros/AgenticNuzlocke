"""Milestone display filtering from verified run progress."""

from nuzlocke.referee.rules import MILESTONE_ORDER


def progression_objectives(obs):
    """Display only the observed progression stage; text never establishes completion."""
    from nuzlocke.assets import data
    from nuzlocke.knowledge.walkthrough import erika_stage, surge_stage

    if obs is None or obs.in_battle:
        return None
    for chapter, stage in (("erika", erika_stage(obs)), ("surge", surge_stage(obs))):
        if stage:
            choices = data("walkthrough/objectives.json")[chapter + "." + stage]
            return dict(next((v["objectives"] for v in choices["variants"] if obs.map_id in v["maps"]), choices["default"]))
    return None


def completed_descriptions(config, referee):
    """Only retire configured milestones whose completion has recorded evidence."""
    current = referee.current_milestone
    boss_index = MILESTONE_ORDER.index(current)
    completed = set(MILESTONE_ORDER[:boss_index])
    if boss_index or referee.balls_acquired:
        completed.update(("leave_pallet", "viridian"))
    entry = referee.encounter_ledger.get("12", {})
    if entry.get("outcome") and entry["outcome"] != "engaged":
        completed.add("route_1_encounter")
    return {
        item["description"].strip()
        for item in config.get("milestones", [])
        if isinstance(item, dict) and item.get("id") in completed and item.get("description")
    }


def prune_completed(objectives, config, referee):
    done = completed_descriptions(config, referee)
    return {tier: text for tier, text in objectives.items() if text.strip() not in done}
