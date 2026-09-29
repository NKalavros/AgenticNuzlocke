"""Battle menus read on Red Star (run 20260929-022135-035cb9), and the settle rule."""

from __future__ import annotations

from nuzlocke.agents import battle
from nuzlocke.agents.system1 import system1_turn
from nuzlocke.environment.nous_red import busy
from nuzlocke.environment.screen_text import ScreenText
from nuzlocke.llm.jev import JevAnswers
from nuzlocke.state.models import GameAction, PlayerObservation

BLANK = " " * 20
TOP = [" SQUIRTLE           ", "     5              ", "          CHARMANDER"]
MENU = [
    *TOP,
    "              5     ",
    "            17/ 20  ",
    *[BLANK] * 7,
    "┌───────┌──────────┐",
    "│       │          │",
    "│       │▶FIGHT PM │",
    "│       │          │",
    "│       │ ITEM  RUN│",
    "└───────└──────────┘",
]
MOVES = [
    *TOP,
    *[BLANK] * 5,
    "┌─────────┐   5     ",
    "│TYPE/    │         ",
    "│ NORMAL  │ 20/ 20  ",
    "│    35/35│         ",
    "└─────────┘────────┐",
    "│   │▶SCRATCH      │",
    "│   │ GROWL        │",
    "│   │ -            │",
    "│   │ -            │",
    "└───└──────────────┘",
]


def _obs(rows: list[str], kind: str = "trainer") -> PlayerObservation:
    return PlayerObservation(
        map_name="Oak's Lab",
        x=5,
        y=6,
        in_battle=True,
        battle={"type": kind, "enemy": {"species": "Squirtle", "level": 5, "hp": 20, "max_hp": 20}},
        party=[
            {
                "species": "Charmander",
                "hp": 17,
                "max_hp": 20,
                "types": ["Fire"],
                "moves": [{"name": "SCRATCH", "pp": 35}, {"name": "GROWL", "pp": 0}],
            }
        ],
        screen_rows=rows,
    )


def test_reads_the_battle_menu_and_the_move_list():
    menu = battle.parse_battle(MENU)
    assert (menu.kind, menu.cursor) == ("menu", 0)
    moves = battle.parse_battle(MOVES)
    assert moves.options == ("SCRATCH", "GROWL")
    assert (moves.cursor, moves.highlighted_type) == (0, "NORMAL")
    assert battle.parse_battle(TOP + [BLANK] * 15).kind is None


def test_cursor_moves_on_the_grid_and_the_list():
    menu = battle.parse_battle(MENU)
    assert battle.actions_for(menu, "run") == [
        GameAction.WALK_RIGHT,
        GameAction.WALK_DOWN,
        GameAction.PRESS_A,
    ]
    moves = battle.parse_battle(MOVES)
    assert battle.actions_for(moves, "move_1") == [GameAction.WALK_DOWN, GameAction.PRESS_A]


def test_options_carry_the_facts():
    trainer = battle.menu_questions(_obs(MENU))["action"]["criteria"]
    assert "run" not in trainer  # no running from a trainer
    assert "17/20" in trainer["fight"]
    assert "run" in battle.menu_questions(_obs(MENU, "wild"))["action"]["criteria"]
    moves = battle.move_questions(_obs(MOVES), ("SCRATCH", "GROWL"), {"SCRATCH": "NORMAL"})
    criteria = moves["action"]["criteria"]
    assert "normal damage on Squirtle" in criteria["move_0"]
    assert "move_1" not in criteria


def test_system_1_fights_through_jev_and_learns_move_types():
    known: dict[str, str] = {}

    def decide(state, questions):
        choice = "fight" if "fight" in questions["action"]["criteria"] else "move_0"
        return JevAnswers(choice, 0.9, 0.0, 0.0, "jev", {choice: 0.9})

    args = {
        "screen": ScreenText(),
        "text_box": False,
        "mash_stalled": False,
        "room": None,
        "objective": None,
        "objective_text": None,
        "objective_from_code": False,
        "heading": None,
        "fails": {},
        "last_direction": None,
        "low_confidence_streak": 0,
        "confidence_floor": 0.55,
        "stale_noul": 0.7,
        "journal": [],
        "constraints": [],
        "jev_decide": decide,
        "move_types": known,
        "battle_plan": {"moves": ["SCRATCH"], "switch_below": 0.0},
    }
    menu_turn = system1_turn(obs=_obs(MENU), **args)
    assert (menu_turn.kind, menu_turn.actions) == ("battle", [GameAction.PRESS_A])
    move_turn = system1_turn(obs=_obs(MOVES), **args)
    assert move_turn.actions == [GameAction.PRESS_A]
    assert known == {"SCRATCH": "NORMAL"}


def test_settle_waits_for_animations_but_not_for_a_decision():
    free = {"input": {"walking": 0, "battle": 0, "status5": 0, "joy_ignore": 0}, "screen": []}
    assert not busy(free)
    assert busy({**free, "input": {**free["input"], "walking": 5}})
    # A move animation between lines: in battle, no text, no menu.
    assert busy({**free, "input": {**free["input"], "battle": 2}, "screen": TOP})
    assert not busy({**free, "input": {**free["input"], "battle": 2}, "screen": MENU})


LEVEL_UP = [
    *[BLANK] * 2,
    "         ┌─────────┐",
    "         │ ATTACK  │",
    "         │      12 │",
    "         │ DEFENSE │",
    "         │      10 │",
    "         │ SPEED   │",
    "         │      13 │",
    "         │ SPECIAL │",
    "         │      12 │",
    "         └─────────┘",
    "┌──────────────────┐",
    "│                  │",
    "│CHARMANDER grew   │",
    "│                  │",
    "│to level 6!       │",
    "└──────────────────┘",
]


def test_the_level_up_stats_box_is_closed_with_a():
    # As read in run 20260929-095253-004c14, where B left it up for 70 cycles.
    from nuzlocke.agents.system1 import _special_page

    assert _special_page(LEVEL_UP).actions[0] == GameAction.PRESS_A
    evolving = [BLANK] * 12 + ["┌" + "─" * 18 + "┐", "│What? CHARMANDER  │", "│is evolving!      │"]
    assert GameAction.PRESS_B not in _special_page(evolving).actions
    assert _special_page(MENU) is None


def _turn_args(**kwargs):
    calls: list = []

    def decide(state, questions):
        calls.append(questions)
        return JevAnswers("fight", 0.9, 0.0, 0.0, "jev", {"fight": 0.9})

    args = {
        "screen": ScreenText(),
        "text_box": False,
        "mash_stalled": False,
        "room": None,
        "objective": None,
        "objective_text": None,
        "objective_from_code": False,
        "heading": None,
        "fails": {},
        "last_direction": None,
        "low_confidence_streak": 0,
        "confidence_floor": 0.55,
        "stale_noul": 0.7,
        "journal": [],
        "constraints": [],
        "jev_decide": decide,
        **kwargs,
    }
    return args, calls


def test_a_trainer_battle_asks_system_2_for_a_plan_once():
    args, _ = _turn_args()
    assert system1_turn(obs=_obs(MENU), **args).trigger == "trainer battle"
    args, calls = _turn_args(battle_plan={"moves": ["SCRATCH", "GROWL"], "switch_below": 0.0})
    system1_turn(obs=_obs(MENU), **args)
    assert "System 2's plan: SCRATCH" in calls[0]["action"]["criteria"]["fight"]
    moves = battle.move_questions(_obs(MOVES), ("SCRATCH", "GROWL"), {}, {"moves": ["GROWL"]})
    assert "move_1" not in moves["action"]["criteria"]


def test_system_3_throws_a_ball_at_the_first_encounter_and_says_no_to_nicknames():
    from nuzlocke.agents.system1 import _battle_menu, _menu_turn

    wild = _obs(MENU, "wild").model_copy(update={"bag": [{"item": "Poke Ball", "quantity": 5}]})
    args, calls = _turn_args(first_encounter=True)
    turn = system1_turn(obs=wild, **args)
    assert turn.choice == "item" and calls == []
    assert turn.actions == [GameAction.WALK_DOWN, GameAction.PRESS_A]
    bag = ScreenText([], ["POKé BALL  ×5", "CANCEL"], 1, "")
    throw = _battle_menu(bag, True, [], 0.55, args["jev_decide"])
    assert throw.actions == [GameAction.WALK_UP, GameAction.PRESS_A]
    closed = _battle_menu(bag, False, [], 0.55, args["jev_decide"])
    assert closed.actions == [GameAction.PRESS_A]  # CANCEL is already highlighted
    nickname = ScreenText(["Do you want to give a", "nickname to PIDGEY?"], ["YES", "NO"], 0, "")
    assert _menu_turn(nickname, None, [], 0, 0.55, args["jev_decide"]).choice == "choose_1"


def test_items_are_never_offered_to_jev():
    wild = _obs(MENU, "wild").model_copy(update={"bag": [{"item": "Potion", "quantity": 2}]})
    assert "item" not in battle.menu_questions(wild)["action"]["criteria"]


def test_the_mart_quantity_box_is_set_from_the_money():
    from nuzlocke.agents.system1 import _quantity_turn

    turn = _quantity_turn(PlayerObservation(money=3000, screen_rows=["│ ×01   ¥200│"]))
    assert turn.actions == [GameAction.WALK_UP] * 9 + [GameAction.PRESS_A]


def test_exhausted_move_menu_requires_return_to_fight():
    from nuzlocke.agents.policy import decision
    obs = _obs(MOVES)
    for move in obs.party[0]['moves']:
        move['pp'] = 0
    policy = decision(obs)
    assert policy.required == 'back'
    assert policy.legal_sequences['back'] == [GameAction.PRESS_B]
