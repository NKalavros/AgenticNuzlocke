from nuzlocke.orchestration.stuck import (
    StuckTracker,
    filter_repeated_noops,
    perpendicular_sidestep,
)
from nuzlocke.state.models import GameAction, PlayerObservation


def _obs(**kw):
    return PlayerObservation(**kw)


def test_update_position_raises_stuck_score_on_same_tile_dwell():
    tracker = StuckTracker(same_tile_window=3)
    tracker.no_progress_streak = 2
    for _ in range(3):
        tracker.update_position(_obs(map_name="Pallet Town", x=5, y=5))
    assert tracker.stuck_score >= 1


def test_pause_for_cutscene_clears_stuck_but_keeps_the_tile():
    tracker = StuckTracker()
    tracker.no_progress_streak = 12
    tracker.noop_streak = 4
    tracker.stuck_score = 10
    tracker.same_tile_streak = 8
    tracker.pause_for_cutscene()
    assert tracker.no_progress_streak == 0
    assert tracker.noop_streak == 0
    assert tracker.stuck_score == 0
    assert tracker.same_tile_streak == 8
    assert tracker.escalation_tier() == 0


def test_same_tile_dwell_does_not_score_while_the_picture_is_changing():
    tracker = StuckTracker(same_tile_window=3)
    for _ in range(3):
        tracker.update_position(_obs(map_name="Pallet Town", x=5, y=5))
    assert tracker.stuck_score == 0


def test_update_position_does_not_accumulate_during_dialog_or_battle():
    tracker = StuckTracker(same_tile_window=3)
    for _ in range(3):
        tracker.update_position(_obs(map_name="Pallet Town", x=5, y=5, dialog_active=True))
    assert tracker.stuck_score == 0


def test_update_position_decays_when_moving():
    tracker = StuckTracker(same_tile_window=3)
    tracker.stuck_score = 2
    tracker.update_position(_obs(map_name="Pallet Town", x=6, y=5))
    assert tracker.stuck_score == 1


def test_record_result_noop_when_fingerprint_unchanged():
    tracker = StuckTracker()
    obs = _obs(map_name="Pallet Town", x=5, y=5)
    fp = tracker.fingerprint(obs)
    is_noop = tracker.record_result(fp, fp, executed=True)
    assert is_noop is True
    assert tracker.noop_streak == 1
    assert tracker.stuck_score == 1


def test_record_result_resets_streak_when_state_changes():
    tracker = StuckTracker()
    tracker.noop_streak = 3
    before = tracker.fingerprint(_obs(map_name="Pallet Town", x=5, y=5))
    after = tracker.fingerprint(_obs(map_name="Pallet Town", x=6, y=5))
    is_noop = tracker.record_result(before, after, executed=True)
    assert is_noop is False
    assert tracker.noop_streak == 0


def test_record_result_not_noop_when_nothing_executed():
    tracker = StuckTracker()
    obs = _obs(map_name="Pallet Town", x=5, y=5)
    fp = tracker.fingerprint(obs)
    is_noop = tracker.record_result(fp, fp, executed=False)
    assert is_noop is False
    assert tracker.noop_streak == 0


def test_discount_never_goes_below_zero():
    tracker = StuckTracker()
    tracker.stuck_score = 1
    tracker.discount(5)
    assert tracker.stuck_score == 0


def test_two_tile_ping_pong_raises_loop_streak():
    tracker = StuckTracker(same_tile_window=4, position_window=8)
    pal = _obs(map_name="Pallet Town", x=2, y=7)
    house = _obs(map_name="Red's House 1F", x=3, y=7)
    for i in range(4):
        tracker.update_position(pal if i % 2 == 0 else house)
    assert tracker.is_position_oscillation()
    tracker.stuck_score = 3
    tracker.update_position(pal)
    tracker.update_position(house)
    assert tracker.stuck_score == 3  # ping-pong must not decay
    before = tracker.fingerprint(pal)
    after = tracker.fingerprint(house)
    tracker.record_result(before, after, executed=True, actions=["walk_down"])
    assert tracker.noop_streak == 0
    assert tracker.loop_streak == 1
    assert tracker.stuck_score >= 4


def test_action_oscillation_raises_loop_streak():
    tracker = StuckTracker()
    left = _obs(map_name="Route 1", x=5, y=2)
    right = _obs(map_name="Route 1", x=7, y=2)
    pairs = [
        (left, right, ["walk_right_2"]),
        (right, left, ["walk_left_2"]),
        (left, right, ["walk_right_2"]),
        (right, left, ["walk_left_2"]),
        (left, right, ["walk_right_2"]),
        (right, left, ["walk_left_2"]),
    ]
    for before, after, acts in pairs:
        tracker.record_result(
            tracker.fingerprint(before),
            tracker.fingerprint(after),
            executed=True,
            actions=acts,
        )
    assert tracker.is_action_oscillation()
    assert tracker.loop_streak >= 3
    assert tracker.noop_streak == 0
    assert not tracker.needs_recovery()


def test_three_tile_fence_wiggle_is_position_oscillation():
    tracker = StuckTracker(same_tile_window=6, position_window=8)
    xs = [1, 2, 3, 2, 1, 2]
    for x in xs:
        tracker.update_position(_obs(map_name="Pallet Town", x=x, y=2))
    assert tracker.is_position_oscillation()
    tracker.stuck_score = 2
    tracker.update_position(_obs(map_name="Pallet Town", x=3, y=2))
    assert tracker.stuck_score == 2  # confined wiggle must not decay
    before = tracker.fingerprint(_obs(map_name="Pallet Town", x=1, y=2))
    after = tracker.fingerprint(_obs(map_name="Pallet Town", x=3, y=2))
    tracker.record_result(before, after, executed=True, actions=["walk_right_2"])
    assert tracker.loop_streak >= 1
    assert not tracker.needs_guide()


def test_record_result_records_failed_approach_on_noop():
    tracker = StuckTracker()
    obs = _obs(map_name="Pallet Town", x=9, y=2)
    fp = tracker.fingerprint(obs)
    tracker.record_result(fp, fp, executed=True, actions=["walk_up_2"])
    assert tracker.failed_approaches == [["walk_up_2"]]
    tracker.record_result(fp, fp, executed=True, actions=["walk_up_2"])
    assert tracker.failed_approaches == [["walk_up_2"]]
    tracker.record_result(fp, fp, executed=True, actions=["walk_up"])
    assert tracker.failed_approaches[-1] == ["walk_up"]


def test_filter_replaces_exact_noop_with_sidestep():
    out = filter_repeated_noops(
        [GameAction.WALK_UP_2], [["walk_up_2"]], alternate=0
    )
    assert out == [GameAction.WALK_LEFT]


def test_filter_alternate_sidestep():
    out = filter_repeated_noops(
        [GameAction.WALK_UP], [["walk_up"]], alternate=1
    )
    assert out == [GameAction.WALK_RIGHT]


def test_filter_strips_failed_prefix_and_keeps_rest():
    out = filter_repeated_noops(
        [GameAction.WALK_UP, GameAction.PRESS_A],
        [["walk_up"]],
        alternate=0,
    )
    assert out == [GameAction.PRESS_A]


def test_perpendicular_sidestep_for_non_walk_is_left():
    assert perpendicular_sidestep(["press_a"]) == GameAction.WALK_LEFT


def test_filter_does_not_rewrite_button_macros():
    out = filter_repeated_noops(
        [GameAction.PRESS_START, GameAction.PRESS_A],
        [["press_a"], ["press_start", "press_a"], ["skip_dialog"]],
        alternate=0,
    )
    assert out == [GameAction.PRESS_START, GameAction.PRESS_A]


def test_record_result_does_not_ban_button_noops():
    tracker = StuckTracker()
    obs = _obs(map_name="Pallet Town", x=0, y=0)
    fp = tracker.fingerprint(obs)
    tracker.record_result(fp, fp, executed=True, actions=["press_a"])
    assert tracker.failed_approaches == []
    tracker.record_result(fp, fp, executed=True, actions=["walk_up_2"])
    assert tracker.failed_approaches == [["walk_up_2"]]


def test_advise_recovery_replaces_failed_walk():
    from nuzlocke.agents.roles import advise_recovery
    from nuzlocke.llm.base import LLMProvider
    from nuzlocke.state.models import AgentRole, LLMResponse

    class FakeLLM(LLMProvider):
        name = "fake"

        def complete(
            self,
            *,
            role: AgentRole,
            system: str,
            user: str,
            schema_hint: dict | None = None,
            image_paths=None,
        ) -> LLMResponse:
            assert "failed_approaches" in user
            return LLMResponse(
                role=role,
                raw_text="{}",
                parsed={
                    "diagnosis": "fence post",
                    "proposed_actions": ["walk_up_2"],
                    "reason": "walk north",
                },
                model="fake",
                provider=self.name,
            )

    advice = advise_recovery(
        FakeLLM(),
        obs=_obs(map_name="Pallet Town", x=9, y=2),
        stuck_score=4,
        recent_positions=[],
        vision_only=True,
        failed_approaches=[["walk_up_2"]],
        loop_streak=0,
    )
    assert advice.proposed_actions == [GameAction.WALK_LEFT]

