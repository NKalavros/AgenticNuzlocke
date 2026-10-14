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


def need_fits(obs, need):
    if need:
        held = next(
            (
                i
                for i in obs.bag
                if (need.get("id") is not None and i.get("id") == need["id"])
                or (need.get("id") is None and normalize(i.get("item", "")) == normalize(need["item"]))
            ),
            None,
        )
        if held:
            return held.get("quantity", 0) + need["quantity"] <= 99
    return occupied(obs) < data("walkthrough/inventory_space.json")["capacity"]


def capacity_need(obs, purchase=None):
    if obs.in_battle:
        return None
    from nuzlocke.agents.shop import best_ball, desired_quantity

    ball = purchase or best_ball(obs)
    quantity = purchase["quantity"] if purchase else desired_quantity(obs, ball)
    if ball and quantity:
        need = {"id": ball.get("id"), "item": ball["item"], "quantity": quantity, "reason": "blocked purchase"}
        if not need_fits(obs, need):
            return need
    words = normalize(" ".join(parse_screen(obs.screen_rows).text_lines))
    if not need_fits(obs, None) and any(
        phrase in words for phrase in data("walkthrough/inventory_space.json")["capacity_messages"]
    ):
        return {"item": "the item refused for lack of room", "quantity": 1, "reason": "observed capacity refusal"}
    return None


def observe_space(state, obs, record, purchase=None):
    # Old fullness-only checkpoints have no blocked operation; pending authorized sales still finish.
    if state.get("active") and not state.get("need") and not state.get("pending"):
        state["active"] = False
        record("bag_space_cancelled", {"reason": "no blocked operation recorded"})
    if not state.get("active") and (need := capacity_need(obs, purchase)):
        state.update(active=True, need=need, pending=None)
        record("bag_space_required", {"slots": occupied(obs), "need": need})
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
    if state.get("active") and not state.get("pending") and need_fits(obs, state.get("need")):
        state["active"] = False
        state.pop("need", None)
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
        allow_zero = any(
            a["id"] == item["id"] and a.get("allow_zero", False) for a in data("walkthrough/inventory_space.json")["sale_items"]
        )
        if not pending or not offer or (int(offer[1]) == 0 and not allow_zero):
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
    selling = obs.map_id in profile["marts"].values() or "Mart" in (obs.map_name or "")
    target = (
        {"kind": "npc", "name": "clerk"}
        if selling
        else ({"kind": "warp", "dest_map": profile["marts"][str(obs.map_id)]} if str(obs.map_id) in profile["marts"] else None)
    )
    return Beat(
        "bag_space_sell" if selling else "bag_space_route",
        f"Free bag space for {state.get('need', {}).get('item', 'the blocked operation')} at a Mart; then resume the interrupted objective.",
        "Use SELL; preserve keys, fossils, TMs/HMs, capture balls, Rare Candies and all unapproved items.",
        target=target,
    )
