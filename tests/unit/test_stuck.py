from nuzlocke.orchestration.stuck import StuckTracker
from nuzlocke.state.models import PlayerObservation


def _obs(**kw):
    return PlayerObservation(**kw)


def test_update_position_raises_stuck_score_on_same_tile_dwell():
    tracker = StuckTracker(same_tile_window=3)
    for _ in range(3):
        tracker.update_position(_obs(map_name="Pallet Town", x=5, y=5))
    assert tracker.stuck_score >= 1


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
