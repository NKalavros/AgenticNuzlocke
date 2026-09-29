"""Prompts are answered, planned paths run without a look per tile, and a walk
grid that disagrees with real movement is withheld.

Run 20260927-235608-cc25eb spent 85% of its active time waiting on the vision
planner, mostly one call per button. On the emulator from that run's
savestate, one B at the starter's YES/NO declines the Pokémon, so the paths
that page text without a look must stop at a prompt.
"""

from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest

from nuzlocke.agents.jev_policy import FrameSignals, choose_fast_action, replan_reason
from nuzlocke.agents.locomotion import GridTrust
from nuzlocke.agents.roles import _images, parse_steps
from nuzlocke.environment import screen
from nuzlocke.environment.nous_red import A_SETTLE, SCENE_ROUND, NousRedEnvironment
from nuzlocke.llm.jev import JevAnswers
from nuzlocke.orchestration.stuck import StuckTracker
from nuzlocke.state.models import GameAction, PlanCard, PlanScene, PlayerObservation

NOW = 1_000.0

# The Oak's Lab grid pokemon-agent drew while the player walked freely.
_ALL_BLOCKED = "\n".join(
    [" ".join("ABCDEFGHIJ")]
    + [
        f"{r} " + " ".join("@" if (r, c) == (5, 4) else "#" for c in range(10))
        for r in range(1, 10)
    ]
)
_OPEN_RIGHT = _ALL_BLOCKED.replace("@ #", "@ .", 1)


def _obs(**kwargs) -> PlayerObservation:
    base: dict = {
        "map_name": "Oak's Lab",
        "map_id": 40,
        "x": 5,
        "y": 3,
        "facing": "up",
        "raw_player": {"name": "RED"},
    }
    base.update(kwargs)
    return PlayerObservation(**base)


def _plan(**kwargs) -> PlanCard:
    base: dict = {
        "scene": PlanScene.OVERWORLD,
        "see": "Oak's lab, balls right of Oak",
        "plan": "go below the first ball and pick it",
        "world_digest": "world",
        "created_at": NOW,
    }
    base.update(kwargs)
    return PlanCard(**base)


def _signals(
    *, text_box: bool = False, prompt_box: bool = False, dialog: str = "dlg"
) -> FrameSignals:
    return FrameSignals("world", dialog, False, False, text_box, prompt_box)


def _turn(plan, signals, *, obs=None, jev=None, refresh=None, **kwargs):
    def no_jev(state, questions):
        raise AssertionError("jev should not be asked")

    def no_planner():
        raise AssertionError("planner should not run")

    return choose_fast_action(
        plan=plan,
        obs=obs or _obs(),
        signals=signals,
        now=NOW,
        plan_every_s=45,
        stale_noul=0.7,
        confidence_floor=0.55,
        low_confidence_streak=0,
        jev_decide=jev or no_jev,
        refresh_plan=refresh or no_planner,
        **kwargs,
    )


# --- frames -----------------------------------------------------------------


def _frame(
    tmp_path: Path, name: str, *, text_box: bool, yes_no: bool = False, void: bool = False
) -> str:
    Image = pytest.importorskip("PIL.Image")
    img = Image.new("L", (screen.FRAME_W, screen.FRAME_H), 255)
    if text_box:
        for y in (98, 100, 138, 140):
            for x in range(8, 152):
                img.putpixel((x, y), 0)
        for y in range(101, 138):
            img.putpixel((8, y), 0)
            img.putpixel((151, y), 0)
    if yes_no:
        # Gen 1 menu border: two dark lines one pixel apart, the box's height.
        for y in range(58, 94):
            for x in (114, 116, 154, 156):
                img.putpixel((x, y), 0)
        for x in range(114, 157):
            for y in (58, 61, 90, 93):
                img.putpixel((x, y), 0)
    if void:
        # The black map edge beside Oak's lab: solid, not a double line.
        for y in range(screen.DIALOG_TOP):
            for x in range(128, 160):
                img.putpixel((x, y), 0)
    path = tmp_path / name
    img.save(path, format="PNG")
    return str(path)


def test_yes_no_above_the_text_box_is_a_prompt(tmp_path):
    assert screen.prompt_box_open(_frame(tmp_path, "yn.png", text_box=True, yes_no=True))


def test_plain_text_and_the_black_map_edge_are_not_prompts(tmp_path):
    assert not screen.prompt_box_open(_frame(tmp_path, "t.png", text_box=True))
    assert not screen.prompt_box_open(_frame(tmp_path, "v.png", text_box=True, void=True))


def test_a_menu_without_a_text_box_is_not_a_prompt(tmp_path):
    """The START menu is a box too, but nobody asked a question."""
    assert not screen.prompt_box_open(_frame(tmp_path, "m.png", text_box=False, yes_no=True))


def test_the_blinking_more_arrow_does_not_change_the_dialog_digest():
    Image = pytest.importorskip("PIL.Image")

    def png(arrow: bool) -> bytes:
        img = Image.new("L", (screen.FRAME_W, screen.FRAME_H), 255)
        if arrow:
            # Vanilla tile and the lower arrow Red Star draws on Oak's intro.
            for y in (129, 138):
                for x in range(145, 151):
                    img.putpixel((x, y), 0)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    assert screen.digests_from_bytes(png(True))[1] == screen.digests_from_bytes(png(False))[1]


# --- skip_dialog --------------------------------------------------------------


def test_skip_dialog_does_not_press_into_a_prompt(tmp_path: Path):
    env = NousRedEnvironment(
        base_url="http://127.0.0.1:8765", run_dir=tmp_path, auto_start=False, press_interval_s=0.0
    )
    env._client = MagicMock()
    env.observe = MagicMock(return_value=None)  # type: ignore[method-assign]
    env._joy_ignore = MagicMock(return_value=0)  # type: ignore[method-assign]
    env._mash_frame = MagicMock(return_value=("x", True))  # type: ignore[method-assign]
    env._prompt_up = MagicMock(return_value=True)  # type: ignore[method-assign]

    env.execute_skip_dialog()

    posted = [c for c in env._client.post.call_args_list if c.args[0].endswith("/action")]
    assert posted == []


# --- prompts in the fast policy -------------------------------------------------


def test_a_new_prompt_is_read_before_anything_is_pressed():
    prompt = _signals(text_box=True, prompt_box=True)
    plan = _plan(scene=PlanScene.DIALOG, text_box=True)
    assert replan_reason(plan, _obs(), prompt, now=NOW, plan_every_s=45) == "new prompt"
    seen = _plan(scene=PlanScene.DIALOG, text_box=True, prompt_digest="dlg")
    assert replan_reason(seen, _obs(), prompt, now=NOW, plan_every_s=45) is None
    # The nickname question after the starter is a different prompt.
    nickname = _signals(text_box=True, prompt_box=True, dialog="nickname?")
    assert replan_reason(seen, _obs(), nickname, now=NOW, plan_every_s=45) == "new prompt"


def test_a_prompt_is_never_paged_with_b():
    plan = _plan(scene=PlanScene.DIALOG, text_box=True, prompt_digest="dlg", plan="Accept it.")
    asked: dict = {}

    def jev(state, questions):
        asked["menu"] = set(questions["action"]["criteria"])
        return JevAnswers("press_a", 0.9, 0.0, 0.0, "jev")

    turn = _turn(plan, _signals(text_box=True, prompt_box=True), jev=jev)
    assert "press_a" in asked["menu"]  # the menu, not the B-only dialog menu
    assert "skip_dialog" not in asked["menu"]
    assert turn.actions == [GameAction.PRESS_A]


def test_unsure_at_a_prompt_confirms():
    plan = _plan(scene=PlanScene.DIALOG, text_box=True, prompt_digest="dlg", plan="Accept it.")
    turn = _turn(
        plan,
        _signals(text_box=True, prompt_box=True),
        jev=lambda s, q: JevAnswers("press_b", 0.2, 0.0, 0.0, "jev"),
    )
    assert turn.actions == [GameAction.PRESS_A]


def test_planned_yes_is_pressed_then_the_next_line_prints():
    plan = _plan(
        scene=PlanScene.MENU, text_box=True, prompt_digest="dlg", steps=[GameAction.PRESS_A]
    )
    turn = _turn(plan, _signals(text_box=True, prompt_box=True))
    assert turn.actions == [GameAction.PRESS_A, GameAction.WAIT_60]
    assert turn.plan.spent is True


# --- planned paths ----------------------------------------------------------------


def test_a_planned_path_is_one_burst_without_a_look():
    plan = _plan(
        steps=[GameAction.WALK_DOWN, GameAction.WALK_RIGHT, GameAction.WALK_UP, GameAction.PRESS_A]
    )
    assert replan_reason(plan, _obs(), _signals(), now=NOW, plan_every_s=45) is None
    turn = _turn(plan, _signals())
    assert turn.actions == [
        GameAction.WALK_DOWN,
        GameAction.WALK_RIGHT,
        GameAction.WALK_UP,
        GameAction.PRESS_A,
    ]
    assert turn.plan.steps == []
    assert turn.plan.spent is True
    assert replan_reason(turn.plan, _obs(), _signals(), now=NOW, plan_every_s=45) == "plan spent"


def test_a_text_box_under_a_walking_path_is_paged_not_walked():
    plan = _plan(steps=[GameAction.WALK_UP, GameAction.WALK_UP])
    turn = _turn(plan, _signals(text_box=True))
    assert turn.actions == [GameAction.SKIP_DIALOG]
    assert turn.plan.steps == []


def test_naming_steps_type_then_finish():
    plan = _plan(scene=PlanScene.NAMING, steps=[GameAction.PRESS_A, GameAction.PRESS_START])
    obs = _obs(joy_ignore=0x40)
    first = _turn(plan, _signals(text_box=True), obs=obs)
    second = _turn(first.plan, _signals(text_box=True), obs=obs)
    assert first.actions[0] == GameAction.PRESS_A
    assert second.actions[0] == GameAction.PRESS_START
    assert second.plan.spent is True


def test_parse_steps_expands_macros_caps_length_and_drops_junk():
    assert parse_steps(["walk_up_3", "PRESS_A", "fly", "skip_dialog"]) == [
        GameAction.WALK_UP,
        GameAction.WALK_UP,
        GameAction.WALK_UP,
        GameAction.PRESS_A,
    ]
    assert len(parse_steps(["walk_left"] * 20)) == 6
    assert parse_steps("walk_up") == []


# --- turning ----------------------------------------------------------------------


def test_a_walk_that_only_turns_is_not_a_failed_walk():
    tracker = StuckTracker()
    facing_right = tracker.fingerprint(_obs(x=6, y=4, facing="right"))
    facing_up = tracker.fingerprint(_obs(x=6, y=4, facing="up"))
    tracker.record_result(facing_right, facing_up, executed=True, actions=["walk_up"])
    assert tracker.immobile_streak == 0
    assert "walk_up" not in tracker.blocked_on_tile
    tracker.record_result(facing_up, facing_up, executed=True, actions=["walk_up"])
    assert tracker.immobile_streak == 1
    assert "walk_up" in tracker.blocked_on_tile


# --- walk grid trust --------------------------------------------------------------


def test_walking_onto_a_hash_tile_twice_withholds_that_maps_grid():
    trust = GridTrust()
    before = _obs(collision_ascii=_ALL_BLOCKED)
    after = _obs(x=6, y=3, facing="right", collision_ascii=_ALL_BLOCKED)
    assert trust.record(before, after, ["walk_right"]) is False
    assert trust.view(before).collision_ascii == _ALL_BLOCKED
    assert trust.record(before, after, ["walk_right"]) is True
    assert trust.view(before).collision_ascii is None
    # Another map keeps its grid.
    pallet = _obs(map_name="Pallet Town", map_id=0, collision_ascii=_ALL_BLOCKED)
    assert trust.view(pallet).collision_ascii == _ALL_BLOCKED


def test_a_burst_onto_hash_tiles_withholds_that_maps_grid():
    trust = GridTrust()
    before = _obs(collision_ascii=_ALL_BLOCKED)
    steps = [
        {
            "action": "walk_right",
            "x0": 5,
            "y0": 3,
            "x1": 6,
            "y1": 3,
            "map_name": "Oak's Lab",
            "map_id": 40,
        },
        {
            "action": "walk_right",
            "x0": 6,
            "y0": 3,
            "x1": 7,
            "y1": 3,
            "map_name": "Oak's Lab",
            "map_id": 40,
        },
    ]
    assert trust.record_path(before, steps) is True
    assert trust.view(before).collision_ascii is None


def test_a_burst_step_that_does_not_move_is_not_a_strike():
    trust = GridTrust()
    before = _obs(collision_ascii=_ALL_BLOCKED)
    stuck = [
        {
            "action": "walk_right",
            "x0": 5,
            "y0": 3,
            "x1": 5,
            "y1": 3,
            "map_name": "Oak's Lab",
            "map_id": 40,
        }
    ]
    assert trust.record_path(before, stuck * 3) is False
    assert trust.view(before).collision_ascii == _ALL_BLOCKED


def test_grid_agreeing_with_movement_is_kept():
    trust = GridTrust()
    # # ahead and the player did not move: the grid was right.
    for _ in range(3):
        trust.record(_obs(collision_ascii=_ALL_BLOCKED), _obs(facing="right"), ["walk_right"])
    # . ahead and the player moved: also right.
    trust.record(_obs(collision_ascii=_OPEN_RIGHT), _obs(x=6), ["walk_right"])
    # A door mat reads # and warps: a map change is never a strike.
    trust.record(
        _obs(collision_ascii=_ALL_BLOCKED),
        _obs(map_name="Pallet Town", map_id=0, x=6),
        ["walk_right"],
    )
    assert trust.view(_obs(collision_ascii=_ALL_BLOCKED)).collision_ascii == _ALL_BLOCKED


# --- vision frame -------------------------------------------------------------------


def test_vision_calls_attach_the_grid_frame(tmp_path: Path):
    env = NousRedEnvironment(
        base_url="http://127.0.0.1:8765", run_dir=tmp_path, auto_start=False, press_interval_s=0.0
    )
    env._client = MagicMock()
    env._client.get = MagicMock(
        return_value=MagicMock(content=b"grid-png", raise_for_status=lambda: None)
    )
    native = tmp_path / "native.png"
    native.write_bytes(b"png")

    obs = env.vision_frame(_obs(screenshot_path=str(native)))

    assert obs.vision_path is not None
    assert Path(obs.vision_path).read_bytes() == b"grid-png"
    assert env._client.get.call_args.args[0].endswith("/screenshot/grid")
    assert _images(obs) == [Path(obs.vision_path)]


def _burst_env(tmp_path: Path) -> tuple[NousRedEnvironment, dict[str, int], list[list[str]]]:
    env = NousRedEnvironment(
        base_url="http://127.0.0.1:8765", run_dir=tmp_path, auto_start=False, press_interval_s=0.0
    )
    pos = {"x": 5, "y": 5, "map": "Pallet Town", "joy": 0, "battle": 0, "facing": "down"}
    posted: list[list[str]] = []

    def state() -> dict:
        return {
            "player": {
                "position": {"x": pos["x"], "y": pos["y"], "map_name": pos["map"]},
                "facing": pos["facing"],
                "name": "RED",
            },
            "map": {"map_name": pos["map"], "map_id": 0},
            "dialog": {"active": False, "joy_ignore": pos["joy"], "text": None},
            "battle": {
                "in_battle": bool(pos["battle"]),
                "type": "wild" if pos["battle"] else "none",
            },
            "party": [],
            "bag": [],
            "metadata": {"frame_count": 1},
        }

    def get(url: str, **kwargs: object) -> MagicMock:
        return MagicMock(status_code=200, json=state, raise_for_status=lambda: None)

    def post(url: str, json: dict | None = None, **kwargs: object) -> MagicMock:
        actions = list((json or {}).get("actions") or [])
        posted.append(actions)
        if actions == ["walk_up"]:
            pos["y"] -= 1
        elif actions == ["walk_right"]:
            pos["x"] += 1
        return MagicMock(content=b"{}", json=dict, raise_for_status=lambda: None)

    env._client = MagicMock()
    env._client.get = MagicMock(side_effect=get)
    env._client.post = MagicMock(side_effect=post)
    env.observe = MagicMock(return_value=_obs())  # type: ignore[method-assign]
    return env, pos, posted


def test_a_burst_stops_when_a_walk_does_not_move(tmp_path: Path):
    env, pos, posted = _burst_env(tmp_path)
    # The tile stays put, so the press_a planned for the far side of the path
    # is not sent.
    env._client.post = MagicMock(
        return_value=MagicMock(content=b"{}", json=dict, raise_for_status=lambda: None)
    )

    result = env.execute([GameAction.WALK_UP, GameAction.PRESS_A])

    assert result.executed == [GameAction.WALK_UP]
    assert result.stopped_early_because == "immobile"
    assert posted == [] or all(batch != ["press_a"] for batch in posted)
    posted_actions = [
        call.kwargs["json"]["actions"]
        for call in env._client.post.call_args_list
        if call.args and str(call.args[0]).endswith("/action")
    ]
    assert posted_actions == [["walk_up"]]
    assert pos["y"] == 5


def test_naming_steps_are_not_cut_short_when_the_tile_stays_put(tmp_path: Path):
    env, pos, posted = _burst_env(tmp_path)
    pos["joy"] = 0x40

    result = env.execute([GameAction.WALK_LEFT, GameAction.WALK_LEFT, GameAction.PRESS_START])

    assert [batch[0] for batch in posted] == ["walk_left", "walk_left", "press_start"]
    assert result.stopped_early_because is None
    assert result.walks == []


def test_a_text_box_stops_the_burst_before_press_a(tmp_path: Path):
    env, _pos, posted = _burst_env(tmp_path)
    frames = {"n": 0}

    def screenshot(path: str | None = None) -> bytes:
        frames["n"] += 1
        # The opening check is a clear overworld. The check after the first
        # walk finds Oak's text, so the press_a is not sent.
        target = tmp_path / f"frame-{frames['n']}.png"
        _frame(tmp_path, target.name, text_box=frames["n"] >= 2)
        data = target.read_bytes()
        if path:
            Path(path).write_bytes(data)
        return data

    env.screenshot = screenshot  # type: ignore[method-assign]

    result = env.execute([GameAction.WALK_UP, GameAction.PRESS_A])

    assert [batch[0] for batch in posted] == ["walk_up"]
    assert result.stopped_early_because == "text_box"


def test_dialog_active_does_not_stop_a_moving_burst(tmp_path: Path):
    env, pos, posted = _burst_env(tmp_path)

    def post(url: str, json: dict | None = None, **kwargs: object) -> MagicMock:
        actions = list((json or {}).get("actions") or [])
        posted.append(actions)
        if actions == ["walk_right"]:
            pos["x"] += 1
        return MagicMock(content=b"{}", json=dict, raise_for_status=lambda: None)

    env._client.post = MagicMock(side_effect=post)
    # RAM says a dialog opened. The frame does not, and the player moved.
    real_get = env._client.get.side_effect

    def get(url: str, **kwargs: object) -> MagicMock:
        response = real_get(url, **kwargs)
        payload = response.json()
        if isinstance(payload, dict) and "dialog" in payload:
            payload = {**payload, "dialog": {**payload["dialog"], "active": True}}
            response.json = lambda payload=payload: payload
        return response

    env._client.get = MagicMock(side_effect=get)

    result = env.execute([GameAction.WALK_RIGHT, GameAction.WALK_RIGHT])

    assert [batch[0] for batch in posted] == ["walk_right", "walk_right"]
    assert result.stopped_early_because is None


def _press(posted: list[list[str]], pos: dict, moves: dict[str, tuple[str, int]]):
    """POST handler: ``moves`` maps an opcode to the position key it changes."""

    def post(url: str, json: dict | None = None, **kwargs: object) -> MagicMock:
        actions = list((json or {}).get("actions") or [])
        posted.append(actions)
        move = moves.get(actions[0]) if actions else None
        if move is not None:
            key, value = move
            pos[key] = value if key == "facing" else pos[key] + value
        return MagicMock(content=b"{}", json=dict, raise_for_status=lambda: None)

    return MagicMock(side_effect=post)


def test_a_walk_that_turns_to_face_the_ball_keeps_its_press_a(tmp_path: Path):
    """walk_up into the table turns the player; the A after it is the point."""
    env, pos, posted = _burst_env(tmp_path)
    env._client.post = _press(posted, pos, {"walk_up": ("facing", "up")})

    result = env.execute([GameAction.WALK_UP, GameAction.PRESS_A])

    assert posted == [["walk_up"], ["press_a", A_SETTLE]]
    assert result.stopped_early_because is None


def test_a_turn_toward_another_walk_still_stops_the_path(tmp_path: Path):
    env, pos, posted = _burst_env(tmp_path)
    env._client.post = _press(posted, pos, {"walk_up": ("facing", "up")})

    result = env.execute([GameAction.WALK_UP, GameAction.WALK_UP, GameAction.PRESS_A])

    assert posted == [["walk_up"]]
    assert result.stopped_early_because == "immobile"


def test_a_walk_held_by_a_scene_waits_and_tries_again(tmp_path: Path):
    """The rival walking to his ball: the player cannot move, the picture can."""
    env, pos, posted = _burst_env(tmp_path)
    frames = iter([("w0", False), ("w1", False), ("w2", False), ("w2", False), ("w2", False)])
    env._scene_frame = lambda: next(frames)  # type: ignore[method-assign]
    released = {"waits": 0}

    def post(url: str, json: dict | None = None, **kwargs: object) -> MagicMock:
        actions = list((json or {}).get("actions") or [])
        posted.append(actions)
        if actions == [SCENE_ROUND]:
            released["waits"] += 1
        elif actions == ["walk_down"] and released["waits"] >= 2:
            pos["y"] += 1
        elif actions == ["walk_right"]:
            pos["x"] += 1
        return MagicMock(content=b"{}", json=dict, raise_for_status=lambda: None)

    env._client.post = MagicMock(side_effect=post)

    result = env.execute([GameAction.WALK_DOWN, GameAction.WALK_RIGHT])

    assert posted == [["walk_down"], *[[SCENE_ROUND]] * 4, ["walk_down"], ["walk_right"]]
    assert result.stopped_early_because is None
    assert (pos["x"], pos["y"]) == (6, 6)
    assert result.walks[0]["y1"] == 6


def test_a_wall_gets_one_still_round_and_no_second_press(tmp_path: Path):
    env, _pos, posted = _burst_env(tmp_path)
    frames = iter([("w0", False), ("w0", False)])
    env._scene_frame = lambda: next(frames)  # type: ignore[method-assign]

    result = env.execute([GameAction.WALK_DOWN, GameAction.WALK_RIGHT])

    assert posted == [["walk_down"], [SCENE_ROUND]]
    assert result.stopped_early_because == "immobile"


def test_a_scene_that_starts_talking_stops_the_burst(tmp_path: Path):
    env, _pos, posted = _burst_env(tmp_path)
    frames = iter([("w0", False), ("w1", True)])
    env._scene_frame = lambda: next(frames)  # type: ignore[method-assign]

    result = env.execute([GameAction.WALK_DOWN, GameAction.WALK_DOWN])

    assert posted == [["walk_down"], [SCENE_ROUND]]
    assert result.stopped_early_because == "text_box"


def test_an_older_server_keeps_the_native_frame(tmp_path: Path):
    env = NousRedEnvironment(
        base_url="http://127.0.0.1:8765", run_dir=tmp_path, auto_start=False, press_interval_s=0.0
    )
    env._client = MagicMock()
    env._client.get = MagicMock(side_effect=httpx.ConnectError("no grid"))
    native = tmp_path / "native.png"
    native.write_bytes(b"png")

    obs = env.vision_frame(_obs(screenshot_path=str(native)))

    assert obs.vision_path is None
    assert _images(obs) == [native]
