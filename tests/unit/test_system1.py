"""System 1: goal options, what they press, and when System 2 is asked instead."""

from __future__ import annotations

from nuzlocke.agents.goals import RoomMap, build_goals, pick
from nuzlocke.agents.system1 import menu_actions, system1_turn
from nuzlocke.environment.screen_text import ScreenText
from nuzlocke.llm.jev import JevAnswers
from nuzlocke.orchestration.journal import format_line
from nuzlocke.state.models import GameAction, PlayerObservation

# Rows 1-9, columns A-J; the player at E5 is map tile (10, 10). E9 is a door mat that reads #.
GRID = """\
   A B C D E F G H I J
 1 . . . . . . . . . .
 2 . . . . . . . . . .
 3 . . . . . . . . . .
 4 . . . . . . . . . .
 5 . . . . @ . . . . .
 6 . . . . # . . . . .
 7 . . . . . . . . . .
 8 . . . . . . . . . .
 9 . . . . # . . . . ."""
DOOR = {"x": 10, "y": 14, "dest_map": 255, "dest_warp": 0}
OAK = {"slot": 1, "picture": 3, "x": 12, "y": 10, "on_screen": True}


def _obs(**kwargs) -> PlayerObservation:
    base = {
        "map_name": "Red's House 1F",
        "map_id": 37,
        "x": 10,
        "y": 10,
        "facing": "down",
        "collision_ascii": GRID,
        "warps": [DOOR],
        "npcs": [OAK],
        "raw_player": {"name": "RED"},
        "party": [{"species": "Bulbasaur"}],
    }
    return PlayerObservation(**{**base, **kwargs})


def _jev(choice: str, confidence: float = 0.9, **probabilities: float):
    calls: list[tuple[dict, dict]] = []

    def decide(state: dict, questions: dict) -> JevAnswers:
        calls.append((state, questions))
        return JevAnswers(choice, confidence, 0.0, 0.0, "jev", probabilities or {choice: 1.0})

    return decide, calls


def _turn(obs=None, **kwargs):
    args = {
        "obs": obs or _obs(),
        "screen": ScreenText(),
        "text_box": False,
        "mash_stalled": False,
        "room": RoomMap(),
        "objective": {"kind": "warp", "dest_map": 255},
        "objective_text": "Leave the house",
        "objective_from_code": True,
        "heading": None,
        "fails": {},
        "last_direction": None,
        "low_confidence_streak": 0,
        "confidence_floor": 0.55,
        "stale_noul": 0.7,
        "journal": [],
        "constraints": [],
    }
    args.update(kwargs)
    return system1_turn(**args)


def test_exit_goes_around_the_wall_and_off_the_mat():
    [exit_goal] = [g for g in build_goals(_obs(), RoomMap()) if g.kind == "exit"]
    assert exit_goal.label == "door or stairs to back outside"
    assert "path open" in exit_goal.facts[0]
    # 4 steps around the wall at E6 to the mat, then one more down to leave.
    assert len(exit_goal.actions) == 7
    assert exit_goal.actions[-1] == GameAction.WALK_DOWN


def test_talk_ends_facing_the_person_with_a():
    talk = next(g for g in build_goals(_obs(), RoomMap()) if g.kind == "talk")
    assert talk.label == "talk to the Prof. Oak"
    assert talk.actions == [GameAction.WALK_RIGHT, GameAction.WALK_RIGHT, GameAction.PRESS_A]


def test_objective_option_is_marked_and_first():
    goals = build_goals(
        _obs(), RoomMap(), objective={"kind": "npc", "picture": 3}, objective_text="Talk to Oak"
    )
    assert goals[0].kind == "talk" and goals[0].objective
    assert "CURRENT OBJECTIVE: Talk to Oak" in goals[0].criterion()


def test_an_untrusted_grid_learns_from_bumps():
    room = RoomMap()
    obs = _obs(collision_ascii=None, npcs=[])
    before = next(g for g in build_goals(obs, room) if g.kind == "exit")
    assert before.path[0] == "down"
    room.record_walks(
        obs, [{"action": "walk_down", "x0": 10, "y0": 10, "x1": 10, "y1": 10, "map_id": 37}]
    )
    after = next(g for g in build_goals(obs, room) if g.kind == "exit")
    assert after.path[0] != "down"


def test_jev_picks_a_goal_and_code_walks_it():
    decide, calls = _jev("exit_255")
    turn = _turn(jev_decide=decide)
    assert turn.kind == "goal" and turn.goal.kind == "exit"
    assert turn.actions[-1] == GameAction.WALK_DOWN
    _state, questions = calls[0]
    assert "CURRENT OBJECTIVE" in questions["action"]["criteria"]["exit_255"]
    # A code-owned beat is done when its map check says so, not on Jev's word.
    assert "objective_done" not in questions


def test_decisions_go_to_system_2():
    decide, _ = _jev("exit_255", 0.1, exit_0=0.4, talk_0=0.35, wait=0.25)
    assert _turn(objective=None, jev_decide=decide).trigger == "no objective"
    unsure = _turn(jev_decide=decide, low_confidence_streak=1, objective_from_code=False)
    assert unsure.trigger == "jev unsure twice"
    far = _turn(
        objective={"kind": "warp", "dest_map": 12}, objective_from_code=False, jev_decide=decide
    )
    assert far.trigger == "objective not on this map"
    failing = _turn(jev_decide=_jev("exit_255")[0], fails={"exit_255": 3, "talk_1": 3})
    assert failing.trigger == "goal keeps failing"


def test_a_goal_that_failed_twice_yields_to_the_runner_up():
    goals = build_goals(_obs(), RoomMap())
    chosen = pick(goals, "exit_255", {"exit_255": 0.6, "talk_1": 0.3}, {"exit_255": 2})
    assert chosen.key == "talk_1"


def test_menus_text_and_title_need_no_look():
    screen = ScreenText(["First, what is", "your name?"], ["NEW NAME", "RED", "ASH"], 0, "NAME")
    decide, calls = _jev("choose_1")
    intro = _obs(raw_player={"name": ""}, party=[], map_name="Red's House 2F")
    turn = _turn(intro, screen=screen, objective=None, jev_decide=decide)
    assert turn.actions == [GameAction.WALK_DOWN, GameAction.PRESS_A]
    assert calls[0][0]["menu"] == ["NEW NAME", "RED", "ASH"]
    assert _turn(intro, text_box=True, jev_decide=decide).actions == [GameAction.SKIP_DIALOG]
    assert _turn(intro, jev_decide=decide).actions[-1] == GameAction.PRESS_START
    assert menu_actions("back", 0) == [GameAction.PRESS_B]


def test_journal_line_reads_like_a_log():
    line = format_line(
        {
            "cycle": 3,
            "map": "Pallet Town",
            "x": 10,
            "y": 5,
            "choice": "edge_up",
            "p": 0.81,
            "label": "walk off the north edge",
            "actions": ["walk_up"] * 4,
            "outcome": "entered Route 1",
        }
    )
    assert line == (
        "c3 Pallet Town (10,5): edge_up p=0.81 (walk off the north edge) | pressed walk_up x4 "
        "| entered Route 1"
    )


def test_a_clear_lead_is_accepted_below_the_spread_floor():
    screen = ScreenText([], ["NEW GAME", "OPTION"], 0, "")
    decide, _ = _jev("choose_0", 0.48, choose_0=0.66, choose_1=0.29, back=0.05)
    intro = _obs(raw_player={"name": ""}, party=[])
    assert _turn(intro, screen=screen, jev_decide=decide).actions == [GameAction.PRESS_A]


def test_cell_is_a_map_tile_from_where_the_player_stands():
    from nuzlocke.agents.goals import cell_to_tile

    assert cell_to_tile("G7", _obs()) == (12, 12)
    assert cell_to_tile("K1", _obs()) is None


def test_object_trust_withholds_a_map_after_two_bad_warps():
    from nuzlocke.agents.goals import ObjectTrust

    trust = ObjectTrust()
    before = _obs(warps=[{"x": 3, "y": 3, "dest_map": 1, "dest_warp": 0}])
    after = _obs(map_id=1, map_name="Route 1")
    assert trust.record(before, after) is False
    assert trust.record(before, after) is True
    assert trust.view(before).warps == []
    at_door = _obs(x=3, y=4, warps=before.warps)
    fresh = ObjectTrust()
    fresh.record(at_door, after)
    assert fresh.record(at_door, after) is False


def test_a_path_north_goes_around_a_door_it_does_not_want():
    # Standing just below a house door, the north edge is the goal: do not walk back inside.
    obs = _obs(y=10, warps=[{"x": 10, "y": 9, "dest_map": 37, "dest_warp": 0}], npcs=[])
    obs = obs.model_copy(update={"connections": ["up"], "map_size": {"w": 20, "h": 18}})
    edge = next(g for g in build_goals(obs, RoomMap()) if g.key == "edge_up")
    assert edge.path[0] in {"left", "right"}


def test_a_shut_edge_is_followed_toward_the_wider_side():
    # Pallet (3,2): the tree line above, the Route 1 gap off screen to the east.
    trees = GRID.replace(" 4 . . . . . . . . . .", " 4 # # # # # # # # # #")
    obs = _obs(x=3, y=2, collision_ascii=trees, warps=[], npcs=[])
    obs = obs.model_copy(update={"connections": ["up"], "map_size": {"w": 20, "h": 18}})
    edge = next(g for g in build_goals(obs, RoomMap()) if g.key == "edge_up")
    assert edge.path and set(edge.path) == {"right"}


def test_a_shut_objective_asks_system_2_instead_of_bumping():
    # A wall down the whole screen at F; the target is beyond it, and no tile is closer.
    walled = "\n".join(
        line if not line[:2].strip().isdigit() else line[:13] + "#" + line[14:]
        for line in GRID.splitlines()
    )
    # The map is exactly the screen, and all of this side has been walked: nothing new is
    # in reach, so the objective goes to System 2.
    obs = _obs(x=4, y=4, collision_ascii=walled, warps=[], npcs=[])
    obs = obs.model_copy(update={"map_size": {"w": 10, "h": 9}})
    room = RoomMap()
    room.visited[37] = {(x, y) for x in range(5) for y in range(9)}
    decide, calls = _jev("objective")
    turn = _turn(obs, room=room, objective={"kind": "tile", "x": 8, "y": 4}, jev_decide=decide)
    assert turn.trigger == "objective path blocked"
    assert calls == []


def test_a_grid_that_boxes_the_player_in_is_ignored():
    boxed = GRID.replace(" 5 . . . . @ . . . . .", " 5 . . . # @ # . . . .").replace(
        " 4 . . . . . . . . . .", " 4 . . . . # . . . . ."
    )
    exit_goal = next(
        g for g in build_goals(_obs(collision_ascii=boxed), RoomMap()) if g.kind == "exit"
    )
    assert "path open" in exit_goal.facts[0]


def test_a_cutscene_waits_without_asking_anyone():
    decide, calls = _jev("exit_255")
    turn = _turn(_obs(cutscene=True), jev_decide=decide)
    assert (turn.kind, turn.actions) == ("cutscene", [GameAction.WAIT_60])
    assert calls == []
    # Text still pages during a scene: B is the one button the game accepts.
    assert _turn(_obs(cutscene=True), text_box=True, jev_decide=decide).kind == "page"


def test_a_ball_is_faced_from_below():
    ball = {"slot": 2, "picture": 74, "x": 11, "y": 10, "on_screen": True}
    talk = next(g for g in build_goals(_obs(npcs=[ball], warps=[]), RoomMap()) if g.kind == "talk")
    # It stands under the ball at (11,11) and faces up, whatever way it walks there.
    assert talk.path[-1] == "up"
    assert talk.actions[-1] == GameAction.PRESS_A


def test_the_pokedex_page_is_turned_with_a():
    page = _obs(joy_ignore=0x40, screen_rows=["CHARMANDER", "HT  2'00\"", "WT   19lb"])
    turn = _turn(page, jev_decide=_jev("x")[0])
    assert turn.actions[0] == GameAction.PRESS_A
    keyboard = _obs(joy_ignore=0x40, screen_rows=["A B C D E F G H I", "J K L M N O P Q R"])
    assert _turn(keyboard, jev_decide=_jev("x")[0]) is None
    # The same bit is set on the battle bag list; that is not the keyboard.
    assert _turn(_obs(joy_ignore=0x40, screen_rows=[]), jev_decide=_jev("exit_255")[0]) is not None


def test_a_goal_shows_the_text_it_ended_in():
    goals = build_goals(_obs(), RoomMap(), last_texts={"exit_255": "You can't go through here!"})
    exit_goal = next(g for g in goals if g.key == "exit_255")
    assert "You can't go through here!" in exit_goal.criterion()


def test_an_offscreen_target_pulls_toward_unvisited_ground():
    # Standing in a walked pocket, the target far north: head for new tiles, not the pocket.
    room = RoomMap()
    room.visited[37] = {(10, 10), (10, 9), (10, 8), (10, 7), (10, 6)}
    obs = _obs(warps=[], npcs=[])
    goals = build_goals(
        obs, room, objective={"kind": "tile", "x": 10, "y": -20}, objective_text="far"
    )
    goal = next(g for g in goals if g.key == "objective")
    assert goal.path and "closer" in goal.facts[1]


def test_uncertain_jev_uses_executable_code_target_without_another_look():
    decide, _ = _jev("exit_255", 0.1, exit_0=0.4, talk_0=0.35, wait=0.25)
    turn = _turn(jev_decide=decide, low_confidence_streak=2)
    assert turn.trigger is None
    assert turn.goal.objective
    assert turn.actions
