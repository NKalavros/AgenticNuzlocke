"""World-region progress detection and the stuck escalation ladder.

Whole-frame hashing cannot see a dialogue loop: animating text changes the PNG
every cycle, so `noop_streak` sat at 0 through ~200 wasted steps in run
20260821-164159-3c5a68 while the agent re-opened Prof Oak forever. Splitting
the frame at the top of the text box makes that loop legible.
"""

from __future__ import annotations

import io

import pytest

from nuzlocke.environment import screen
from nuzlocke.orchestration.stuck import (
    IMMOBILE_DISENGAGE,
    NO_PROGRESS_DISENGAGE,
    NO_PROGRESS_RECOVERY,
    NO_PROGRESS_REFRAME,
    NO_PROGRESS_RESET,
    SAME_TILE_BUDGET,
    Fingerprint,
    StuckTracker,
    world_static,
)
from nuzlocke.state.models import GameAction, PlayerObservation


def _fp(*, world: str = "w", dialog: str = "d", x: int = 5) -> Fingerprint:
    return Fingerprint(
        map_name="Oak's Lab",
        x=x,
        y=3,
        facing="up",
        dialog_active=False,
        frame=world + dialog,
        world=world,
        dialog=dialog,
    )


def _frame_png(*, world_fill: int, dialog_fill: int) -> bytes:
    """A 160x144 frame: flat world region on top, flat text box underneath.

    Pillow only — NumPy ships with the optional `emu` extra, and the split has
    to work on a base install or the stuck detection silently stops working.
    """
    Image = pytest.importorskip("PIL.Image")
    img = Image.new("L", (screen.FRAME_W, screen.FRAME_H), world_fill)
    img.paste(
        Image.new("L", (screen.FRAME_W, screen.FRAME_H - screen.DIALOG_TOP), dialog_fill),
        (0, screen.DIALOG_TOP),
    )
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_text_box_change_alone_does_not_move_the_world_digest():
    a = screen.digests_from_bytes(_frame_png(world_fill=100, dialog_fill=10))
    b = screen.digests_from_bytes(_frame_png(world_fill=100, dialog_fill=200))
    assert a[0] == b[0]  # world region identical
    assert a[1] != b[1]  # only the text box moved


def test_world_change_moves_the_world_digest():
    a = screen.digests_from_bytes(_frame_png(world_fill=100, dialog_fill=10))
    b = screen.digests_from_bytes(_frame_png(world_fill=140, dialog_fill=10))
    assert a[0] != b[0]


def test_text_box_border_is_detected(tmp_path):
    Image = pytest.importorskip("PIL.Image")
    img = Image.new("L", (screen.FRAME_W, screen.FRAME_H), 255)
    for y in (98, 100, 138, 140):
        for x in range(8, 152):
            img.putpixel((x, y), 0)
    for y in range(101, 138):
        img.putpixel((8, y), 0)
        img.putpixel((151, y), 0)
    path = tmp_path / "box.png"
    img.save(path, format="PNG")
    assert screen.text_box_open(str(path))

    # Oak's lab roof sits in the text-box rows and is dark, but the black
    # pixels are a short band in the middle of the screen, not a full-width
    # frame. Run 20260927-235608-cc25eb pressed B there with nobody talking.
    building = Image.new("L", (screen.FRAME_W, screen.FRAME_H), 200)
    for y in (109, 111):
        for x in range(80, 144):
            building.putpixel((x, y), 0)
    for y in range(96, 128):
        building.putpixel((8, y), 0)
    building_path = tmp_path / "lab.png"
    building.save(building_path, format="PNG")
    assert not screen.text_box_open(str(building_path))

    plain = Image.new("L", (screen.FRAME_W, screen.FRAME_H), 120)
    plain_path = tmp_path / "grass.png"
    plain.save(plain_path, format="PNG")
    assert not screen.text_box_open(str(plain_path))

    # A fade to black is a full-width dark band with no white panel.
    # Run 20260928-205856-f65040 mashed skip_dialog on one.
    fade = Image.new("L", (screen.FRAME_W, screen.FRAME_H), 0)
    for y in range(0, 70, 4):
        for x in range(screen.FRAME_W):
            fade.putpixel((x, y), 255)
    fade_path = tmp_path / "fade.png"
    fade.save(fade_path, format="PNG")
    assert not screen.text_box_open(str(fade_path))
    world, dialog = screen.digests_from_bytes(b"not-a-png")
    assert world == dialog != "0"


def test_dialogue_loop_is_no_progress_even_though_it_is_not_a_noop():
    """The exact Oak shape: frame differs every cycle, world never does."""
    tracker = StuckTracker()
    for i in range(NO_PROGRESS_RECOVERY):
        before = _fp(dialog=f"page{i}")
        after = _fp(dialog=f"page{i + 1}")
        is_noop = tracker.record_result(before, after, executed=True, actions=["skip_dialog"])
        assert is_noop is False  # whole-frame hashing sees "progress"
    assert tracker.noop_streak == 0
    assert tracker.no_progress_streak == NO_PROGRESS_RECOVERY
    assert tracker.needs_recovery()


def test_real_movement_clears_the_no_progress_streak():
    tracker = StuckTracker()
    for i in range(5):
        tracker.record_result(
            _fp(dialog=f"p{i}"), _fp(dialog=f"p{i + 1}"), executed=True, actions=["press_a"]
        )
    assert tracker.no_progress_streak == 5
    tracker.record_result(
        _fp(x=5), _fp(world="elsewhere", x=6), executed=True, actions=["walk_right"]
    )
    assert tracker.no_progress_streak == 0
    assert tracker.no_progress_counts == {}


def test_nothing_executed_is_not_counted_as_no_progress():
    tracker = StuckTracker()
    fp = _fp()
    tracker.record_result(fp, fp, executed=False)
    assert tracker.no_progress_streak == 0


def test_repeated_actions_records_button_macros_for_the_prompt():
    """failed_approaches stays walk-only; this is the evidence channel."""
    tracker = StuckTracker()
    for i in range(4):
        tracker.record_result(
            _fp(dialog=f"p{i}"), _fp(dialog=f"p{i + 1}"), executed=True, actions=["skip_dialog"]
        )
    assert tracker.failed_approaches == []  # filter must not learn to ban B/A
    assert tracker.repeated_actions() == [{"actions": ["skip_dialog"], "times_without_progress": 4}]


def test_escalation_tiers_climb_with_the_streak():
    tracker = StuckTracker()
    assert tracker.escalation_tier() == 0
    tracker.no_progress_streak = NO_PROGRESS_DISENGAGE
    assert tracker.escalation_tier() == 2
    tracker.no_progress_streak = NO_PROGRESS_REFRAME
    assert tracker.escalation_tier() == 3
    tracker.no_progress_streak = NO_PROGRESS_RESET
    assert tracker.escalation_tier() == 4


def test_same_tile_budget_does_not_disengage_while_the_picture_changes():
    """A name menu and a cutscene hold RAM x,y while the screen still moves."""
    tracker = StuckTracker()
    obs = PlayerObservation(map_name="Red's House 2F", x=3, y=6)
    for _ in range(SAME_TILE_BUDGET + 1):
        tracker.update_position(obs)
    assert tracker.same_tile_streak >= SAME_TILE_BUDGET
    assert tracker.escalation_tier() == 0


def test_same_tile_budget_disengages_when_the_world_is_also_frozen():
    tracker = StuckTracker()
    tracker.no_progress_streak = 2
    obs = PlayerObservation(map_name="Oak's Lab", x=5, y=3)
    for _ in range(SAME_TILE_BUDGET + 1):
        tracker.update_position(obs)
    assert tracker.escalation_tier() >= 2


def test_same_tile_streak_resets_on_a_new_tile():
    tracker = StuckTracker()
    for _ in range(4):
        tracker.update_position(PlayerObservation(map_name="Route 1", x=5, y=3))
    assert tracker.same_tile_streak == 3
    tracker.update_position(PlayerObservation(map_name="Route 1", x=6, y=3))
    assert tracker.same_tile_streak == 0


def test_animated_shore_walk_is_immobile_without_a_frozen_picture():
    """Water changes the world digest, so the old ladder never left (8, 16)."""
    tracker = StuckTracker()
    for i in range(IMMOBILE_DISENGAGE):
        before = _fp(world=f"water{i}", x=8)
        after = _fp(world=f"water{i + 1}", x=8)
        is_noop = tracker.record_result(before, after, executed=True, actions=["walk_down"])
        assert is_noop is False
    assert tracker.noop_streak == 0
    assert tracker.no_progress_streak == 0
    assert tracker.failed_approaches == []
    assert tracker.immobile_streak == IMMOBILE_DISENGAGE
    assert tracker.blocked_on_tile == {"walk_down"}
    assert tracker.escalation_tier() >= 2
    actions = tracker.disengage_actions()
    assert GameAction.WALK_DOWN not in actions
    assert any(action.value.startswith("walk_") for action in actions)


def test_immobile_block_clears_when_the_tile_changes():
    tracker = StuckTracker()
    tracker.record_result(
        _fp(world="a", x=8), _fp(world="b", x=8), executed=True, actions=["walk_down"]
    )
    assert "walk_down" in tracker.blocked_on_tile
    tracker.record_result(
        _fp(world="b", x=8), _fp(world="c", x=7), executed=True, actions=["walk_left"]
    )
    assert tracker.immobile_streak == 0
    assert tracker.blocked_on_tile == set()


def test_four_blocked_sides_are_a_held_input_not_walls():
    """The rival's cutscene refused every walk; the tile is not a closed box."""
    tracker = StuckTracker()
    for step in ("walk_down", "walk_left", "walk_right"):
        tracker.record_result(_fp(x=6), _fp(x=6), executed=True, actions=[step])
    assert tracker.blocked_on_tile == {"walk_down", "walk_left", "walk_right"}
    tracker.record_result(_fp(x=6), _fp(x=6), executed=True, actions=["walk_up"])
    assert tracker.blocked_on_tile == set()


def test_a_text_box_retries_the_blocked_directions():
    tracker = StuckTracker()
    tracker.record_result(_fp(x=6), _fp(x=6), executed=True, actions=["walk_down"])
    assert tracker.blocked_on_tile == {"walk_down"}
    tracker.pause_for_cutscene()
    assert tracker.blocked_on_tile == set()


def test_dialog_walk_does_not_block_the_tile():
    tracker = StuckTracker()
    tracker.record_result(
        _fp(world="a", x=8),
        _fp(world="b", x=8),
        executed=True,
        actions=["walk_up"],
        allow_immobile=False,
    )
    assert tracker.immobile_streak == 0
    assert tracker.blocked_on_tile == set()


def test_disengage_rotates_so_a_blocked_direction_is_not_retried():
    tracker = StuckTracker()
    first = tracker.disengage_actions()
    second = tracker.disengage_actions()
    assert first[0] == second[0] == GameAction.PRESS_B  # always close the box
    assert first != second


def test_hard_reset_clears_every_streak():
    tracker = StuckTracker()
    tracker.no_progress_streak = 50
    tracker.stuck_score = 30
    tracker.same_tile_streak = 40
    tracker.no_progress_counts[("press_a",)] = 12
    tracker.hard_reset()
    assert tracker.escalation_tier() == 0
    assert tracker.no_progress_counts == {}


def test_world_static_ignores_dialog_but_not_position():
    assert world_static(_fp(dialog="a"), _fp(dialog="b")) is True
    assert world_static(_fp(x=5), _fp(x=6)) is False
    assert world_static(_fp(world="a"), _fp(world="b")) is False


def test_no_progress_evidence_reaches_the_recovery_prompt():
    """Recovery was flying blind: the old prompt had no field for this at all."""
    from nuzlocke.agents.roles import advise_recovery
    from nuzlocke.llm.base import LLMProvider
    from nuzlocke.state.models import LLMResponse

    seen: dict[str, str] = {}

    class FakeLLM(LLMProvider):
        name = "fake"

        def complete(self, *, role, system, user, schema_hint=None, image_paths=None):
            seen["user"] = user
            seen["system"] = system
            return LLMResponse(
                role=role,
                raw_text="{}",
                parsed={"diagnosis": "loop", "proposed_actions": ["press_b"]},
                model="fake",
                provider=self.name,
            )

    advise_recovery(
        FakeLLM(),
        obs=PlayerObservation(map_name="Oak's Lab", x=5, y=3),
        stuck_score=14,
        recent_positions=[],
        vision_only=True,
        no_progress={
            "streak": 21,
            "repeated_actions": [{"actions": ["skip_dialog"], "times_without_progress": 11}],
        },
        reframe=True,
    )

    assert "no_progress" in seen["user"]
    assert "21" in seen["user"]
    assert "ALREADY COMPLETE" in seen["user"]  # the reframe brief


def test_naming_keyboard_is_stated_outright_in_vision_only():
    """joy_ignore bit 6 held up all run; the agent was never told about it."""
    from nuzlocke.agents.roles import _obs_payload

    grid = _obs_payload(
        PlayerObservation(map_name="Red's House 2F", joy_ignore=0x40), vision_only=True
    )
    assert "NAMING KEYBOARD" in grid["hard_signal"]

    # Bit 5 stays out — it reads 0 through real dialog on Red Star.
    dialog = _obs_payload(
        PlayerObservation(map_name="Oak's Lab", joy_ignore=0x20), vision_only=True
    )
    assert "hard_signal" not in dialog
