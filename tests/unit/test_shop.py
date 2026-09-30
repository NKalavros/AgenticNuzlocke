import json
from pathlib import Path

import pytest

from nuzlocke.agents.policy import decision
from nuzlocke.agents.shop import ShopController, best_ball, desired_quantity, shop_choice
from nuzlocke.environment import pa_serve
from nuzlocke.state.models import GameAction as A
from nuzlocke.state.models import PlayerObservation as O

SCREENS = json.loads((Path(__file__).parents[1] / "fixtures/mart_screens.json").read_text())


def observation(stage="items", **updates):
    return O(
        map_id=67,
        flags={"has_pokedex": True},
        money=3391,
        bag=[{"item": "Poke Ball", "quantity": 9}],
        screen_rows=SCREENS[stage],
        shop_stock=[{"id": 4, "slot": 0}],
        **updates,
    )


@pytest.mark.parametrize(
    "money,expected", [(2400, 2), (1200, 2), (1199, 3), (600, 3), (599, 4), (200, 4), (199, None)]
)
def test_best_affordable_ball(money, expected):
    obs = observation()
    obs.money = money
    obs.shop_stock = [{"id": i, "slot": s} for s, i in enumerate([4, 3, 2])]
    ball = best_ball(obs)
    assert (ball["id"] if ball else None) == expected


def test_quantity_counts_all_ball_types_and_budget():
    obs = observation()
    obs.bag = [{"item": "Great Ball", "quantity": 3}, {"item": "Poke Ball", "quantity": 5}]
    assert desired_quantity(obs, best_ball(obs)) == 2
    obs.money = 200
    assert desired_quantity(obs, best_ball(obs)) == 1


def test_scrolls_to_best_ball_below_visible_rows():
    obs = observation(menu_scroll=0, menu_index=0)
    obs.shop_stock.append({"id": 2, "slot": 6})
    assert shop_choice(obs)[1] == [A.WALK_DOWN]
    obs.screen_rows = SCREENS["quantity"]
    assert shop_choice(obs)[1] == [A.PRESS_B]  # Reselect Ultra instead of buying current Poké Ball.


def test_real_quantity_price_pages_checkpoint_and_verified_receipt():
    shop, events = ShopController(), []
    record = lambda kind, payload: events.append((kind, payload))
    obs = observation("quantity")
    assert shop.turn(obs, record)[0] == [A.PRESS_A]  # Hollow menu must not cancel ×01.
    restored = ShopController()
    restored.restore(json.loads(json.dumps(shop.snapshot())))
    obs.screen_rows = SCREENS["price_page"]
    assert restored.turn(obs)[0] == [A.PRESS_A, A.WAIT_60]
    obs.screen_rows = SCREENS["confirmation"]
    actions = restored.turn(obs)[0]
    assert actions == [A.PRESS_A]
    obs.policy["shop_actions"] = [a.value for a in restored.actions(obs)]
    assert decision(obs).validate(actions) is None
    assert decision(obs).validate([A.PRESS_B]) is not None
    obs.screen_rows = SCREENS["receipt"]
    obs.bag[0]["quantity"] = 10
    obs.money -= 200
    assert restored.turn(obs, record)[0] == [A.PRESS_B]
    restored.observe(obs, record)
    assert [e[0] for e in events] == ["shop_purchase_requested", "shop_purchase_verified"]
    assert restored.pending is None


def test_untracked_confirmation_cancels_and_bad_price_pauses():
    shop = ShopController()
    assert shop.turn(observation("confirmation"))[0] == [A.PRESS_B]
    shop.turn(observation("quantity"))
    obs = observation("confirmation")
    obs.screen_rows = [r.replace("¥200. OK?", "¥400. OK?") for r in obs.screen_rows]
    with pytest.raises(RuntimeError, match="confirmation differs"):
        shop.turn(obs)
    assert shop.actions(obs) == [A.WAIT_60]


def test_bad_receipt_and_stalled_menu_are_bounded():
    shop = ShopController()
    shop.turn(observation("quantity"))
    obs = observation("receipt")
    obs.money -= 400
    with pytest.raises(RuntimeError, match="bag/money"):
        shop.observe(obs, lambda *_: None)
    shop = ShopController()
    for _ in range(60):
        shop.turn(observation())
    with pytest.raises(RuntimeError, match="60 cycles"):
        shop.turn(observation())


def test_stock_reader_includes_offscreen_rows_and_rejects_stale_scratch(monkeypatch):
    class Emu:
        def __init__(self):
            self.memory = {
                0xCF7B: 6,
                **{0xCF7C + i: v for i, v in enumerate([4, 20, 30, 11, 3, 2, 255])},
            }

        def read_u8(self, addr):
            return self.memory.get(addr, 0)

        def read_range(self, addr, count):
            return bytes(self.read_u8(addr + i) for i in range(count))

    emu = Emu()
    monkeypatch.setattr(pa_serve, "read_screen_rows", lambda _: SCREENS["items"])
    assert [row["id"] for row in pa_serve.read_shop_stock(emu)] == [4, 20, 30, 11, 3, 2]
    emu.memory[0xCF82] = 0
    assert pa_serve.read_shop_stock(emu) == []
    emu.memory[0xCF82] = 255
    monkeypatch.setattr(pa_serve, "read_screen_rows", lambda _: [])
    assert pa_serve.read_shop_stock(emu) == []


def test_no_affordable_stock_pauses_instead_of_revisiting_shop_forever():
    obs = observation()
    obs.money = 400
    obs.shop_stock = [{"id": 2, "slot": 0}]
    with pytest.raises(RuntimeError, match="no affordable capture ball"):
        shop_choice(obs)
