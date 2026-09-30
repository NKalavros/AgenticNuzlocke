from types import SimpleNamespace

from nuzlocke.agents.goals import RoomMap, build_goals
from nuzlocke.agents.navigation import Navigator
from nuzlocke.agents.policy import decision
from nuzlocke.agents.preparation import preparation_turn
from nuzlocke.knowledge.beats import current_beat
from nuzlocke.state.models import GameAction as A
from nuzlocke.state.models import PlayerObservation as O


def scene():
    return O(
        map_id=61,
        map_name="Mt Moon B2F",
        raw_player={"name": "RED"},
        x=13,
        y=15,
        map_size={"w": 40, "h": 36},
        badges=["Boulder"],
        party=[{"species": "Nidorino", "level": 18, "hp": 54, "max_hp": 54}],
        npcs=[
            {"slot": 6, "picture": 75, "x": 12, "y": 6, "on_screen": False},
            {"slot": 7, "picture": 75, "x": 13, "y": 6, "on_screen": False},
        ],
    )


def test_fossil_story_step_advances_only_after_bag_confirmation():
    obs = scene()
    beat = current_beat(obs)
    assert beat.id == "moon_choose_fossil"
    assert beat.target == {"kind": "npc", "slot": 7, "picture": 75}
    obs.bag = [{"item": "Helix Fossil", "quantity": 0}]
    assert current_beat(obs).id == "moon_choose_fossil"
    obs.bag[0]["quantity"] = 1
    assert current_beat(obs).id == "moon_exit_ladder"


def test_director_receives_named_offscreen_objects_and_interaction_target():
    obs = scene()
    target = current_beat(obs).target
    data = Navigator().context(obs, RoomMap(), target)
    assert data["interaction_target"] == target
    fossil = data["objects"][1]
    assert fossil["name"] == "Helix Fossil"
    assert fossil["x"] == 13 and fossil["y"] == 6
    assert "verify on arrival" in fossil["visibility"]
    assert "YES" in fossil["interaction"]


def test_offscreen_target_is_offered_to_actor_and_keeps_its_slot_identity():
    obs = scene()
    room = RoomMap()
    room.known[61] = {(x, y): True for x in (12, 13) for y in range(7, 17)}
    goals = build_goals(obs, room, objective=current_beat(obs).target)
    goal = next(g for g in goals if g.objective)
    assert goal.key == "talk_7" and "Helix Fossil" in goal.label
    assert goal.finish == A.PRESS_A
    assert goal.path[-1] == "up"
    assert all(g.key != "talk_6" for g in goals)  # Other off-screen objects aren't actionable.


def question(prompt=False):
    rows = [" " * 20 for _ in range(18)]
    rows[12:] = [
        "┌──────────────────┐",
        "│                  │",
        "│You want the      │",
        "│                  │",
        "│HELIX FOSSIL?     │",
        "└──────────────────┘",
    ]
    if prompt:
        rows[7:12] = [
            "            ┌──────┐",
            "            │▶YES  │",
            "            │      │",
            "            │ NO   │",
            "            └──────┘",
        ]
    return rows


def test_question_waits_for_menu_then_accepts_with_arbiter_agreement():
    obs = scene()
    for prompt, expected in [(False, [A.WAIT_60]), (True, [A.PRESS_A])]:
        obs.screen_rows = question(prompt)
        actions, _ = preparation_turn(SimpleNamespace(), obs)
        assert actions == expected
        assert decision(obs).validate(actions) is None
        assert decision(obs).validate([A.PRESS_B]) is not None
        assert decision(obs).validate([A.SKIP_DIALOG]) is not None


def test_receipt_is_acknowledged_without_reopening_fossil_choice():
    obs = scene()
    obs.bag = [{"item": "Dome Fossil", "quantity": 1}]
    obs.screen_rows = ["RED got the", "DOME FOSSIL!"]
    assert preparation_turn(SimpleNamespace(), obs)[0] == [A.PRESS_A, A.WAIT_60]
