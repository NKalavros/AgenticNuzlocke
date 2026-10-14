"""Select a known bag item even when its row is below the visible menu."""

from nuzlocke.agents.shop import normalize
from nuzlocke.environment.screen_text import parse_screen
from nuzlocke.state.models import GameAction as A


def is_capture_ball(item):
    identity = item.get("id")
    return (
        item.get("quantity", 0) > 0
        and normalize(str(item.get("item", ""))) in {"MASTERBALL", "ULTRABALL", "GREATBALL", "POKEBALL"}
        and (identity is None or identity in {1, 2, 3, 4})
    )


def capture_ball_actions(obs, first_encounter=False):
    """Scroll a legal catch's full bag; close it when survival or encounter rules require another action."""
    if not obs.in_battle:
        return None
    from nuzlocke.agents.system3 import forced_battle_choice

    ball = (
        next((item for item in obs.bag if is_capture_ball(item)), None)
        if forced_battle_choice(obs, first_encounter) == "item"
        else None
    )
    return _bag_actions(obs, normalize(ball["item"]) if ball else None, missing_action=A.PRESS_B)


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


def _bag_actions(obs, wanted, *, missing_action=A.WAIT_60):
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
        return [missing_action]  # Missing candy pauses preparation; an unauthorized battle bag closes.
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


def teaching_actions(obs):
    target = (obs.policy.get("system4") or {}).get("teaching")
    if not target or obs.in_battle:
        return None
    from nuzlocke.agents.lead_rotation import key, toward
    from nuzlocke.agents.move_learning import learning_phase

    if learning_phase(obs):
        return None
    screen = parse_screen(obs.screen_rows)
    if screen.menu_title == "TM_COMPATIBILITY":
        slot = next((i for i, m in enumerate(obs.party) if m.get("capture_id") == target["capture_id"]), None)
        if slot is None or f"choose_{slot}" not in (tm_party_choices(obs) or {}):
            raise ValueError("Planned Pokémon is NOT ABLE to learn this move")
        return toward(screen.cursor_row, slot)
    bag = _bag_actions(obs, normalize(target["item"]))
    if bag is not None:
        return bag
    rows = [key(r) for r in screen.menu_rows]
    for label in ("USE", "ITEM", "PACK"):
        if label in rows:
            return toward(screen.cursor_row, rows.index(label))
    if rows == ["YES", "NO"]:
        return toward(screen.cursor_row, 0)
    if screen.text_lines:
        return [A.PRESS_A]
    from nuzlocke.environment.screen_text import find_boxes

    return [A.WAIT_60] if find_boxes(obs.screen_rows) else [A.PRESS_START]
