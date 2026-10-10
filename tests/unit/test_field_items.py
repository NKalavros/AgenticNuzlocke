from types import SimpleNamespace

from nuzlocke.agents.goals import RoomMap, build_goals, collision_map
from nuzlocke.agents.navigation import Navigator
from nuzlocke.environment.pa_serve import (
    W_MAP_SPRITE_EXTRA_DATA,
    W_NUM_SPRITES,
    W_SPRITE_STATE_DATA_1,
    W_SPRITE_STATE_DATA_2,
    read_map_objects,
)
from nuzlocke.knowledge.items import bag_has_room, item_objective
from nuzlocke.knowledge.objects import object_facts
from nuzlocke.state.models import GameAction as A
from nuzlocke.state.models import PlayerObservation


def scene():
    item = {
        "slot": 7,
        "picture": 74,
        "x": 1,
        "y": 31,
        "on_screen": True,
        "hidden": False,
        "item_id": 4,
        "item_name": "Poke Ball",
    }
    obs = PlayerObservation(
        map_id=51,
        map_name="Viridian Forest",
        x=1,
        y=30,
        facing="down",
        npcs=[item],
        party=[{"species": "Bulbasaur", "hp": 30, "max_hp": 30, "status": "OK"}],
        raw_player={"name": "RED"},
        bag=[],
    )
    room = RoomMap()
    # Item has a wall below it. The old starter-only approach cannot reach it.
    room.known[51] = {(1, 30): True, (2, 30): True, (2, 31): True, (1, 31): True, (1, 32): False}
    return obs, SimpleNamespace(room=room, _goal_fails={})


def test_unknown_floor_cannot_start_item_pickup_but_verified_walks_can():
    obs, loop = scene()
    obs.npcs[0].update(x=3, y=30)
    loop.room.known.clear()
    assert item_objective(loop, obs, None) is None
    assert obs.policy["item_pickup"] is None
    loop.room.record_walks(obs, [{"map_id": 51, "x0": 1, "y0": 30, "x1": 2, "y1": 30, "action": "walk_right"}])
    target, _, owned = item_objective(loop, obs, None)
    assert target == {"kind": "npc", "slot": 7} and owned


def test_live_item_decode_does_not_mislabel_starter_or_trainer():
    memory = {W_NUM_SPRITES: 3}
    for slot in (1, 2, 3):
        memory[W_SPRITE_STATE_DATA_1 + 16 * slot] = 74
        memory[W_SPRITE_STATE_DATA_2 + 16 * slot + 4] = 35
        memory[W_SPRITE_STATE_DATA_2 + 16 * slot + 5] = 5
    # Slot 1 is an ordinary scripted starter (0/0), 2 an item, 3 non-item extra data.
    memory[W_MAP_SPRITE_EXTRA_DATA + 2] = 4
    memory[W_MAP_SPRITE_EXTRA_DATA + 4] = 4
    memory[W_MAP_SPRITE_EXTRA_DATA + 5] = 1
    emu = SimpleNamespace(
        read_u8=lambda a: memory.get(a, 0),
        read_range=lambda a, n: bytes(memory.get(a + i, 0) for i in range(n)),
    )
    a, b, c = read_map_objects(emu)["npcs"]
    assert "item_id" not in a and "item_id" not in c
    assert b["item_id"] == 4 and b["item_name"] == "Poke Ball"
    assert object_facts(scene()[0], b)["name"] == "Poke Ball"


def test_pickup_above_forest_item_uses_down_then_a_and_skips_llm():
    from nuzlocke.agents.system1 import system1_turn
    from nuzlocke.environment.screen_text import ScreenText

    obs, loop = scene()
    target, text, owned = item_objective(loop, obs, None)
    turn = system1_turn(
        obs=obs,
        screen=ScreenText(),
        text_box=False,
        mash_stalled=False,
        room=loop.room,
        objective=target,
        objective_text=text,
        objective_from_code=owned,
        heading=None,
        fails={},
        last_direction=None,
        low_confidence_streak=0,
        confidence_floor=0.5,
        stale_noul=0.7,
        journal=[],
        constraints=[],
        navigator=Navigator(),
        jev_decide=lambda *_: (_ for _ in ()).throw(AssertionError("LLM called")),
    )
    assert turn.actions == [A.WALK_DOWN, A.PRESS_A]
    assert turn.goal.label == "pick up Poke Ball"


def test_hidden_pickup_disappears_and_offscreen_item_remains_obstacle():
    obs, loop = scene()
    obs.npcs[0]["on_screen"] = False
    assert not collision_map(obs, loop.room)[1, 31]
    assert item_objective(loop, obs, None)
    obs.npcs[0]["hidden"] = True
    assert item_objective(loop, obs, None) is None
    assert collision_map(obs, loop.room)[1, 31]
    assert not object_facts(obs, obs.npcs[0])["available"]


def test_starters_and_fossils_are_not_automatic_pickups():
    obs, loop = scene()
    obs.npcs[0].pop("item_id")
    obs.npcs[0].pop("item_name")
    assert item_objective(loop, obs, None) is None
    goal = next(g for g in build_goals(obs, loop.room) if g.kind == "talk")
    assert goal.actions != [A.WALK_DOWN, A.PRESS_A]
    obs.npcs[0]["picture"] = 75
    assert item_objective(loop, obs, None) is None


def test_bag_full_defers_pickup_but_existing_stack_can_accept_one():
    obs, loop = scene()
    obs.bag = [{"id": i, "item": f"Item {i}", "quantity": 1} for i in range(10, 30)]
    assert not bag_has_room(obs, obs.npcs[0])
    assert item_objective(loop, obs, None) is None
    obs.bag[0] = {"id": 4, "item": "Poke Ball", "quantity": 98}
    assert item_objective(loop, obs, None)
    obs.bag[0]["quantity"] = 99
    assert item_objective(loop, obs, None) is None


def test_safety_menus_unreachable_and_repeated_failures_defer_pickup():
    for update in [
        {"in_battle": True},
        {"cutscene": True},
        {"screen_rows": ["┌──────────┐", "│Found it! │", "└──────────┘"]},
    ]:
        obs, loop = scene()
        assert item_objective(loop, obs.model_copy(update=update), None) is None
    obs, loop = scene()
    obs.party[0]["hp"] = 5
    assert item_objective(loop, obs, None) is None
    obs.party[0]["hp"] = 30
    assert item_objective(loop, obs, SimpleNamespace(id="prepare_center")) is None
    loop._goal_fails["talk_7"] = 3
    assert item_objective(loop, obs, None) is None
    loop._goal_fails.clear()
    obs.npcs[0].update(x=20, y=20, on_screen=False)
    assert item_objective(loop, obs, None) is None


def test_runloop_pickup_outranks_encounter_and_updates_objective_window():
    from nuzlocke.orchestration.loop import RunLoop

    obs, state = scene()
    loop = RunLoop.__new__(RunLoop)
    loop.room = state.room
    loop._goal_fails = {}
    loop._beat_locked = True
    loop._beat_id = None
    loop.plan = None
    loop._seed_objectives = lambda: {"primary": "Cross forest"}
    assert loop._objective(obs)[0] == {"kind": "npc", "slot": 7}
    assert "Poke Ball" in loop._sync_beats(obs, controllable=True)
    assert "Poke Ball" in loop.objectives["primary"]


def test_trainer_blocked_pickup_does_not_toggle_with_visibility_or_drop_story_plan():
    from nuzlocke.orchestration.loop import RunLoop

    # TM19-shaped enclosure: only one entrance, occupied by a trainer.
    obs, state = scene()
    obs.map_id, obs.map_name = 999, "Enclosure"
    obs.map_size = {"w": 7, "h": 7}
    obs.x, obs.y = 4, 5
    obs.badges = ["Boulder", "Cascade"]
    obs.npcs[0].update(x=2, y=1, item_id=219, item_name="TM19", on_screen=False)
    trainer = {"slot": 3, "picture": 7, "x": 4, "y": 3, "hidden": False}
    obs.npcs.append(trainer)
    state.room.known[999] = {(x, y): False for x in range(7) for y in range(7)}
    for tile in [(4, 5), (4, 4), (4, 3), (4, 2), (3, 2), (2, 2)]:
        state.room.known[999][tile] = True
    loop = RunLoop.__new__(RunLoop)
    loop.room = state.room
    loop._goal_fails = {}
    loop._beat_locked, loop._beat_id = False, None
    loop._seed_objectives = lambda: {"primary": "Visit Bill"}
    story_plan = loop.plan = object()
    for visible in (True, False, True, False):
        trainer["on_screen"] = visible
        assert not collision_map(obs, loop.room)[4, 3]
        assert item_objective(loop, obs, None) is None
        loop._sync_beats(obs, controllable=True)
        assert "Bill" in loop.objectives["primary"]
        assert not loop._beat_locked and loop.plan is story_plan
    # A real change to occupancy, unlike scrolling, makes the pickup eligible.
    trainer["x"] = 5
    assert collision_map(obs, loop.room)[4, 3]
    assert item_objective(loop, obs, None)[0] == {"kind": "npc", "slot": 7}
    trainer["x"] = 4
    trainer["hidden"] = True
    assert collision_map(obs, loop.room)[4, 3]
    assert item_objective(loop, obs, None)
