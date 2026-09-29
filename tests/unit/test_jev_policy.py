"""Scene menus, replan gates, and the fast actor's confidence rules."""

from __future__ import annotations

from nuzlocke.agents.jev_policy import (
    FrameSignals,
    action_menu,
    build_jev_state,
    choose_fast_action,
    classify_scene,
    replan_reason,
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
    prompt_box: bool = False,
) -> FrameSignals:
    return FrameSignals(world, dialog, world_changed, dialog_changed, text_box, prompt_box)


def _answers(
    action: str = "walk_up_3", *, confidence: float = 0.9, stale: float = 0.1, done: float = 0.05
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


def test_overworld_menu_keeps_every_walk_off_a_blocked_tile():
    """Only this tile's blocked directions leave the menu."""
    menu = action_menu("overworld")
    assert "walk_up" in menu
    assert set(menu) == {"walk_up", "walk_down", "walk_left", "walk_right", "press_a", "press_b"}
    assert "walk_down_3" not in menu
    assert "skip_dialog" not in menu


def test_overworld_menu_hides_the_direction_blocked_on_this_tile():
    menu = action_menu("overworld", blocked_on_tile=["walk_down"])
    assert "walk_down" not in menu
    assert "walk_up" in menu


def test_dialog_plan_holds_while_only_text_moves():
    plan = _plan(scene=PlanScene.DIALOG, world_digest="still", text_box=True)
    signals = _signals("still", world_changed=False, dialog_changed=True, text_box=True)
    obs = _obs()
    assert classify_scene(obs, plan, signals) == "dialog"
    assert replan_reason(plan, obs, signals, now=NOW, plan_every_s=45) is None


def test_a_box_that_just_closed_is_the_overworld():
    """The text rows change when a box closes; the world above them does not.

    Run 20260928-205856-f65040 pressed a fresh four-step path one button per
    cycle because this frame was called dialog.
    """
    plan = _plan(scene=PlanScene.OVERWORLD, world_digest="still")
    signals = _signals("still", world_changed=False, dialog_changed=True)
    assert classify_scene(_obs(), plan, signals) == "overworld"
    held = _plan(scene=PlanScene.DIALOG, world_digest="still")
    assert classify_scene(_obs(), held, signals) == "overworld"


def test_leaving_a_dialog_plan_requests_replan():
    plan = _plan(scene=PlanScene.DIALOG, world_digest="still")
    signals = _signals("moved", world_changed=True)
    assert replan_reason(plan, _obs(), signals, now=NOW, plan_every_s=45) == "scene changed"


def test_sprite_animation_does_not_replan_while_the_box_is_open():
    plan = _plan(scene=PlanScene.DIALOG, world_digest="sprite", text_box=True)
    signals = _signals("sprite-blink", world_changed=True, text_box=True)
    obs = _obs()
    assert classify_scene(obs, plan, signals) == "dialog"
    assert replan_reason(plan, obs, signals, now=NOW, plan_every_s=45) is None


def test_closing_the_text_box_requests_replan():
    plan = _plan(scene=PlanScene.DIALOG, world_digest="still", text_box=True)
    signals = _signals("still", text_box=False)
    assert replan_reason(plan, _obs(), signals, now=NOW, plan_every_s=45) == "scene changed"


def test_open_speech_is_mashed_without_asking_jev():
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
    assert turn.actions == [GameAction.SKIP_DIALOG]
    assert turn.replanned is False


def test_speech_is_mashed_even_when_the_plan_says_press_a():
    plan = _plan(
        scene=PlanScene.DIALOG, text_box=True, plan="Press A once to page the finished line."
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
    assert turn.actions == [GameAction.SKIP_DIALOG]


def test_open_speech_is_not_replanned_just_because_time_passed():
    plan = _plan(scene=PlanScene.DIALOG, text_box=True, created_at=NOW - 30)
    signals = _signals(text_box=True)
    assert replan_reason(plan, _obs(), signals, now=NOW, plan_every_s=45) is None
    prompt = _signals(text_box=True, prompt_box=True)
    assert replan_reason(plan, _obs(), prompt, now=NOW, plan_every_s=45) == "new prompt"


def test_naming_plan_presses_down_once_then_must_look_again():
    plan = _plan(scene=PlanScene.NAMING, plan="Press DOWN once to move the cursor toward END.")
    obs = _obs(joy_ignore=0x40)
    signals = _signals(text_box=True)
    assert replan_reason(plan, obs, signals, now=NOW, plan_every_s=45) is None

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
    assert replan_reason(turn.plan, obs, signals, now=NOW, plan_every_s=45) == "plan spent"


def test_menu_plan_survives_the_highlight_moving():
    plan = _plan(scene=PlanScene.MENU, world_digest="menu")
    signals = _signals("menu-cursor", world_changed=True, dialog_changed=False)
    obs = _obs()
    assert classify_scene(obs, plan, signals) == "menu"
    assert replan_reason(plan, obs, signals, now=NOW, plan_every_s=45) is None
    state = build_jev_state(plan=plan, scene="menu", obs=obs, signals=signals)
    assert "highlight" in state["hard_signal"]
    assert set(action_menu("menu")) >= {"walk_up", "walk_down", "press_a"}


def test_leaving_a_menu_requests_replan():
    plan = _plan(scene=PlanScene.MENU, world_digest="menu")
    signals = _signals("overworld", world_changed=True, dialog_changed=True)
    assert replan_reason(plan, _obs(), signals, now=NOW, plan_every_s=45) == "scene changed"


def test_overworld_plan_on_one_tile_replans_before_the_cap():
    plan = _plan(scene=PlanScene.OVERWORLD, created_at=NOW - 8)
    signals = _signals()
    six = replan_reason(plan, _obs(), signals, now=NOW, plan_every_s=45, same_tile_streak=6)
    five = replan_reason(plan, _obs(), signals, now=NOW, plan_every_s=45, same_tile_streak=5)
    assert six == "same tile"
    assert five is None


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
        [_answers("walk_up", stale=0.95), _answers("walk_down_3", stale=0.1)],
    )
    assert planned == 1
    assert turn.actions == [GameAction.WALK_DOWN_3]


def test_objective_done_refreshes_before_the_press():
    turn, planned = _turn(
        _plan(),
        _obs(),
        _signals(),
        [_answers("walk_up", done=0.9), _answers("press_start", done=0.0)],
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
        [_answers(confidence=0.2), _answers("walk_left_3", confidence=0.88, stale=0.0, done=0.0)],
        streak=1,
    )
    assert planned == 1
    assert turn.actions == [GameAction.WALK_LEFT_3]
    assert turn.low_confidence_streak == 0


def _grid(*, up: str = ".", down: str = ".", left: str = ".", right: str = ".") -> str:
    return "\n".join([f"1 # {up} #", f"2 {left} @ {right}", f"3 # {down} #"])


def test_planned_step_is_taken_and_a_sidestep_is_not_held():
    """walk_right toward the ball happens. It is not replaced with B, and it is not held."""
    plan = _plan(plan="walk_right toward the starter ball.")
    obs = _obs(x=3, y=5, collision_ascii=_grid(up=".", right="."))

    def jev_decide(state, questions):
        raise AssertionError("a planned open step does not ask Jev")

    turn = choose_fast_action(
        plan=plan,
        obs=obs,
        signals=_signals(),
        now=NOW,
        plan_every_s=45,
        stale_noul=0.7,
        confidence_floor=0.55,
        low_confidence_streak=0,
        heading="up",
        jev_decide=jev_decide,
        refresh_plan=lambda: (_ for _ in ()).throw(AssertionError("planner")),
    )
    assert turn.actions == [GameAction.WALK_RIGHT]
    assert turn.plan.spent is True


def test_heading_is_held_when_the_plan_names_it():
    plan = _plan(plan="walk_up through the grass gap.")
    obs = _obs(x=8, y=8, collision_ascii=_grid(up="."))

    def jev_decide(state, questions):
        raise AssertionError("the heading is not sent to Jev")

    turn = choose_fast_action(
        plan=plan,
        obs=obs,
        signals=_signals(),
        now=NOW,
        plan_every_s=45,
        stale_noul=0.7,
        confidence_floor=0.55,
        low_confidence_streak=0,
        heading="up",
        jev_decide=jev_decide,
        refresh_plan=lambda: (_ for _ in ()).throw(AssertionError("planner")),
    )
    assert turn.actions == [GameAction.WALK_UP]
    assert turn.plan.spent is False


def test_an_open_heading_is_one_run():
    plan = _plan(plan="walk_up through the grass gap.")
    rows = [f"{i} # . #" for i in range(1, 4)] + ["4 . @ ."]
    obs = _obs(x=8, y=8, collision_ascii="\n".join(rows))

    turn = choose_fast_action(
        plan=plan,
        obs=obs,
        signals=_signals(),
        now=NOW,
        plan_every_s=45,
        stale_noul=0.7,
        confidence_floor=0.55,
        low_confidence_streak=0,
        heading="up",
        jev_decide=lambda state, questions: (_ for _ in ()).throw(AssertionError("jev")),
        refresh_plan=lambda: (_ for _ in ()).throw(AssertionError("planner")),
    )
    assert turn.actions == [GameAction.WALK_UP_3]
    assert turn.plan.spent is False


def test_a_missing_grid_does_not_invent_a_run():
    plan = _plan(plan="walk_up through the grass gap.")
    obs = _obs(x=8, y=8, collision_ascii=None)

    turn = choose_fast_action(
        plan=plan,
        obs=obs,
        signals=_signals(),
        now=NOW,
        plan_every_s=45,
        stale_noul=0.7,
        confidence_floor=0.55,
        low_confidence_streak=0,
        heading="up",
        jev_decide=lambda state, questions: (_ for _ in ()).throw(AssertionError("jev")),
        refresh_plan=lambda: (_ for _ in ()).throw(AssertionError("planner")),
    )
    assert turn.actions == [GameAction.WALK_UP]


def test_a_heading_into_a_wall_sidesteps_without_a_prior_failure():
    plan = _plan(plan="walk_up through the gap.")
    obs = _obs(x=10, y=2, collision_ascii=_grid(up="#", left="#", right="."))

    turn = choose_fast_action(
        plan=plan,
        obs=obs,
        signals=_signals(),
        now=NOW,
        plan_every_s=45,
        stale_noul=0.7,
        confidence_floor=0.55,
        low_confidence_streak=0,
        heading="up",
        jev_decide=lambda state, questions: (_ for _ in ()).throw(AssertionError("jev")),
        refresh_plan=lambda: (_ for _ in ()).throw(AssertionError("planner")),
    )
    assert turn.actions == [GameAction.WALK_RIGHT]
    assert turn.plan.spent is True


def test_blocked_heading_sidesteps_once_then_the_heading_resumes():
    plan = _plan(plan="walk_up through the gap.")
    blocked = _obs(x=10, y=2, collision_ascii=_grid(up="#", left="#", right="."))
    seen: dict[str, object] = {}

    def jev_decide(state, questions):
        seen["state"] = state
        seen["menu"] = set((questions.get("action") or {}).get("criteria") or {})
        return _answers("walk_right")

    first = choose_fast_action(
        plan=plan,
        obs=blocked,
        signals=_signals(),
        now=NOW,
        plan_every_s=45,
        stale_noul=0.7,
        confidence_floor=0.55,
        low_confidence_streak=0,
        heading="up",
        blocked_on_tile=["walk_up"],
        jev_decide=jev_decide,
        refresh_plan=lambda: (_ for _ in ()).throw(AssertionError("planner")),
    )
    assert first.actions == [GameAction.WALK_RIGHT]
    assert "state" not in seen

    opened = _obs(x=11, y=2, collision_ascii=_grid(up=".", left=".", right="."))
    second = choose_fast_action(
        plan=_plan(plan="walk_up through the gap."),
        obs=opened,
        signals=_signals(),
        now=NOW,
        plan_every_s=45,
        stale_noul=0.7,
        confidence_floor=0.55,
        low_confidence_streak=0,
        heading="up",
        jev_decide=jev_decide,
        refresh_plan=lambda: (_ for _ in ()).throw(AssertionError("planner")),
    )
    assert second.actions == [GameAction.WALK_UP]


def test_a_failed_plan_direction_sidesteps_instead_of_pressing_b():
    plan = _plan(plan="walk_up through the gap.")
    obs = _obs(x=8, y=2, collision_ascii=_grid(up="#", left=".", right="."))

    def jev_decide(state, questions):
        return _answers("press_b", confidence=0.2)

    turn = choose_fast_action(
        plan=plan,
        obs=obs,
        signals=_signals(),
        now=NOW,
        plan_every_s=45,
        stale_noul=0.7,
        confidence_floor=0.55,
        low_confidence_streak=0,
        heading="up",
        blocked_on_tile=["walk_up"],
        jev_decide=jev_decide,
        refresh_plan=lambda: (_ for _ in ()).throw(AssertionError("planner")),
    )
    assert turn.actions == [GameAction.WALK_LEFT]
    assert turn.actions != [GameAction.PRESS_B]


def test_no_walk_is_pressed_while_a_box_is_open():
    """The D-pad does nothing until the box closes.

    Run 20260928-205856-f65040 sent two walk_downs into every reopened Oak
    box because the tile's page count only grew.
    """
    plan = _plan(scene=PlanScene.DIALOG, plan="walk_down off this bookshelf.", text_box=True)

    def jev_decide(state, questions):
        raise AssertionError("speech is mashed")

    turn = choose_fast_action(
        plan=plan,
        obs=_obs(),
        signals=_signals(text_box=True),
        now=NOW,
        plan_every_s=45,
        stale_noul=0.7,
        confidence_floor=0.55,
        low_confidence_streak=0,
        heading="up",
        jev_decide=jev_decide,
        refresh_plan=lambda: (_ for _ in ()).throw(AssertionError("planner")),
    )
    assert turn.actions == [GameAction.SKIP_DIALOG]


def _no_look() -> PlanCard:
    raise AssertionError("no planner look")


def _page_turn(plan: PlanCard, signals: FrameSignals, **kwargs):
    return choose_fast_action(
        plan=plan,
        obs=_obs(),
        signals=signals,
        now=NOW,
        plan_every_s=45,
        stale_noul=0.7,
        confidence_floor=0.55,
        low_confidence_streak=0,
        jev_decide=lambda state, questions: _answers("press_b"),
        **kwargs,
    )


def test_a_box_that_opens_after_a_spent_plan_is_paged_before_a_look():
    """The planner used to look first, then the code mashed anyway."""
    plan = _plan(plan="press A on the aide", spent=True)
    turn = _page_turn(plan, _signals(dialog_changed=True, text_box=True), refresh_plan=_no_look)
    assert turn.actions == [GameAction.SKIP_DIALOG]
    assert turn.looks == []
    assert turn.plan.scene == PlanScene.DIALOG


def test_text_after_an_answered_yes_no_is_paged_before_a_look():
    plan = _plan(scene=PlanScene.MENU, plan="press A for YES", prompt_digest="yes-no", spent=True)
    turn = _page_turn(plan, _signals(dialog_changed=True, text_box=True), refresh_plan=_no_look)
    assert turn.actions == [GameAction.SKIP_DIALOG]


def test_a_menus_own_text_box_still_gets_a_look():
    """The party list draws a box. B there closes the menu the plan opened."""
    plan = _plan(scene=PlanScene.MENU, plan="choose the lead", spent=True)
    looked: list[int] = []

    def refresh() -> PlanCard:
        looked.append(1)
        return _plan(
            scene=PlanScene.MENU, plan="press A", created_at=NOW, steps=[GameAction.PRESS_A]
        )

    turn = _page_turn(plan, _signals(dialog_changed=True, text_box=True), refresh_plan=refresh)
    assert looked == [1]
    assert turn.looks == ["plan spent"]
    assert turn.actions[0] == GameAction.PRESS_A


def test_battle_narration_is_paged_by_the_battle_agent_without_a_look():
    from nuzlocke.state.models import AgentRole

    plan = _plan(scene=PlanScene.BATTLE, plan="SCRATCH", spent=True)
    turn = choose_fast_action(
        plan=plan,
        obs=_obs(in_battle=True),
        signals=_signals(dialog_changed=True, text_box=True),
        now=NOW,
        plan_every_s=45,
        stale_noul=0.7,
        confidence_floor=0.55,
        low_confidence_streak=0,
        jev_decide=lambda state, questions: _answers("press_a"),
        refresh_plan=_no_look,
    )
    assert turn.actions == [GameAction.SKIP_DIALOG]
    assert turn.agent == AgentRole.BATTLE


def test_a_battle_yes_no_still_gets_a_look():
    """'Will RED change POKéMON?' — B answers NO."""
    plan = _plan(scene=PlanScene.BATTLE, plan="SCRATCH", spent=True)
    looked: list[int] = []

    def refresh() -> PlanCard:
        looked.append(1)
        return _plan(scene=PlanScene.BATTLE, plan="NO", created_at=NOW, steps=[GameAction.PRESS_B])

    choose_fast_action(
        plan=plan,
        obs=_obs(in_battle=True),
        signals=_signals(dialog_changed=True, text_box=True, prompt_box=True),
        now=NOW,
        plan_every_s=45,
        stale_noul=0.7,
        confidence_floor=0.55,
        low_confidence_streak=0,
        jev_decide=lambda state, questions: _answers("press_b"),
        refresh_plan=refresh,
    )
    assert looked == [1]


def test_a_planned_battle_step_belongs_to_the_battle_agent():
    """The arbiter rejected every planned A in the rival battle as overworld's."""
    from nuzlocke.state.models import AgentRole

    plan = _plan(scene=PlanScene.BATTLE, plan="open FIGHT", steps=[GameAction.PRESS_A])
    turn = choose_fast_action(
        plan=plan,
        obs=_obs(in_battle=True),
        signals=_signals(),
        now=NOW,
        plan_every_s=45,
        stale_noul=0.7,
        confidence_floor=0.55,
        low_confidence_streak=0,
        jev_decide=lambda state, questions: _answers("press_a"),
        refresh_plan=_no_look,
    )
    assert turn.actions[0] == GameAction.PRESS_A
    assert turn.agent == AgentRole.BATTLE


def test_a_forced_look_is_logged_with_its_reason():
    looked: list[int] = []

    def refresh() -> PlanCard:
        looked.append(1)
        return _plan(plan="walk left", created_at=NOW, steps=[GameAction.WALK_LEFT])

    turn = _page_turn(_plan(), _signals(), refresh_plan=refresh, force_replan="a walk did not move")
    assert looked == [1]
    assert turn.looks == ["a walk did not move"]


def test_a_mash_that_changed_nothing_goes_to_the_plan():
    plan = _plan(
        scene=PlanScene.DIALOG,
        plan="Press A on this box.",
        text_box=True,
        steps=[GameAction.PRESS_A],
    )

    def jev_decide(state, questions):
        raise AssertionError("the plan names the button")

    turn = choose_fast_action(
        plan=plan,
        obs=_obs(),
        signals=_signals(text_box=True),
        now=NOW,
        plan_every_s=45,
        stale_noul=0.7,
        confidence_floor=0.55,
        low_confidence_streak=0,
        mash_stalled=True,
        jev_decide=jev_decide,
        refresh_plan=lambda: (_ for _ in ()).throw(AssertionError("planner")),
    )
    assert turn.actions == [GameAction.PRESS_A, GameAction.WAIT_60]


def test_text_box_overrides_a_latched_walk():
    plan = _plan(plan="walk_right along the fence.")

    def jev_decide(state, questions):
        raise AssertionError("speech is one button")

    turn = choose_fast_action(
        plan=plan,
        obs=_obs(),
        signals=_signals(text_box=True),
        now=NOW,
        plan_every_s=45,
        stale_noul=0.7,
        confidence_floor=0.55,
        low_confidence_streak=0,
        heading="up",
        jev_decide=jev_decide,
        refresh_plan=lambda: (_ for _ in ()).throw(AssertionError("planner")),
    )
    assert turn.actions == [GameAction.SKIP_DIALOG]
    assert turn.plan.scene == PlanScene.DIALOG


def test_named_overworld_button_does_not_ask_jev():
    plan = _plan(plan="walk_up once onto the grass gap.")

    def jev_decide(state, questions):
        raise AssertionError("a named walk is pressed in code")

    turn = choose_fast_action(
        plan=plan,
        obs=_obs(),
        signals=_signals(),
        now=NOW,
        plan_every_s=45,
        stale_noul=0.7,
        confidence_floor=0.55,
        low_confidence_streak=0,
        jev_decide=jev_decide,
        refresh_plan=lambda: (_ for _ in ()).throw(AssertionError("planner")),
    )
    assert turn.actions == [GameAction.WALK_UP]
    assert turn.actions != [GameAction.PRESS_B]


def test_blocked_named_walk_sidesteps_instead_of_pressing_b():
    plan = _plan(plan="walk_down once onto the open ground below the player.")

    def jev_decide(state, questions):
        raise AssertionError("sidestep does not ask Jev")

    turn = choose_fast_action(
        plan=plan,
        obs=_obs(),
        signals=_signals(),
        now=NOW,
        plan_every_s=45,
        stale_noul=0.7,
        confidence_floor=0.55,
        low_confidence_streak=0,
        blocked_on_tile=["walk_down"],
        jev_decide=jev_decide,
        refresh_plan=lambda: (_ for _ in ()).throw(AssertionError("planner")),
    )
    assert turn.actions == [GameAction.WALK_LEFT]
    assert turn.plan.spent is True
    assert replan_reason(turn.plan, _obs(), _signals(), now=NOW, plan_every_s=45) == "plan spent"


def test_naming_low_confidence_waits_instead_of_pressing_b():
    plan = _plan(scene=PlanScene.NAMING)
    obs = _obs(joy_ignore=0x40)
    turn, planned = _turn(plan, obs, _signals(), [_answers("press_a", confidence=0.1)])
    assert planned == 0
    assert turn.actions == [GameAction.WAIT_60]
