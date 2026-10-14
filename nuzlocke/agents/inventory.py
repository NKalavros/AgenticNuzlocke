"""Select a known bag item even when its row is below the visible menu."""

import re

from nuzlocke.agents.shop import normalize
from nuzlocke.assets import data
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


def _bag_menu(obs):
    screen = parse_screen(obs.screen_rows)
    rows = screen.menu_rows
    if not rows or screen.cursor_row is None or any("¥" in row for row in rows):
        return None
    bag = [normalize(str(item.get("item", ""))) for item in obs.bag]
    labels = [normalize(row.split("×")[0]) for row in rows]
    # Distinguish the inventory from START, USE/TOSS, and Pokémon-selection menus.
    if not all(label in bag or label == "CANCEL" for label in labels):
        return None
    if len(set(bag)) != len(bag):
        return None  # A repeated label cannot establish an absolute cursor.
    return screen, bag, labels


def _bag_actions(obs, wanted, *, missing_action=A.WAIT_60):
    menu = _bag_menu(obs)
    if menu is None:
        return None
    screen, bag, labels = menu
    target = next((i for i, item in enumerate(obs.bag) if bag[i] == wanted and item.get("quantity", 0) > 0), None)
    if target is None:
        return [missing_action]  # Missing candy pauses preparation; an unauthorized battle bag closes.
    selected = labels[screen.cursor_row]
    current = len(bag) if selected == "CANCEL" else bag.index(selected)
    return [A.PRESS_A if current == target else A.WALK_DOWN if current < target else A.WALK_UP]


def _field_allowed(obs, label):
    matches = [item for item in obs.bag if normalize(item.get("item", "")) == label]
    return len(matches) == 1 and any(
        item.get("quantity", 0) > 0
        and normalize(item.get("item", "")) == label == normalize(entry["item"])
        and item.get("id") == entry["id"]
        and (not entry.get("preparing") or obs.policy.get("preparing"))
        for item in matches
        for entry in data("walkthrough/field_items.json")
    )


def field_bag_choices(obs):
    """Shared field inventory choices: scrolling is independent of permission to use an item."""
    if obs.in_battle:
        return None
    menu = _bag_menu(obs)
    choices = {"back": ("Press B to close the bag", [A.PRESS_B])}
    if menu is None:
        screen = parse_screen(obs.screen_rows)
        if "TOSS" not in screen.menu_rows:
            return None
        labels = [normalize(label.split("×")[0]) for label in re.findall(r"▷([^│]+)", " ".join(obs.screen_rows))]
        selected = [label for label in labels if any(normalize(i.get("item", "")) == label for i in obs.bag)]
        if len(selected) == 1 and _field_allowed(obs, selected[0]) and "USE" in screen.menu_rows:
            from nuzlocke.agents.system1 import menu_actions

            slot = screen.menu_rows.index("USE")
            choices[f"choose_{slot}"] = ("Use the verified field item", menu_actions(f"choose_{slot}", screen.cursor_row))
        return choices  # TOSS and unverifiable item use remain unavailable.
    screen, bag, labels = menu
    current = len(bag) if labels[screen.cursor_row] == "CANCEL" else bag.index(labels[screen.cursor_row])
    for name, action, names in (("up", A.WALK_UP, bag[:current]), ("down", A.WALK_DOWN, bag[current + 1 :] + ["CANCEL"])):
        if names and not (name == "down" and current == len(bag)):
            choices[f"scroll_{name}"] = (
                f"Scroll {name} one row without using an item; {name}ward items: {', '.join(names)}",
                [action],
            )
    for i, label in enumerate(labels):
        if label == "CANCEL":
            choices[f"choose_{i}"] = ("Close the bag", [A.PRESS_B])
        elif _field_allowed(obs, label):
            choices[f"choose_{i}"] = (f"Select {screen.menu_rows[i]}", _bag_actions(obs, label))
    return choices


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
