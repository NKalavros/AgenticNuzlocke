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


def _butterfree(status="SLP"):
    obs = _obs([r.replace("SCRATCH", "SLEEP POWDER").replace("GROWL", "CONFUSION") for r in MOVES])
    obs.battle["enemy"] = {"species": "Starmie", "level": 21, "hp": 59, "max_hp": 59, "status": status}
    obs.party = [
        {
            "species": "Butterfree",
            "hp": 24,
            "max_hp": 58,
            "status": "OK",
            "moves": [{"id": 79, "name": "SLEEP POWDER", "pp": 5}, {"id": 93, "name": "CONFUSION", "pp": 25}],
        }
    ]
    return obs


def test_sleep_powder_has_effect_information_and_no_damage_matchup():
    obs = _butterfree("OK")
    criteria = battle.move_questions(obs, ("SLEEP POWDER", "CONFUSION"), {})["action"]["criteria"]
    assert "puts the opponent to sleep" in criteria["move_0"]
    assert "no direct damage" in criteria["move_0"]
    assert "accuracy 75%" in criteria["move_0"]
    assert "super effective" not in criteria["move_0"]
    assert "not very effective" in criteria["move_1"]
    assert "power 50" in criteria["move_1"]


def test_battle_handoff_keeps_strategy_and_blocks_repeated_sleep_even_on_fallback():
    from nuzlocke.agents.policy import decision
    from nuzlocke.agents.roles import _battle_plan
    from nuzlocke.orchestration.loop import RunLoop
    from nuzlocke.state.models import PlanCard, PlanScene

    obs = _butterfree()
    loop = RunLoop.__new__(RunLoop)
    loop.move_types = {}
    loop.plan = PlanCard(
        scene=PlanScene.BATTLE,
        see="Starmie sleeps",
        plan="Attack while it sleeps",
        do_not=["Do not use Sleep Powder while asleep"],
        battle_plan=_battle_plan(
            {
                "moves": ["SLEEP POWDER", "CONFUSION"],
                "opening_moves": ["SLEEP POWDER"],
                "notes": "Use Confusion until it wakes up.",
                "move_rules": [{"move": "SLEEP POWDER", "enemy_status": ["OK"], "reason": "Sleep once"}],
            }
        ),
    )
    received = []

    def decide(state, questions):
        received.append((state, questions))
        # Even a confident invalid choice must not bypass the status or plan restriction.
        return JevAnswers("move_0", 0.95, 0, 0, "jev", {"move_0": 0.95})

    args, _ = _turn_args(jev_decide=decide, battle_plan=loop._battle_plan(obs))
    turn = system1_turn(obs=obs, **args)
    state, questions = received[0]
    assert state["system2"]["notes"] == "Use Confusion until it wakes up."
    assert state["system2"]["do_not"] == loop.plan.do_not
    assert state["system2"]["intent"] == loop.plan.plan
    assert state["battle"]["enemy"]["status"] == "SLP"
    assert "move_0" not in questions["action"]["criteria"]
    assert turn.choice == "move_1"
    assert turn.actions == [GameAction.WALK_DOWN, GameAction.PRESS_A]
    assert decision(obs).validate(turn.actions) is None
    assert decision(obs).validate([GameAction.PRESS_A]) is not None
    assert loop._battle_brief(obs)["our_moves"][0]["unavailable_reason"]
    # Sleep counter ticks are the same condition; waking requires a fresh strategy.
    obs.battle["enemy"]["status"] = "SLP(2)"
    assert loop._battle_plan(obs)
    obs.battle["enemy"]["status"] = "OK"
    assert loop._battle_plan(obs) is None


def test_plan_conditions_and_bans_apply_with_unknown_status_and_to_fallback():
    obs = _butterfree(None)
    plan = {
        "moves": ["SLEEP POWDER", "CONFUSION"],
        "move_rules": [{"move": "Sleep Powder", "enemy_status": ["OK"], "reason": "Only if healthy"}],
    }
    screen = battle.parse_battle(obs.screen_rows)
    assert battle.fallback(screen, obs, plan=plan) == "move_1"
    obs.battle["enemy"]["status"] = "OK"
    criteria = battle.move_questions(obs, screen.options, {}, plan)["action"]["criteria"]
    assert "condition met" in criteria["move_0"]
    plan["avoid_moves"] = ["sleep powder"]
    assert battle.fallback(screen, obs, plan=plan) == "move_1"


def test_status_moves_do_not_block_damaging_moves_with_secondary_effects():
    obs = _butterfree("PSN")
    for name in ("SLEEP POWDER", "STUN SPORE", "POISONPOWDER"):
        assert battle.move_facts(obs, name)["unavailable_reason"]
    for name in ("CONFUSION", "EMBER", "THUNDERBOLT", "NIGHT SHADE"):
        assert not battle.move_facts(obs, name)["unavailable_reason"]
    assert battle.move_facts(obs, "NIGHT SHADE")["category"] == "special damage"


def test_only_blocked_moves_can_back_out_then_switch():
    obs = _butterfree()
    obs.screen_rows = [r.replace("CONFUSION", "-") for r in obs.screen_rows]
    obs.party[0]["moves"] = obs.party[0]["moves"][:1]
    obs.party.append({"species": "Pidgeotto", "hp": 50, "max_hp": 50})
    args, _ = _turn_args(battle_plan={"moves": ["SLEEP POWDER"]})
    turn = system1_turn(obs=obs, **args)
    assert turn.actions == [GameAction.PRESS_B]
    assert "fight" not in battle.menu_questions(obs)["action"]["criteria"]
    from nuzlocke.agents.policy import decision

    assert decision(obs).validate(turn.actions) is None


def test_invalid_plan_condition_is_not_silently_discarded():
    from nuzlocke.agents.roles import _battle_plan

    assert _battle_plan({"moves": ["SLEEP POWDER"], "move_rules": [{"move": "SLEEP POWDER", "enemy_status": ["SOMETHING"]}]}) == {}


def test_no_applicable_move_or_switch_stops_instead_of_reopening_the_move_menu():
    import pytest

    from nuzlocke.llm.jev import JevDecisionError

    obs = _butterfree()
    obs.party[0]["moves"] = obs.party[0]["moves"][:1]
    obs.screen_rows = MENU
    args, _ = _turn_args(battle_plan={"moves": ["SLEEP POWDER"]})
    with pytest.raises(JevDecisionError, match="No applicable battle choices"):
        system1_turn(obs=obs, **args)
    # Exhausted PP is different: FIGHT must remain available for automatic Struggle.
    obs.party[0]["moves"][0]["pp"] = 0
    assert "fight" in battle.menu_questions(obs)["action"]["criteria"]


def test_completed_growl_openers_are_not_repeatable_choices():
    obs = _obs(MOVES)
    obs.party[0]["moves"][1]["pp"] = 40
    plan = {"moves": ["SCRATCH"], "opening_moves": ["GROWL", "GROWL"]}
    args, _ = _turn_args(battle_plan=plan)
    for remaining in (2, 1):
        assert len(plan["opening_moves"]) == remaining
        assert system1_turn(obs=obs, **args).choice == "move_1"
        # Controller consumes each opening only after an observed PP decrease.
        obs.party[0]["moves"][1]["pp"] -= 1
        plan["opening_moves"].pop(0)
    choices = battle.move_questions(obs, ("SCRATCH", "GROWL"), {}, plan)["action"]["criteria"]
    assert list(choices) == ["move_0"]
    assert system1_turn(obs=obs, **args).choice == "move_0"
    # An explicitly repeatable conditional status move remains available.
    plan["moves"].append("GROWL")
    assert not battle.move_facts(obs, "GROWL", plan=plan)["unavailable_reason"]


def test_reads_the_battle_menu_and_the_move_list():
    menu = battle.parse_battle(MENU)
    assert (menu.kind, menu.cursor) == ("menu", 0)
    moves = battle.parse_battle(MOVES)
    assert moves.options == ("SCRATCH", "GROWL")
    assert (moves.cursor, moves.highlighted_type) == (0, "NORMAL")
    assert battle.parse_battle(TOP + [BLANK] * 15).kind is None


def test_cursor_moves_on_the_grid_and_the_list():
    menu = battle.parse_battle(MENU)
    assert battle.actions_for(menu, "run") == [GameAction.WALK_RIGHT, GameAction.WALK_DOWN, GameAction.PRESS_A]
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
    from nuzlocke.environment.screen_text import parse_screen

    wild.screen_rows = ["┌─────────────┐", "│ POKé BALL ×5│", "│▶CANCEL      │", "└─────────────┘"]
    bag = parse_screen(wild.screen_rows)
    throw = _battle_menu(bag, True, [], 0.55, args["jev_decide"], wild)
    assert throw.actions == [GameAction.WALK_UP]  # Reobserve before selecting the ball.
    wild.screen_rows = ["┌─────────────┐", "│▶POKé BALL ×5│", "│ CANCEL      │", "└─────────────┘"]
    assert _battle_menu(parse_screen(wild.screen_rows), True, [], 0.55, args["jev_decide"], wild).actions == [GameAction.PRESS_A]
    closed = _battle_menu(bag, False, [], 0.55, args["jev_decide"], wild)
    assert closed.actions == [GameAction.PRESS_B]
    nickname = ScreenText(["Do you want to give a", "nickname to PIDGEY?"], ["YES", "NO"], 0, "")
    assert _menu_turn(nickname, None, [], 0, 0.55, args["jev_decide"]).choice == "choose_1"


def test_items_are_never_offered_to_jev():
    wild = _obs(MENU, "wild").model_copy(update={"bag": [{"item": "Potion", "quantity": 2}]})
    assert "item" not in battle.menu_questions(wild)["action"]["criteria"]


def test_mart_quantity_respects_money_and_existing_ball_supply():
    from nuzlocke.agents.shop import best_ball, desired_quantity

    obs = PlayerObservation(money=3000, shop_stock=[{"id": 3, "slot": 0}], bag=[])
    assert desired_quantity(obs, best_ball(obs)) == 5
    obs.bag = [{"item": "Poke Ball", "quantity": 9}]
    assert desired_quantity(obs, best_ball(obs)) == 1


def test_exhausted_move_menu_requires_return_to_fight():
    from nuzlocke.agents.policy import decision

    obs = _obs(MOVES)
    for move in obs.party[0]["moves"]:
        move["pp"] = 0
    policy = decision(obs)
    assert policy.required == "back"
    assert policy.legal_sequences["back"] == [GameAction.PRESS_B]
