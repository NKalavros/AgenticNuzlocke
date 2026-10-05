"""Select a known bag item even when its row is below the visible menu."""

from nuzlocke.agents.shop import normalize
from nuzlocke.environment.screen_text import parse_screen
from nuzlocke.state.models import GameAction as A


def candy_bag_actions(obs):
    if obs.in_battle or not obs.policy.get("preparing"):
        return None
    return _bag_actions(obs, "RARECANDY")


def cut_bag_actions(obs):
    from nuzlocke.agents.system3 import needs_heal
    from nuzlocke.knowledge.walkthrough import surge_stage

    if obs.in_battle or obs.policy.get("preparing") or needs_heal(obs) or surge_stage(obs) != "teach_cut":
        return None
    return _bag_actions(obs, "HM01")


def _bag_actions(obs, wanted):
    screen = parse_screen(obs.screen_rows)
    rows = screen.menu_rows
    if not rows or screen.cursor_row is None or any("¥" in row for row in rows):
        return None
    bag = [normalize(str(item.get("item", ""))) for item in obs.bag]
    labels = [normalize(row.split("×")[0]) for row in rows]
    # Distinguish the inventory from START, USE/TOSS, and Pokémon-selection menus.
    if not all(label in bag or label == "CANCEL" for label in labels):
        return None
    target = next((i for i, item in enumerate(obs.bag) if bag[i] == wanted and item.get("quantity", 0) > 0), None)
    if target is None:
        return [A.WAIT_60]  # Actor reports missing candy; final arbiter permits its pause.
    selected = labels[screen.cursor_row]
    current = len(bag) if selected == "CANCEL" else bag.index(selected)
    return [A.PRESS_A if current == target else A.WALK_DOWN if current < target else A.WALK_UP]


def tm_party_choices(obs):
    screen = parse_screen(obs.screen_rows)
    if obs.in_battle or screen.menu_title != "TM_COMPATIBILITY":
        return None
    return {
        f"choose_{i}": row
        for i, (row, mon) in enumerate(zip(screen.menu_rows, obs.party))
        if row.endswith("ABLE") and "NOT ABLE" not in row and mon.get("hp", 0) > 0 and not mon.get("dead")
    }
