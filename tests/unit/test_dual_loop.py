"""Dual mode uses Jev; the cursor provider still calls the overworld LLM."""

from __future__ import annotations

import tempfile
from pathlib import Path
from types import SimpleNamespace

from nuzlocke.agents.goals import RoomMap
from nuzlocke.agents.roles import make_task, propose_plan
from nuzlocke.llm.base import LLMProvider
from nuzlocke.orchestration.journal import Journal
from nuzlocke.orchestration.loop import RunLoop
from nuzlocke.state.models import (
    ActionProposal,
    AgentRole,
    DirectorDecision,
    GameAction,
    GameMode,
    LLMResponse,
    PlanCard,
    PlanScene,
    PlayerObservation,
    RecoveryAdvice,
)


class _Planner(LLMProvider):
    name = "planner"

    def complete(self, *, role, system, user, schema_hint=None, image_paths=None):
        return LLMResponse(
            role=role,
            raw_text="{}",
            parsed={
                "scene": "dialog",
                "see": "Oak is talking",
                "plan": "advance the text, then leave the lab",
                "do_not": ["press A on Oak"],
                "objectives": {"primary": "Leave Oak's Lab"},
            },
            model="fake",
            provider=self.name,
        )


def _context() -> dict:
    return {
        "memory": None,
        "recent": [],
        "vision_only": True,
        "walkthrough_hint": None,
        "objectives": {},
        "nuzlocke": {},
        "failed_approaches": None,
        "no_progress": None,
        "beat": None,
        "blocked_on_tile": [],
    }


def _decision() -> DirectorDecision:
    return DirectorDecision(
        mode=GameMode.OVERWORLD, owner=AgentRole.OVERWORLD, objective="go north"
    )


def _obs() -> PlayerObservation:
    return PlayerObservation(
        map_name="Pallet Town", x=1, y=2, party=[{"name": "Bulbasaur"}], raw_player={"name": "RED"}
    )


def _proposal(reason: str) -> ActionProposal:
    return ActionProposal(
        task_id="t", agent=AgentRole.OVERWORLD, reason=reason, actions=[GameAction.WALK_UP]
    )


def test_propose_plan_reads_the_card():
    card = propose_plan(_Planner(), obs=_obs(), vision_only=True, objective="go north")
    assert card.scene == PlanScene.DIALOG
    assert card.see == "Oak is talking"
    assert "leave the lab" in card.plan
    assert card.do_not == ["press A on Oak"]
    assert card.objectives is not None
    assert card.objectives.primary == "Leave Oak's Lab"


def test_cursor_path_calls_overworld(monkeypatch):
    loop = RunLoop.__new__(RunLoop)
    loop.jev = None
    loop.llm = _Planner()
    loop.stuck = SimpleNamespace(loop_streak=0)
    loop.env = SimpleNamespace(vision_frame=lambda obs: obs)
    seen: dict[str, object] = {}

    def fake_overworld(llm, **kwargs):
        seen["llm"] = llm
        return _proposal("overworld")

    monkeypatch.setattr("nuzlocke.orchestration.loop.propose_overworld", fake_overworld)
    proposal, used, pause = loop._select_proposal(
        tier=0,
        decision=_decision(),
        task=make_task(_decision()),
        obs=_obs(),
        steps=1,
        context=_context(),
    )
    assert seen["llm"] is loop.llm
    assert proposal is not None
    assert proposal.reason == "overworld"
    assert used is False
    assert pause is False


def test_dual_branch_calls_fast_actor_not_overworld(monkeypatch):
    loop = RunLoop.__new__(RunLoop)
    loop.jev = object()
    sentinel = _proposal("jev")

    def fake_fast(**kwargs):
        return sentinel

    def boom(*args, **kwargs):
        raise AssertionError("vision role should not run on the fast path")

    loop._fast_proposal = fake_fast  # type: ignore[method-assign]
    monkeypatch.setattr("nuzlocke.orchestration.loop.propose_overworld", boom)
    monkeypatch.setattr("nuzlocke.orchestration.loop.propose_battle", boom)
    proposal, used, pause = loop._select_proposal(
        tier=0,
        decision=_decision(),
        task=make_task(_decision()),
        obs=_obs(),
        steps=1,
        context=_context(),
    )
    assert proposal is sentinel
    assert used is False
    assert pause is False


def test_fast_path_sends_the_whole_overworld_path(monkeypatch):
    import time

    path = [GameAction.WALK_DOWN, GameAction.WALK_RIGHT, GameAction.WALK_UP, GameAction.PRESS_A]
    plan = PlanCard(
        scene=PlanScene.OVERWORLD,
        see="the door is south",
        plan="walk to the mat",
        world_digest="0",
        created_at=time.time(),
        steps=path,
    )
    loop = _fast_loop(plan, recent=[])

    def boom(*args, **kwargs):
        raise AssertionError("the path is already planned")

    monkeypatch.setattr("nuzlocke.orchestration.loop.propose_plan", boom)
    proposal = loop._fast_proposal(task=make_task(_decision()), obs=_obs(), context=_context())
    assert proposal.actions == path


def _fast_loop(plan: PlanCard | None, *, recent: list[dict]) -> RunLoop:
    loop = RunLoop.__new__(RunLoop)
    loop.jev = object()
    loop.llm = object()
    loop.plan_every_s = 45
    loop.stale_noul = 0.7
    loop.confidence_floor = 0.55
    loop._low_confidence_streak = 0
    loop._prev_world = "0"
    loop._prev_dialog = "0"
    loop._beat_heading = None
    loop.recent_steps = recent
    loop.stuck = SimpleNamespace(same_tile_streak=0, immobile_streak=0, press_counts={})
    loop.plan = plan
    loop.env = SimpleNamespace(
        vision_frame=lambda obs: obs, push_event=lambda *args, **kwargs: None
    )
    loop.store = SimpleNamespace(append=lambda *args, **kwargs: None)
    loop.room = RoomMap()
    from nuzlocke.agents.navigation import Navigator

    loop.navigator = Navigator()
    loop._cycle = 0
    loop.run_id = "test"
    loop.env.publish_navigation = lambda payload: None
    from nuzlocke.agents.locomotion import GridTrust

    loop.grid_trust = GridTrust()
    loop.journal = Journal(Path(tempfile.mkdtemp()) / "journal.jsonl")
    loop._goal_fails = {}
    loop._goal_texts = {}
    loop._s1 = None
    loop._last_look = -99
    loop._last_direction = None
    loop.move_types = {}
    loop.ledger = SimpleNamespace(first_encounter=False)
    loop._beat_locked = False
    loop.referee = SimpleNamespace(current_cap=None, death_ledger=[])
    return loop


def test_a_mash_that_left_the_box_unchanged_gets_a_look(monkeypatch):
    import time

    from nuzlocke.agents.jev_policy import FrameSignals

    looks: list[int] = []

    def planner(*args, **kwargs):
        looks.append(1)
        return PlanCard(
            scene=PlanScene.DIALOG,
            see="the box did not move",
            plan="press A",
            steps=[GameAction.PRESS_A],
        )

    plan = PlanCard(
        scene=PlanScene.DIALOG,
        see="Oak is talking",
        plan="page it",
        world_digest="w",
        text_box=True,
        created_at=time.time(),
    )
    loop = _fast_loop(plan, recent=[{"actions": ["skip_dialog"]}])
    loop._frame_signals = lambda obs: FrameSignals("w", "d", False, False, True, False)  # type: ignore[method-assign]
    monkeypatch.setattr("nuzlocke.orchestration.loop.propose_plan", planner)
    proposal = loop._fast_proposal(task=make_task(_decision()), obs=_obs(), context=_context())
    assert looks == [1]
    assert proposal.actions == [GameAction.PRESS_A, GameAction.WAIT_60]


def test_a_mash_that_paged_the_box_mashes_again(monkeypatch):
    import time

    from nuzlocke.agents.jev_policy import FrameSignals

    def boom(*args, **kwargs):
        raise AssertionError("paging text needs no look")

    plan = PlanCard(
        scene=PlanScene.DIALOG,
        see="Oak is talking",
        plan="page it",
        world_digest="w",
        text_box=True,
        created_at=time.time(),
    )
    loop = _fast_loop(plan, recent=[{"actions": ["skip_dialog"]}])
    loop._frame_signals = lambda obs: FrameSignals("w", "d2", False, True, True, False)  # type: ignore[method-assign]
    monkeypatch.setattr("nuzlocke.orchestration.loop.propose_plan", boom)
    proposal = loop._fast_proposal(task=make_task(_decision()), obs=_obs(), context=_context())
    assert proposal.actions == [GameAction.SKIP_DIALOG]


def test_a_forced_look_names_its_reason():
    from nuzlocke.agents.jev_policy import FrameSignals

    loop = _fast_loop(None, recent=[])
    clear = FrameSignals("w", "d", False, False, False, False)
    boxed = FrameSignals("w", "d", False, False, True, False)
    assert loop._forced_look(clear, mash_stalled=False) is False
    assert loop._forced_look(boxed, mash_stalled=True) == "skip_dialog left the box unchanged"
    loop.stuck.press_counts = {"press_b": 8}
    assert loop._forced_look(boxed, mash_stalled=False) == "long text on one tile"


def test_mashes_count_as_pages_but_do_not_force_a_look():
    from nuzlocke.agents.jev_policy import FrameSignals

    loop = _fast_loop(None, recent=[])
    loop.stuck.press_counts = {"skip_dialog": 4, "walk_up": 1}
    assert loop._pages() == 4
    boxed = FrameSignals("w", "d", False, False, True, False)
    assert loop._forced_look(boxed, mash_stalled=False) is False


def test_a_headless_loop_does_not_wait_for_the_dashboard():
    loop = RunLoop.__new__(RunLoop)
    loop.headless = True
    loop.run_cfg = {"control": {"respect_dashboard_control": True}}
    sent: list = []

    def never(*args, **kwargs):
        raise AssertionError("a headless loop does not poll /control")

    loop.env = SimpleNamespace(set_control=sent.append, get_control=never)
    from nuzlocke.state.models import ControlState

    assert loop._wait_until_running() == ControlState.RUNNING
    assert sent == [ControlState.RUNNING]


def test_disengage_drops_the_plan():
    loop = RunLoop.__new__(RunLoop)
    loop.jev = object()
    loop.plan = PlanCard(scene=PlanScene.OVERWORLD, see="stuck", plan="talk to oak")
    loop._last_recovery_step = -1
    loop.arbiter = SimpleNamespace(set_owner=lambda owner: None)
    loop._disengage_proposal = lambda task, tier, obs=None: _proposal("disengage")  # type: ignore[method-assign]
    proposal, used, pause = loop._select_proposal(
        tier=2,
        decision=_decision(),
        task=make_task(_decision()),
        obs=_obs(),
        steps=4,
        context=_context(),
    )
    assert loop.plan is None
    assert proposal is not None
    assert proposal.reason == "disengage"
    assert used is True
    assert pause is False


def test_recovery_advice_becomes_the_plan(monkeypatch):
    loop = RunLoop.__new__(RunLoop)
    loop.jev = object()
    loop.llm = object()
    loop.plan = None
    loop._low_confidence_streak = 4
    loop._prev_world = None
    loop._prev_dialog = None
    loop._last_recovery_step = -1
    loop.stuck = SimpleNamespace(stuck_score=6, recent_positions=[], loop_streak=0)
    loop.env = SimpleNamespace(
        push_event=lambda *a, **k: None,
        set_control=lambda *a, **k: None,
        vision_frame=lambda obs: obs,
    )
    loop.store = SimpleNamespace(append=lambda *a, **k: None)
    loop.arbiter = SimpleNamespace(set_owner=lambda owner: None)

    def fake_recovery(llm, **kwargs):
        return RecoveryAdvice(
            diagnosis="Oak is repeating himself",
            reason="leave the lab north",
            proposed_actions=[GameAction.PRESS_B],
        )

    monkeypatch.setattr("nuzlocke.orchestration.loop.advise_recovery", fake_recovery)
    proposal, used, pause = loop._select_proposal(
        tier=3,
        decision=_decision(),
        task=make_task(_decision()),
        obs=_obs(),
        steps=3,
        context=_context(),
    )
    assert used is True
    assert pause is False
    assert proposal is not None
    assert proposal.actions == [GameAction.PRESS_B]
    assert loop.plan is not None
    assert loop.plan.plan == "leave the lab north"
    assert loop._low_confidence_streak == 0


def test_a_goal_that_ends_in_the_same_text_again_counts_as_failed():
    from nuzlocke.agents.goals import Goal
    from nuzlocke.agents.system1 import S1Turn

    loop = _fast_loop(None, recent=[])
    goal = Goal(key="edge_up", kind="edge", label="north edge", actions=[GameAction.WALK_UP])
    before = PlayerObservation(map_name="Viridian City", map_id=1, x=19, y=10)
    after = before.model_copy(
        update={
            "y": 9,
            "screen_rows": [" " * 20] * 12
            + ["┌" + "─" * 18 + "┐", "│" + " " * 18 + "│", "│You can't go".ljust(19) + "│"]
            + ["│" + " " * 18 + "│"] * 2
            + ["└" + "─" * 18 + "┘"],
        }
    )
    walk = SimpleNamespace(
        walks=[{"action": "walk_up", "x0": 19, "y0": 10, "x1": 19, "y1": 9, "map_id": 1}],
        stopped_early_because="text_box",
    )
    for _ in range(2):
        loop._s1 = S1Turn([GameAction.WALK_UP], "jev", "goal", goal=goal, choice="edge_up")
        loop._after_system1(before, after, walk, ["walk_up"], True, 1)
    assert loop._goal_fails == {"edge_up": 1}
    assert loop._goal_texts["edge_up"]
