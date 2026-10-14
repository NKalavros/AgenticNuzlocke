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


def test_full_bag_alone_does_not_interrupt_progression():
    state = {"active": False, "pending": None}
    obs = scene(full_bag())
    observe_space(state, obs, lambda *_: None)
    assert not state["active"] and space_beat(obs) is None


def test_blocked_purchase_latches_only_until_it_fits_and_survives_resume():
    state = {"active": False, "pending": None}
    obs = scene(full_bag())
    obs.shop_stock = [{"id": 3, "item": "Great Ball", "slot": 0}]
    observe_space(state, obs, lambda *_: None)
    assert state["active"] and state["need"]["reason"] == "blocked purchase"
    restored = ShopController()
    restored.space = state
    copy = ShopController()
    copy.restore(restored.snapshot())
    obs.bag.pop(0)
    observe_space(copy.space, obs, lambda *_: None)
    assert not copy.space["active"]  # One free slot is enough for this purchase.


def test_existing_ball_stack_can_be_restocked_without_cleanup():
    state = {"active": False, "pending": None}
    obs = scene(full_bag())
    obs.bag[-1] = {"id": 3, "item": "Great Ball", "quantity": 4}
    obs.shop_stock = [{"id": 3, "item": "Great Ball", "slot": 0}]
    observe_space(state, obs, lambda *_: None)
    assert not state["active"]


def test_restocking_to_a_full_bag_does_not_retrigger_cleanup():
    state = {"active": False, "pending": None}
    obs = scene(full_bag())
    obs.bag[-1] = {"id": 3, "item": "Great Ball", "quantity": 10}
    obs.shop_stock = [{"id": 3, "item": "Great Ball", "slot": 0}]
    observe_space(state, obs, lambda *_: None)
    assert not state["active"]


def test_observed_item_refusal_requests_space_until_one_slot_is_free():
    state = {"active": False, "pending": None}
    obs = scene(full_bag())
    obs.screen_rows = [" " * 20] * 12 + [
        "┌──────────────────┐",
        "│                  │",
        "│No room for items.│",
        "│                  │",
        "│                  │",
        "└──────────────────┘",
    ]
    observe_space(state, obs, lambda *_: None)
    assert state["active"] and state["need"]["reason"] == "observed capacity refusal"
    obs.screen_rows = []
    observe_space(state, obs, lambda *_: None)
    assert state["active"]  # Remember the required acquisition after dialogue closes.
    obs.bag.pop(0)
    observe_space(state, obs, lambda *_: None)
    assert not state["active"]


def test_legacy_fullness_only_cleanup_retires_without_a_sale():
    state = {"active": True, "pending": None}
    observe_space(state, scene(full_bag()), lambda *_: None)
    assert not state["active"]


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


@pytest.mark.parametrize("item_id,name,allowed", [(82, "Elixir", True), (81, "Ether", True), (49, "Nugget", False)])
def test_zero_quote_requires_explicit_surplus_permission_and_exact_sale(item_id, name, allowed):
    pending = {"id": item_id, "item": name, "quantity": 1, "money": 1000, "bag": {str(item_id): 1, "72": 1}}
    state = {"active": True, "need": {"item": "Poké Flute", "quantity": 1}, "pending": pending}
    obs = scene([{"id": item_id, "item": name, "quantity": 1}, {"id": 72, "item": "Silph Scope", "quantity": 1}])
    obs.screen_rows = [
        "┌─────────┬────┐",
        f"│▷{name.upper():8}│▶YES│",
        "│         │ NO │",
        "└─────────┴────┘",
        "          ┌────┐",
        "          │▶YES│",
        "          │ NO │",
        "          └────┘",
        *[" " * 20] * 4,
        "┌──────────────────┐",
        "│I can pay you     │",
        "│                  │",
        "│¥0 for that.      │",
        "│                  │",
        "└──────────────────┘",
    ]
    if not allowed:
        with pytest.raises(RuntimeError, match="Cannot verify"):
            space_choice(state, obs)
        return
    assert space_choice(state, obs) == ("confirm sale", [A.PRESS_A])
    pending["offer"] = 0
    obs.bag.pop(0)
    records = []
    observe_space(state, obs, lambda kind, _: records.append(kind))
    assert "bag_sale_verified" in records and not state["active"] and obs.money == 1000


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


def test_fuji_make_room_message_requests_capacity_without_move_learning():
    from nuzlocke.agents.move_learning import learning_phase

    obs = scene(full_bag(), learning_move_id=75, learning_party_slot=0)
    obs.screen_rows = [" " * 20] * 12 + [
        "┌──────────────────┐",
        "│                  │",
        "│You must make     │",
        "│                  │",
        "│room for this!    │",
        "└──────────────────┘",
    ]
    state = {"active": False, "pending": None}
    observe_space(state, obs, lambda *_: None)
    assert state["active"] and state["need"]["reason"] == "observed capacity refusal"
    assert learning_phase(obs) is None


def test_capacity_arrival_changes_stage_and_clears_stale_exit_plan():
    from nuzlocke.orchestration.loop import RunLoop
    from nuzlocke.state.models import PlanCard, PlanScene
    from nuzlocke.agents.goals import RoomMap

    obs = scene(full_bag())
    obs.map_id = 4
    obs.map_name = "Lavender Town"
    obs.x = 15
    obs.y = 14
    obs.policy["bag_space"] = {"active": True, "need": {"item": "Poké Flute", "quantity": 1}, "pending": None}
    route = space_beat(obs)
    assert route.target == {"kind": "warp", "dest_map": 150}
    loop = RunLoop.__new__(RunLoop)
    loop.room = RoomMap()
    loop._beat_locked = True
    loop._beat_id = route.id
    loop._seed_objectives = lambda: {"primary": "Continue to Koga"}
    loop.plan = PlanCard(scene=PlanScene.OVERWORLD, see="Fuji", plan="Leave the house", goal_target={"kind": "warp", "dest_map": 4})
    obs.map_id = 150
    obs.map_name = "Lavender Mart"
    obs.x = 3
    obs.y = 7
    sell = space_beat(obs)
    assert sell.id != route.id and sell.target == {"kind": "npc", "name": "clerk"}
    loop._sync_beats(obs, controllable=True)
    assert loop.plan is None and loop._beat_id == sell.id
