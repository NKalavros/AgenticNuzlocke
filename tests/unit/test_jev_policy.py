"""Scene menus, replan gates, and the fast actor's confidence rules."""

from __future__ import annotations

from nuzlocke.agents.jev_policy import (
    FrameSignals,
    action_menu,
    build_jev_state,
    choose_fast_action,
    classify_scene,
    needs_replan,
)
from nuzlocke.llm.jev import JevAnswers
from nuzlocke.state.models import GameAction, PlanCard, PlanScene, PlayerObservation

NOW = 1_000.0


def _obs(**kwargs) -> PlayerObservation:
    base: dict = {
        "map_name": "Pallet Town",
        "x": 1,
        "y": 2,
        "party": [{"name": "Bulbasaur"}],
        "raw_player": {"name": "RED"},
    }
    base.update(kwargs)
    return PlayerObservation(**base)


def _plan(**kwargs) -> PlanCard:
    base: dict = {
        "scene": PlanScene.OVERWORLD,
        "see": "a room",
        "plan": "walk north",
        "world_digest": "world",
        "created_at": NOW,
    }
    base.update(kwargs)
    return PlanCard(**base)


def _signals(
    world: str = "world",
    dialog: str = "dlg",
    *,
    world_changed: bool = False,
    dialog_changed: bool = False,
    text_box: bool = False,
) -> FrameSignals:
    return FrameSignals(world, dialog, world_changed, dialog_changed, text_box)


def _answers(
    action: str = "walk_up_3",
    *,
    confidence: float = 0.9,
    stale: float = 0.1,
    done: float = 0.05,
) -> JevAnswers:
    return JevAnswers(action, confidence, stale, done, "jev-test")


def _turn(plan, obs, signals, jev_answers, *, refresh=None, streak=0, **kwargs):
    planned = {"n": 0}

    def default_refresh() -> PlanCard:
        planned["n"] += 1
        return _plan(plan="fresh plan", created_at=NOW)

    queue = list(jev_answers)

    def jev_decide(state, questions):
        return queue.pop(0)

    turn = choose_fast_action(
        plan=plan,
        obs=obs,
        signals=signals,
        now=NOW,
        plan_every_s=45,
        stale_noul=0.7,
        confidence_floor=0.55,
        low_confidence_streak=streak,
        jev_decide=jev_decide,
        refresh_plan=refresh or default_refresh,
        **kwargs,
    )
    return turn, planned["n"]


def test_naming_menu_excludes_skip_dialog():
    menu = action_menu("naming")
    assert "skip_dialog" not in menu
    assert "press_a" in menu
    assert set(menu) == {"walk_up", "walk_down", "walk_left", "walk_right", "press_a"}


def test_dialog_menu_is_b_only():
    menu = action_menu("dialog")
    assert set(menu) == {"skip_dialog", "press_b"}
    assert "press_a" not in menu


def test_overworld_menu_is_the_joystick():
    menu = action_menu("overworld", [["walk_up"]])
    assert set(menu) == {"walk_down", "walk_left", "walk_right", "press_a", "press_b"}
    assert "walk_up" not in menu
    assert "walk_down_3" not in menu
    assert "skip_dialog" not in menu


def test_dialog_plan_holds_while_only_text_moves():
    plan = _plan(scene=PlanScene.DIALOG, world_digest="still")
    signals = _signals("still", world_changed=False, dialog_changed=True)
    obs = _obs()
    assert classify_scene(obs, plan, signals) == "dialog"
    assert not needs_replan(plan, obs, signals, now=NOW, plan_every_s=45)


def test_leaving_a_dialog_plan_requests_replan():
    plan = _plan(scene=PlanScene.DIALOG, world_digest="still")
    signals = _signals("moved", world_changed=True)
    assert needs_replan(plan, _obs(), signals, now=NOW, plan_every_s=45)


def test_sprite_animation_does_not_replan_while_the_box_is_open():
    plan = _plan(scene=PlanScene.DIALOG, world_digest="sprite", text_box=True)
    signals = _signals("sprite-blink", world_changed=True, text_box=True)
    obs = _obs()
    assert classify_scene(obs, plan, signals) == "dialog"
    assert not needs_replan(plan, obs, signals, now=NOW, plan_every_s=45)


def test_closing_the_text_box_requests_replan():
    plan = _plan(scene=PlanScene.DIALOG, world_digest="still", text_box=True)
    signals = _signals("still", text_box=False)
    assert needs_replan(plan, _obs(), signals, now=NOW, plan_every_s=45)


def test_open_speech_presses_once_without_asking_jev():
    plan = _plan(
        scene=PlanScene.DIALOG,
        world_digest="intro",
        text_box=True,
        plan="Press B once to advance Oak's dialog.",
        see="Professor Oak is still speaking.",
    )
    signals = _signals("intro-moved", world_changed=True, text_box=True)

    def jev_decide(state, questions):
        raise AssertionError("jev should not be asked while a text box is open")

    def refresh():
        raise AssertionError("planner should not run while the line is still fresh")

    from nuzlocke.agents.jev_policy import choose_fast_action

    turn = choose_fast_action(
        plan=plan,
        obs=_obs(),
        signals=signals,
        now=NOW,
        plan_every_s=45,
        stale_noul=0.7,
        confidence_floor=0.55,
        low_confidence_streak=0,
        jev_decide=jev_decide,
        refresh_plan=refresh,
    )
    assert turn.actions == [GameAction.PRESS_B]
    assert turn.replanned is False


def test_speech_plan_that_says_press_a_presses_a():
    plan = _plan(
        scene=PlanScene.DIALOG,
        text_box=True,
        plan="Press A once to page the finished line.",
    )
    signals = _signals(text_box=True)
    from nuzlocke.agents.jev_policy import choose_fast_action

    turn = choose_fast_action(
        plan=plan,
        obs=_obs(),
        signals=signals,
        now=NOW,
        plan_every_s=45,
        stale_noul=0.7,
        confidence_floor=0.55,
        low_confidence_streak=0,
        jev_decide=lambda state, questions: (_ for _ in ()).throw(AssertionError("jev")),
        refresh_plan=lambda: (_ for _ in ()).throw(AssertionError("planner")),
    )
    assert turn.actions == [GameAction.PRESS_A]


def test_open_speech_is_replanned_after_a_few_seconds():
    plan = _plan(scene=PlanScene.DIALOG, text_box=True, created_at=NOW - 5)
    signals = _signals(text_box=True)
    assert needs_replan(plan, _obs(), signals, now=NOW, plan_every_s=45)
    fresh = _plan(scene=PlanScene.DIALOG, text_box=True, created_at=NOW)
    assert not needs_replan(fresh, _obs(), signals, now=NOW, plan_every_s=45)


def test_naming_plan_presses_down_once_then_must_look_again():
    plan = _plan(
        scene=PlanScene.NAMING,
        plan="Press DOWN once to move the cursor toward END.",
    )
    obs = _obs(joy_ignore=0x40)
    signals = _signals(text_box=True)
    assert not needs_replan(plan, obs, signals, now=NOW, plan_every_s=45)

    def jev_decide(state, questions):
        raise AssertionError("the named press does not ask Jev")

    turn = choose_fast_action(
        plan=plan,
        obs=obs,
        signals=signals,
        now=NOW,
        plan_every_s=45,
        stale_noul=0.7,
        confidence_floor=0.55,
        low_confidence_streak=0,
        jev_decide=jev_decide,
        refresh_plan=lambda: (_ for _ in ()).throw(AssertionError("planner")),
    )
    assert turn.actions == [GameAction.WALK_DOWN]
    assert turn.plan.spent is True
    assert needs_replan(turn.plan, obs, signals, now=NOW, plan_every_s=45)


def test_menu_plan_survives_the_highlight_moving():
    plan = _plan(scene=PlanScene.MENU, world_digest="menu")
    signals = _signals("menu-cursor", world_changed=True, dialog_changed=False)
    obs = _obs()
    assert classify_scene(obs, plan, signals) == "menu"
    assert not needs_replan(plan, obs, signals, now=NOW, plan_every_s=45)
    state = build_jev_state(plan=plan, scene="menu", obs=obs, signals=signals)
    assert "highlight" in state["hard_signal"]
    assert set(action_menu("menu")) >= {"walk_up", "walk_down", "press_a"}


def test_leaving_a_menu_requests_replan():
    plan = _plan(scene=PlanScene.MENU, world_digest="menu")
    signals = _signals("overworld", world_changed=True, dialog_changed=True)
    assert needs_replan(plan, _obs(), signals, now=NOW, plan_every_s=45)


def test_overworld_plan_on_one_tile_replans_before_the_cap():
    plan = _plan(scene=PlanScene.OVERWORLD, created_at=NOW - 8)
    signals = _signals()
    assert needs_replan(
        plan, _obs(), signals, now=NOW, plan_every_s=45, same_tile_streak=6
    )
    assert not needs_replan(
        plan, _obs(), signals, now=NOW, plan_every_s=45, same_tile_streak=5
    )


def test_menu_low_confidence_confirms_instead_of_backing_out():
    plan = _plan(scene=PlanScene.MENU, world_digest="menu")
    signals = _signals("menu")
    turn, planned = _turn(plan, _obs(), signals, [_answers("press_a", confidence=0.1)])
    assert planned == 0
    assert turn.actions == [GameAction.PRESS_A]


def test_fresh_plan_skips_planner_and_uses_jev():
    turn, planned = _turn(_plan(), _obs(), _signals(), [_answers()])
    assert planned == 0
    assert turn.actions == [GameAction.WALK_UP_3]
    assert turn.replanned is False
    assert "walk_up_3" in turn.reason


def test_missing_plan_calls_planner_then_jev():
    turn, planned = _turn(None, _obs(), _signals(), [_answers("walk_down")])
    assert planned == 1
    assert turn.replanned is True
    assert turn.actions == [GameAction.WALK_DOWN]
    assert turn.plan.plan == "fresh plan"


def test_stale_noul_refreshes_before_the_press():
    turn, planned = _turn(
        _plan(),
        _obs(),
        _signals(),
        [
            _answers("walk_up", stale=0.95),
            _answers("walk_down_3", stale=0.1),
        ],
    )
    assert planned == 1
    assert turn.actions == [GameAction.WALK_DOWN_3]


def test_objective_done_refreshes_before_the_press():
    turn, planned = _turn(
        _plan(),
        _obs(),
        _signals(),
        [
            _answers("walk_up", done=0.9),
            _answers("press_start", done=0.0),
        ],
    )
    assert planned == 1
    assert turn.actions == [GameAction.PRESS_START]


def test_one_low_confidence_uses_safe_action_without_planner():
    turn, planned = _turn(_plan(), _obs(), _signals(), [_answers(confidence=0.2)])
    assert planned == 0
    assert turn.actions == [GameAction.PRESS_B]
    assert turn.low_confidence_streak == 1


def test_second_low_confidence_calls_planner():
    turn, planned = _turn(
        _plan(),
        _obs(),
        _signals(),
        [
            _answers(confidence=0.2),
            _answers("walk_left_3", confidence=0.88, stale=0.0, done=0.0),
        ],
        streak=1,
    )
    assert planned == 1
    assert turn.actions == [GameAction.WALK_LEFT_3]
    assert turn.low_confidence_streak == 0


def test_naming_low_confidence_waits_instead_of_pressing_b():
    plan = _plan(scene=PlanScene.NAMING)
    obs = _obs(joy_ignore=0x40)
    turn, planned = _turn(plan, obs, _signals(), [_answers("press_a", confidence=0.1)])
    assert planned == 0
    assert turn.actions == [GameAction.WAIT_60]
