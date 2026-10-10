"""Healing keeps its priority while System 2 can clear necessary obstacles."""

from types import SimpleNamespace
from unittest.mock import Mock

from nuzlocke.agents.goals import RoomMap
from nuzlocke.agents.navigation import Navigator
from nuzlocke.agents.system1 import system1_turn
from nuzlocke.environment.screen_text import parse_screen
from nuzlocke.knowledge.walkthrough import compose
from nuzlocke.orchestration.loop import _COOLDOWN_TRIGGERS, RunLoop
from nuzlocke.referee.rules import NuzlockeReferee
from nuzlocke.state.models import ActionProposal, AgentRole, ObjectivesUpdate, PlanCard, PlanScene, PlayerObservation


def setup():
    loop = RunLoop.__new__(RunLoop)
    loop.referee = NuzlockeReferee({})
    loop.referee.advance(2)
    loop.run_cfg = {"milestones": []}
    loop._encounter_tables, loop._encounter_search_counts, loop._grass_visits = {}, {}, {}
    loop.navigator, loop.room = Navigator(), RoomMap()
    loop._beat_locked, loop._beat_id, loop.plan = False, None, None
    loop.env, loop.store = Mock(), Mock()
    loop.memory = SimpleNamespace(enabled=False)
    loop._cycle = 1
    obs = PlayerObservation(
        map_id=5,
        map_name="Vermilion City",
        x=15,
        y=19,
        raw_player={"name": "RED"},
        badges=["Boulder", "Cascade"],
        flags={"has_pokedex": True},
        party=[{"species": "Beedrill", "hp": 60, "max_hp": 60, "status": "PAR", "moves": [{"name": "Cut"}]}],
    )
    return loop, obs


def card(target):
    return PlanCard(scene=PlanScene.OVERWORLD, see="tree", plan="Clear the tree on the healing route", goal_target=target)


def test_healing_allows_a_subgoal_and_field_menu_without_releasing_its_priority():
    loop, obs = setup()
    loop.plan = card({"kind": "warp", "dest_map": 92})  # Previous story intent.
    hint = loop._sync_beats(obs, controllable=True)
    assert loop.plan is None
    assert "Strength" in hint and "Rock Smash" in hint and "prerequisites are observed" in hint
    assert loop._objective(obs)[0] == {"kind": "warp", "dest_map": 89}
    target = {"kind": "tile", "map_id": 5, "x": 15, "y": 19}
    loop.plan = card(target)
    assert loop._objective(obs) == (target, loop.plan.plan, False)
    loop._apply_proposal_meta(
        ActionProposal(
            task_id="test",
            agent=AgentRole.OVERWORLD,
            actions=[],
            reason="try progression",
            objectives=ObjectivesUpdate(primary="Challenge Surge"),
        )
    )
    assert loop.objectives["primary"] == "Heal first: enter Vermilion's Center."
    loop.plan = card(None)  # Opening START must not revert to walking toward the Center.
    assert loop._objective(obs) == (None, loop.plan.plan, False)
    loop._sync_beats(obs, controllable=True)
    assert loop.plan is not None and loop._beat_locked
    assert not obs.policy.get("encounter_search")


def test_nurse_and_verified_healing_retire_the_temporary_route():
    loop, obs = setup()
    loop._sync_beats(obs, controllable=True)
    loop.plan = card({"kind": "tile", "map_id": 5, "x": 15, "y": 19})
    obs.map_id, obs.map_name = 89, "Vermilion Pokecenter"
    loop._sync_beats(obs, controllable=True)
    assert loop.plan is None
    assert loop._objective(obs)[0]["kind"] == "face"
    loop.plan = card(None)
    obs.party[0]["status"] = "OK"
    loop._sync_beats(obs, controllable=True)
    assert not loop._beat_locked and loop.plan is None
    assert not loop.objectives["primary"].startswith("Heal")


def test_final_gym_healing_cannot_be_replaced_by_planner_or_progression_objectives():
    from nuzlocke.agents.gym_preparation import GymPreparation

    loop, obs = setup()
    obs.map_id, obs.map_name = 89, "Vermilion Pokecenter"
    obs.party[0].update(status="OK", level=23)
    obs.surge_puzzle = {"phase": "open"}
    loop.gym_preparation = GymPreparation()
    loop.gym_preparation.observe(obs, cap=24, candy_enabled=True, record=loop.store.append)
    loop._sync_beats(obs, controllable=True)
    loop._apply_proposal_meta(
        ActionProposal(
            task_id="test",
            agent=AgentRole.OVERWORLD,
            actions=[],
            reason="challenge",
            objectives=ObjectivesUpdate(primary="Fight Surge", secondary="Erika"),
        )
    )
    assert loop.objectives["primary"].startswith("Heal")
    assert "24" in loop.objectives["secondary"] and "Thunder" in loop.objectives["tertiary"]
    assert loop._objective(obs)[0] == {"kind": "face", "x": 3, "y": 3, "dir": "up"}


def test_partial_healing_exit_requests_a_plan_before_walking_an_enclosed_area():
    loop, obs = setup()
    # Open local floor cannot reach the distant Center; the inaccessible exit still has a partial path.
    obs.warps = [{"x": 11, "y": 3, "dest_map": 89}]
    obs.map_size = {"w": 40, "h": 36}
    obs.collision_ascii = "\n".join(["   A B C D E F G H I J"] + [f" {i} . . . . . . . . . ." for i in range(1, 10)])
    obs.policy["healing_route"] = True
    turn = system1_turn(
        obs=obs,
        screen=parse_screen([]),
        text_box=False,
        mash_stalled=False,
        room=loop.room,
        objective={"kind": "warp", "dest_map": 89},
        objective_text="Heal first: enter Vermilion's Center.",
        objective_from_code=True,
        heading=None,
        fails={},
        last_direction=None,
        low_confidence_streak=0,
        confidence_floor=0.55,
        stale_noul=0.7,
        journal=[],
        constraints=[],
        jev_decide=Mock(side_effect=AssertionError("Blocked healing route must request a plan first")),
    )
    assert turn.trigger == "healing route blocked" and not turn.actions
    assert turn.trigger not in _COOLDOWN_TRIGGERS


def test_healing_guide_requires_real_capabilities_and_both_sides_of_a_blocker():
    guide = compose("healing")
    assert "HM ownership alone is insufficient" in guide
    assert "Do not invent Rock Smash support" in guide
    assert "gym side" in guide and "(15,19)" in guide and "**UP**" in guide
    assert "Avoid trapping the boulder" in guide
    assert "until observed HP, status and PP" in guide


def test_field_capabilities_are_observed_not_inferred_from_hm_inventory():
    from nuzlocke.agents.system3 import constraints

    _, obs = setup()
    obs.bag = [{"item": "HM04", "quantity": 1}]
    obs.party += [
        {"species": "Machop", "hp": 0, "moves": [{"name": "Strength"}]},
        {"species": "Geodude", "hp": 20, "dead": True, "moves": [{"name": "Rock Smash"}]},
    ]
    facts = [line for line in constraints(obs, 24, []) if line.startswith("Living field-move user:")]
    assert facts == ["Living field-move user: Beedrill knows Cut; verify field permission."]
    obs.party[1]["hp"] = 20
    obs.party[2]["dead"] = False
    facts = [line for line in constraints(obs, 24, []) if line.startswith("Living field-move user:")]
    assert len(facts) == 3 and "Strength" in facts[1] and "Rock Smash" in facts[2]


def test_open_healing_route_retires_a_stale_obstacle_or_door_tile_plan():
    loop, obs = setup()
    loop._sync_beats(obs, controllable=True)
    obs.warps = [{"x": 15, "y": 17, "dest_map": 89}]
    obs.collision_ascii = "\n".join(["   A B C D E F G H I J"] + [f" {i} . . . . . . . . . ." for i in range(1, 10)])
    loop.plan = card({"kind": "tile", "map_id": 5, "x": 15, "y": 17})
    assert loop._objective(obs) == ({"kind": "warp", "dest_map": 89}, "Heal first: enter Vermilion's Center.", True)
    assert loop.plan is None
    assert loop._beat_locked and loop.objectives["primary"].startswith("Heal")
