"""Verified capture-ball purchases through ordinary Mart menus."""

import re

from nuzlocke.environment.screen_text import parse_screen
from nuzlocke.state.models import GameAction as A

TARGET = 10
# Gen 1 priority/prices; the visible row and final total are checked before payment.
BALLS = {2: ("Ultra Ball", 1200), 3: ("Great Ball", 600), 4: ("Poke Ball", 200)}


def normalize(text):
    return re.sub(r"[^A-Z0-9]", "", text.upper().replace("É", "E"))


def ball_count(obs, item=None):
    names = {normalize(item)} if item else {normalize(name) for name, _ in BALLS.values()}
    return sum(i.get("quantity", 0) for i in obs.bag if normalize(str(i.get("item", ""))) in names)


def best_ball(obs):
    for item_id, (name, price) in BALLS.items():
        stock = next((i for i in obs.shop_stock if i.get("id") == item_id), None)
        if stock and (obs.money or 0) >= price:
            return {**stock, "item": name, "price": price}
    return None


def desired_quantity(obs, ball):
    if not ball:
        return 0
    return max(
        0,
        min(
            TARGET - ball_count(obs),
            (obs.money or 0) // ball["price"],
            99 - ball_count(obs, ball["item"]),
        ),
    )


def cursor_action(cursor, target):
    return [A.PRESS_A if cursor == target else A.WALK_DOWN if cursor < target else A.WALK_UP]


def shop_choice(obs, pending=None):
    if obs.in_battle or not obs.flags.get("has_pokedex"):
        return None
    screen = parse_screen(obs.screen_rows)
    text = " ".join(obs.screen_rows)
    speech = " ".join(screen.text_lines)
    words = normalize(speech)
    rows = [r.upper() for r in screen.menu_rows]
    cursor = screen.cursor_row
    selected = [normalize(s) for s in re.findall(r"[▶▷]([^│┐┘]+)", text)]
    shop_ui = any(re.search(r"[│▶▷]\s*BUY\b", r) for r in obs.screen_rows)
    if not shop_ui and not pending:
        return None
    ball = best_ball(obs)
    want = desired_quantity(obs, ball)
    if obs.shop_stock and not ball and ball_count(obs) < TARGET and (obs.money or 0) >= 200:
        raise RuntimeError(
            "This Mart has no affordable capture ball; pause instead of repeating the supply visit"
        )
    # A price question can overlay the quantity box. Handle the active prompt first.
    if rows == ["YES", "NO"] and cursor is not None:
        total = re.search(r"¥\s*(\d+)", speech)
        if not pending:
            return "reselect quantity before confirming", [A.PRESS_B]
        if (
            not any(s.startswith(normalize(pending["item"])) for s in selected)
            or not total
            or int(total[1]) != pending["quantity"] * pending["price"]
        ):
            raise RuntimeError("Mart confirmation differs from the authorized ball purchase")
        return "confirm purchase", cursor_action(cursor, 0)
    if "THATWILLBE" in words:
        return (
            ("advance price question", [A.PRESS_A, A.WAIT_60])
            if pending
            else ("cancel untracked purchase", [A.PRESS_B, A.WAIT_60])
        )
    quantity = re.search(r"×\s*(\d+)", text)
    if quantity:
        if not ball or not want or not any(s.startswith(normalize(ball["item"])) for s in selected):
            return "cancel quantity", [A.PRESS_B]
        have = int(quantity[1])
        return "quantity", [A.WALK_UP if have < want else A.WALK_DOWN if have > want else A.PRESS_A]
    if cursor is not None and "BUY" in rows and "QUIT" in rows:
        return "leave shop" if not want else "open BUY", cursor_action(
            cursor, rows.index("QUIT" if not want else "BUY")
        )
    if cursor is not None and any("¥" in row for row in rows):
        if not obs.shop_stock:
            raise RuntimeError("Mart stock list unavailable; cannot verify the best ball")
        if not want:
            return "close item list", [A.PRESS_B]
        index = next(
            (i for i, row in enumerate(rows) if normalize(row).startswith(normalize(ball["item"]))),
            None,
        )
        if index is None:
            # Read the full loaded list, then scroll until the chosen row is visible.
            absolute = (obs.menu_scroll or 0) + (
                obs.menu_index if obs.menu_index is not None else cursor
            )
            return f"scroll to {ball['item']}", [
                A.WALK_DOWN if absolute < ball["slot"] else A.WALK_UP
            ]
        price = re.search(r"¥\s*(\d+)", rows[index])
        if not price or int(price[1]) != ball["price"]:
            raise RuntimeError("Unexpected ball price; purchase paused")
        return f"select {ball['item']}", cursor_action(cursor, index)
    if "HOWMANY" in words:
        return "wait for quantity input", [A.WAIT_60]
    if "▷" in text and "▶" not in text:
        return (
            ("page shop dialogue", [A.PRESS_B, A.WAIT_60])
            if screen.text_lines
            else ("wait for shop menu", [A.WAIT_60])
        )
    return None


class ShopController:
    def __init__(self):
        self.pending = None
        self.cycles = 0
        self.error = None

    def snapshot(self):
        return {"pending": self.pending, "cycles": self.cycles, "error": self.error}

    def restore(self, data):
        self.pending = (data or {}).get("pending")
        self.cycles = (data or {}).get("cycles", 0)
        self.error = (data or {}).get("error")

    def observe(self, obs, record):
        if not self.pending:
            return
        p = self.pending
        added = ball_count(obs, p["item"]) - p["item_before"]
        spent = p["money_before"] - (obs.money or 0)
        if added == p["quantity"] and spent == p["quantity"] * p["price"]:
            record(
                "shop_purchase_verified",
                {**p, "balls_after": ball_count(obs), "money_after": obs.money},
            )
            self.pending = None
            self.cycles = 0
        elif added not in {0, p["quantity"]} or spent not in {0, p["quantity"] * p["price"]}:
            raise RuntimeError("Mart bag/money change differs from the authorized purchase")

    def actions(self, obs):
        if self.error:
            return [A.WAIT_60]
        try:
            choice = shop_choice(obs, self.pending)
        except RuntimeError:
            # turn() reports the error and pauses. Permit the pause's released wait
            # through final policy instead of crashing while trying to preserve state.
            return [A.WAIT_60]
        return choice[1] if choice else None

    def turn(self, obs, record=lambda *_: None):
        if self.error:
            raise RuntimeError(self.error)
        self.observe(obs, record)
        choice = shop_choice(obs, self.pending)
        if choice is None:
            if self.pending:
                raise RuntimeError("Mart purchase ended without matching bag and money changes")
            self.cycles = 0
            return [], ""
        self.cycles += 1
        if self.cycles > 60:
            raise RuntimeError(
                "Mart transaction did not progress after 60 cycles; paused for inspection"
            )
        phase, actions = choice
        if phase == "cancel quantity":
            self.pending = None
        if phase == "quantity" and actions == [A.PRESS_A] and not self.pending:
            ball = best_ball(obs)
            self.pending = {
                **ball,
                "quantity": desired_quantity(obs, ball),
                "balls_before": ball_count(obs),
                "item_before": ball_count(obs, ball["item"]),
                "money_before": obs.money,
                "map_id": obs.map_id,
            }
            record("shop_purchase_requested", dict(self.pending))
        return actions, f"Mart: {phase}"
