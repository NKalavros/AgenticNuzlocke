import pytest

from nuzlocke.agents.bag_space import observe_space, sale_item, space_beat, space_choice
from nuzlocke.agents.shop import ShopController
from nuzlocke.state.models import GameAction as A, PlayerObservation


def scene(bag=None, **kwargs):
    return PlayerObservation(
        map_id=150,
        money=1000,
        bag=bag or [{"id": 49, "item": "Nugget", "quantity": 2}],
        party=[{"species": "Ivysaur", "hp": 80, "max_hp": 80}],
        **kwargs,
    )


def full_bag():
    return [{"id": i, "item": f"TM{i}", "quantity": 1} for i in range(200, 219)] + [{"id": 49, "item": "Nugget", "quantity": 2}]


def test_full_bag_latches_until_two_slots_are_free_and_resumes():
    state = {"active": False, "pending": None}
    obs = scene(full_bag())
    observe_space(state, obs, lambda *_: None)
    assert state["active"] and space_beat(obs).id == "bag_space"
    restored = ShopController()
    restored.space = state
    copy = ShopController()
    copy.restore(restored.snapshot())
    obs.bag.pop(0)
    observe_space(copy.space, obs, lambda *_: None)
    assert copy.space["active"]
    obs.bag.pop(0)
    observe_space(copy.space, obs, lambda *_: None)
    assert not copy.space["active"]


def test_only_approved_exact_inventory_identities_can_be_sold():
    important = [
        {"id": i, "item": name, "quantity": 1}
        for i, name in [
            (72, "Silph Scope"),
            (73, "Poké Flute"),
            (74, "Lift Key"),
            (42, "Helix Fossil"),
            (196, "HM01"),
            (234, "TM34"),
            (4, "Poké Ball"),
            (40, "Rare Candy"),
            (29, "Escape Rope"),
        ]
    ]
    assert sale_item(scene(important)) is None
    assert sale_item(scene([{"id": 72, "item": "Nugget", "quantity": 1}])) is None
    assert sale_item(scene())["id"] == 49


def test_confirm_offer_with_occluded_name_requires_unique_identity():
    from nuzlocke.agents.bag_space import sale_visible

    obs = scene([{"id": 14, "item": "Awakening", "quantity": 1}])
    obs.screen_rows = ["│▷AWAKENIN│▶YES│", "│         │ NO │", "│I can pay you│", "│¥100 for that.│"]
    assert sale_visible(obs, obs.bag[0])
    obs.bag.append({"id": 200, "item": "Awakening Other", "quantity": 1})
    assert not sale_visible(obs, obs.bag[0])


def test_sale_verifies_full_stack_money_and_preserves_all_other_items():
    state = {
        "active": True,
        "pending": {"id": 49, "item": "Nugget", "quantity": 2, "money": 1000, "offer": 10000, "bag": {"49": 2, "72": 1}},
    }
    obs = scene([{"id": 72, "item": "Silph Scope", "quantity": 1}])
    obs.money = 11000
    records = []
    observe_space(state, obs, lambda k, d: records.append(k))
    assert "bag_sale_verified" in records and not state["active"]
    state["pending"] = {"id": 49, "item": "Nugget", "quantity": 2, "money": 1000, "offer": 10000, "bag": {"49": 2, "72": 1}}
    obs.bag = [{"id": 73, "item": "Poké Flute", "quantity": 1}]
    with pytest.raises(RuntimeError, match="outside the approved"):
        observe_space(state, obs, lambda *_: None)


def test_sale_rejects_partial_stack_or_wrong_money():
    state = {
        "active": True,
        "pending": {"id": 49, "item": "Nugget", "quantity": 2, "money": 1000, "offer": 10000, "bag": {"49": 2}},
    }
    obs = scene([{"id": 49, "item": "Nugget", "quantity": 1}])
    obs.money = 11000
    with pytest.raises(RuntimeError, match="does not match"):
        observe_space(state, obs, lambda *_: None)


def test_full_bag_preempts_unfulfilled_purchase_and_requires_sell():
    shop = ShopController()
    shop.cycles = 60
    shop.pending = {"item": "Great Ball", "quantity": 10, "price": 600, "item_before": 0, "money_before": 1000}
    obs = scene(full_bag())
    obs.screen_rows = ["┌─────────┐", "│▶BUY     │", "│ SELL    │", "│ QUIT    │", "└─────────┘"]
    shop.observe(obs, lambda *_: None)
    assert shop.pending is None and shop.cycles == 0
    assert shop.actions(obs) == [A.WALK_DOWN]
    obs.party[0]["hp"] = 1
    assert shop.actions(obs) is None


def test_capacity_does_not_select_items_from_overworld_pack():
    obs = scene()
    obs.screen_rows = ["│▶NUGGET│", "│× 2│", "│ CANCEL│"]
    assert space_choice({"active": True, "pending": None}, obs) is None
