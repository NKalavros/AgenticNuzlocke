"""Capacity intervention: preserve important inventory and verify approved Mart sales."""

import re

from nuzlocke.agents.shop import cursor_action, normalize
from nuzlocke.assets import data
from nuzlocke.environment.screen_text import parse_screen
from nuzlocke.state.models import GameAction as A


def occupied(obs):
    return sum(item.get("quantity", 0) > 0 for item in obs.bag)


def sale_item(obs):
    for allowed in data("walkthrough/inventory_space.json")["sale_items"]:
        matches = [
            i for i in obs.bag if i.get("id") == allowed["id"] and normalize(i.get("item", "")) == normalize(allowed["item"])
        ]
        if len(matches) == 1 and matches[0].get("quantity", 0) > 0:
            return matches[0]
    return None


def observe_space(state, obs, record):
    profile = data("walkthrough/inventory_space.json")
    if occupied(obs) >= profile["capacity"] and not state.get("active"):
        state.update(active=True, pending=None)
        record("bag_space_required", {"slots": occupied(obs)})
    pending = state.get("pending")
    if pending:
        remaining = sum(i.get("quantity", 0) for i in obs.bag if i.get("id") == pending["id"])
        expected = pending.get("offer")
        if remaining == 0 and expected is not None and obs.money == pending["money"] + expected:
            before = {int(k): v for k, v in pending["bag"].items()}
            after = {i["id"]: i["quantity"] for i in obs.bag if i.get("quantity", 0) > 0}
            before.pop(pending["id"])
            if before != after:
                raise RuntimeError("Inventory changed outside the approved capacity sale")
            record("bag_sale_verified", dict(pending))
            state["pending"] = None
        elif remaining != pending["quantity"] or obs.money != pending["money"]:
            raise RuntimeError("Bag sale quantity or money does not match the approved transaction")
    if state.get("active") and not state.get("pending") and occupied(obs) <= profile["capacity"] - profile["reserve_slots"]:
        state["active"] = False
        record("bag_space_restored", {"slots": occupied(obs)})
    obs.policy["bag_space"] = dict(state) if state.get("active") else None


def sale_visible(obs, item):
    for fragment in re.findall(r"[▶▷]([^│┐┘]+)", " ".join(obs.screen_rows)):
        label = normalize(fragment)
        matches = [i for i in obs.bag if normalize(i.get("item", "")).startswith(label)] if len(label) >= 4 else []
        if len(matches) == 1 and matches[0].get("id") == item["id"]:
            return True
    return False


def space_choice(state, obs):
    if not state.get("active") or obs.in_battle:
        return None
    screen = parse_screen(obs.screen_rows)
    rows = [normalize(r) for r in screen.menu_rows]
    text = " ".join(obs.screen_rows)
    speech = " ".join(screen.text_lines)
    pending = state.get("pending")
    shop_ui = any(re.search(r"[│▶▷]\s*BUY\b", row) for row in obs.screen_rows)
    if not shop_ui and not pending:
        return None
    from nuzlocke.agents.system3 import needs_heal

    if not pending and needs_heal(obs):
        return None
    item = pending or sale_item(obs)
    if pending and not any(
        a["id"] == item["id"] and normalize(a["item"]) == normalize(item["item"])
        for a in data("walkthrough/inventory_space.json")["sale_items"]
    ):
        raise RuntimeError("Capacity sale targets a protected item")
    if item is None:
        raise RuntimeError("Full bag has no approved surplus to sell; preserve important items and pause")
    if "BUY" in rows and "SELL" in rows and screen.cursor_row is not None:
        if pending:
            raise RuntimeError("Sale ended without a verified inventory and money change")
        return "open SELL", cursor_action(screen.cursor_row, rows.index("SELL"))
    if rows == ["YES", "NO"]:
        offer = re.search(r"¥\s*(\d+)", speech)
        if not pending or not offer or int(offer[1]) <= 0:
            raise RuntimeError("Cannot verify Mart sale offer")
        if pending.get("offer") is not None and pending["offer"] != int(offer[1]):
            raise RuntimeError("Mart sale offer changed before confirmation")
        if not sale_visible(obs, item):
            raise RuntimeError("Mart sale does not show the approved item")
        return "confirm sale", cursor_action(screen.cursor_row, 0)
    quantity = re.search(r"×\s*(\d+)\s+¥", text)
    if quantity:
        if not pending or not sale_visible(obs, item):
            return "cancel unrelated quantity", [A.PRESS_B]
        current, wanted = int(quantity[1]), pending["quantity"]
        return "sale quantity", [A.PRESS_A] if current == wanted else [A.WALK_UP if current < wanted else A.WALK_DOWN] * min(
            8, abs(wanted - current)
        )
    if screen.text_lines and screen.cursor_row is None:
        return "page sale dialogue", [A.PRESS_B, A.WAIT_60]
    if any("¥" in row for row in screen.menu_rows):
        return "close BUY list", [A.PRESS_B]
    from nuzlocke.agents.inventory import _bag_actions

    actions = _bag_actions(obs, normalize(item["item"]), missing_action=A.PRESS_B)
    if actions is not None:
        return "select sale item", actions
    return None


def space_beat(obs):
    state = obs.policy.get("bag_space")
    if not state or obs.in_battle:
        return None
    from nuzlocke.knowledge.beats import Beat

    profile = data("walkthrough/inventory_space.json")
    target = {"kind": "warp", "dest_map": profile["marts"][str(obs.map_id)]} if str(obs.map_id) in profile["marts"] else None
    return Beat(
        "bag_space",
        "Free two bag slots at a Mart by selling only approved surplus; then resume the interrupted objective.",
        "Use SELL; preserve keys, fossils, TMs/HMs, capture balls, Rare Candies and all unapproved items.",
        target=target,
    )
