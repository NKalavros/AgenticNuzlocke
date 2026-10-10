from nuzlocke.agents.roles import (
    merge_objectives,
    objectives_for_dashboard,
    parse_landmarks,
    parse_objectives,
)
from nuzlocke.state.models import LandmarkNote, ObjectivesUpdate


def test_parse_objectives():
    got = parse_objectives({"primary": " Get starter ", "secondary": "", "tertiary": "Brock"})
    assert got is not None
    assert got.primary == "Get starter"
    assert got.secondary is None
    assert got.tertiary == "Brock"


def test_parse_objectives_empty():
    assert parse_objectives({}) is None
    assert parse_objectives(None) is None


def test_merge_and_dashboard():
    current = {"primary": "old", "secondary": "keep"}
    merged = merge_objectives(current, ObjectivesUpdate(primary="new primary", tertiary="third"))
    assert merged == {"primary": "new primary", "secondary": "keep", "tertiary": "third"}
    dash = objectives_for_dashboard(merged)
    assert [d["tier"] for d in dash] == ["primary", "secondary", "tertiary"]
    assert dash[0]["text"] == "new primary"


def test_parse_landmarks():
    got = parse_landmarks(
        [
            {"label": "stairs", "note": "south of bed"},
            {"label": "", "note": "skip"},
            {"label": "door", "note": "bottom"},
        ]
    )
    assert got == [
        LandmarkNote(label="stairs", note="south of bed"),
        LandmarkNote(label="door", note="bottom"),
    ]


def test_completed_milestones_do_not_reappear_after_a_partial_planner_update():
    from types import SimpleNamespace
    from unittest.mock import Mock

    from nuzlocke.orchestration.loop import RunLoop
    from nuzlocke.referee.rules import NuzlockeReferee

    loop = RunLoop.__new__(RunLoop)
    loop.run_cfg = {
        "milestones": [
            {"id": "leave_pallet", "description": "Leave Pallet Town"},
            {"id": "viridian", "description": "Reach Viridian City"},
            {"id": "route_1_encounter", "description": "Resolve the first legal Route 1 encounter"},
            {"id": "brock", "description": "Attempt Brock"},
            {"id": "misty", "description": "Attempt Misty"},
        ]
    }
    loop.referee = NuzlockeReferee({})
    loop.referee.advance(1)
    loop.referee.encounter_ledger["12"] = {"outcome": "caught", "species": "Pidgey"}
    assert loop._seed_objectives() == {"primary": "Attempt Misty"}
    loop.objectives = {
        "primary": "Old task",
        "tertiary": "Resolve the first legal Route 1 encounter",
    }
    loop._beat_locked = False
    loop.env, loop.store = Mock(), Mock()
    loop.memory = SimpleNamespace(enabled=False)
    from nuzlocke.state.models import ActionProposal, AgentRole

    loop._apply_proposal_meta(
        ActionProposal(
            task_id="t",
            agent=AgentRole.OVERWORLD,
            actions=[],
            reason="battle done",
            objectives=ObjectivesUpdate(primary="Resolve Route 24"),
        )
    )
    assert loop.objectives == {"primary": "Resolve Route 24"}
    assert loop.env.set_objectives.call_args.args[0] == [
        {"tier": "primary", "text": "Resolve Route 24", "done": False}
    ]
    # An unresolved area is not erased merely because Brock was beaten.
    loop.referee.encounter_ledger.clear()
    assert loop._seed_objectives()["primary"] == "Resolve the first legal Route 1 encounter"


def test_encounter_override_is_shared_by_actor_dashboard_and_planner_context():
    from nuzlocke.agents.goals import RoomMap
    from nuzlocke.agents.navigation import Navigator
    from nuzlocke.orchestration.loop import RunLoop
    from nuzlocke.referee.rules import NuzlockeReferee
    from nuzlocke.state.models import PlayerObservation

    loop = RunLoop.__new__(RunLoop)
    loop.referee = NuzlockeReferee({})
    loop.referee.advance(1)
    loop.run_cfg = {"milestones": [{"id": "misty", "description": "Attempt Misty"}]}
    loop._encounter_tables, loop._encounter_search_counts, loop._grass_visits = {}, {}, {}
    loop._cycle = 1
    loop.navigator, loop.room = Navigator(), RoomMap()
    loop._beat_locked, loop._beat_id, loop.plan = False, None, None
    obs = PlayerObservation(
        map_id=35,
        map_name="Route 24",
        x=1,
        y=1,
        raw_player={"name": "RED"},
        badges=["Boulder"],
        flags={"has_pokedex": True},
        bag=[{"item": "Poke Ball", "quantity": 10}],
        party=[{"species": "Pidgeotto", "level": 19, "hp": 53, "max_hp": 53, "status": "OK"}],
        grass_tiles=[{"x": 2, "y": 1}],
    )
    loop._sync_beats(obs, controllable=True)
    target, text, owned = loop._objective(obs)
    assert target == {"kind": "tile", "x": 2, "y": 1}
    assert owned and "Route 24" in text
    assert loop.objectives == {"primary": text, "secondary": "Attempt Misty"}
    assert loop._prompt_beat == text and loop._beat_locked
    # Keeping the destination prevents another visit from restoring opening goals.
    loop._sync_beats(obs, controllable=True)
    assert loop.objectives["primary"] == loop._objective(obs)[1]
    assert loop.referee.encounter_ledger == {}
    # Existing north-before-Misty ordering remains in effect in Cerulean.
    obs.map_id, obs.map_name = 3, "Cerulean City"
    obs.policy["preparation_target"] = 19
    loop._sync_beats(obs, controllable=True)
    assert loop._objective(obs)[0] == {"kind": "edge", "dir": "up"}
    assert "before Misty" in loop.objectives["primary"]


def test_healing_without_known_route_clears_story_plan_and_keeps_objective_locked():
    from nuzlocke.agents.goals import RoomMap
    from nuzlocke.agents.navigation import Navigator
    from nuzlocke.orchestration.loop import RunLoop
    from nuzlocke.referee.rules import NuzlockeReferee
    from nuzlocke.state.models import ActionProposal, AgentRole, PlayerObservation

    loop = RunLoop.__new__(RunLoop)
    loop.referee = NuzlockeReferee({})
    loop.run_cfg = {"milestones": []}
    loop._encounter_tables, loop._encounter_search_counts, loop._grass_visits = {}, {}, {}
    loop.navigator, loop.room = Navigator(), RoomMap()
    loop._beat_locked, loop._beat_id, loop.plan = False, None, object()
    loop._cycle = 1
    obs = PlayerObservation(
        map_id=94,
        x=3,
        y=4,
        badges=["Boulder", "Cascade"],
        flags={"has_pokedex": True},
        bag=[{"item": "Poke Ball", "quantity": 7}],
        party=[{"species": "Pidgeotto", "level": 22, "hp": 16, "max_hp": 65}],
        grass_tiles=[{"x": 4, "y": 4}],
    )
    loop._sync_beats(obs, controllable=True)
    assert loop.plan is None and loop._beat_locked
    assert loop._beat_id == "heal_route_unknown"
    assert loop.objectives["primary"].startswith("Heal")
    assert loop._objective(obs)[0] is None  # Director must supply a healing route.
    loop._apply_proposal_meta(
        ActionProposal(
            task_id="t",
            agent=AgentRole.OVERWORLD,
            actions=[],
            reason="continue story",
            objectives=ObjectivesUpdate(primary="Board S.S. Anne"),
        )
    )
    assert loop.objectives["primary"].startswith("Heal")
    obs.map_id = 17
    loop._sync_beats(obs, controllable=True)
    assert loop._objective(obs)[0] == {"kind": "edge", "dir": "down"}
    assert not obs.policy.get("encounter_search")


def test_progression_panel_advances_only_with_observed_prerequisites():
    from nuzlocke.orchestration.objectives import progression_objectives
    from nuzlocke.state.models import PlayerObservation

    obs = PlayerObservation(map_id=3, badges=["Boulder", "Cascade"])
    assert "Bill" in progression_objectives(obs)["primary"]
    obs.map_id = 36
    assert "east end of Route 25" in progression_objectives(obs)["primary"]
    obs.map_id = 88
    assert "separation machine" in progression_objectives(obs)["primary"]
    # Visiting Bill is not evidence of receipt.
    assert "S.S. Ticket" in progression_objectives(obs)["primary"]
    obs.bag = [{"item": "S.S. Ticket", "quantity": 1}]
    assert "Underground Path" in progression_objectives(obs)["primary"]
    obs.map_id = 5
    assert "captain" in progression_objectives(obs)["primary"]
    obs.bag.append({"item": "HM01", "quantity": 1})
    assert "Teach" in progression_objectives(obs)["primary"]
    obs.party = [{"hp": 20, "moves": [{"name": "CUT"}]}]
    assert "tree" in progression_objectives(obs)["primary"]
    obs.map_id = 92
    assert "switch locks" in progression_objectives(obs)["primary"]
    obs.badges.append("Thunder")
    assert "Erika" in progression_objectives(obs)["tertiary"]
    obs.map_id = 134
    assert "challenge Erika" in progression_objectives(obs)["primary"]
    obs.badges.append("Rainbow")
    assert "Rocket Hideout" in progression_objectives(obs)["primary"]
    assert "Koga" in progression_objectives(obs)["tertiary"]
    obs.badges.append("Soul")
    assert progression_objectives(obs) is None
    obs.badges = ["Boulder"]
    assert progression_objectives(obs) is None


def test_planner_gym_list_cannot_overwrite_progression_but_safety_objectives_can():
    from types import SimpleNamespace
    from unittest.mock import Mock

    from nuzlocke.orchestration.loop import RunLoop
    from nuzlocke.referee.rules import NuzlockeReferee
    from nuzlocke.state.models import ActionProposal, AgentRole, PlayerObservation

    loop = RunLoop.__new__(RunLoop)
    loop.run_cfg = {}
    loop.referee = NuzlockeReferee({})
    loop.referee.advance(2)
    loop.objectives = {"primary": "Attempt Lt. Surge", "secondary": "Attempt Erika"}
    loop._beat_locked = False
    loop.env, loop.store = Mock(), Mock()
    loop.memory = SimpleNamespace(enabled=False)
    obs = PlayerObservation(map_id=3, badges=["Boulder", "Cascade"])
    loop._publish_objectives(obs)
    assert "Bill" in loop.env.set_objectives.call_args.args[0][0]["text"]
    loop._apply_proposal_meta(
        ActionProposal(
            task_id="t",
            agent=AgentRole.OVERWORLD,
            actions=[],
            reason="go to Surge",
            objectives=ObjectivesUpdate(primary="Attempt Lt. Surge", secondary="Attempt Erika"),
        )
    )
    assert "Bill" in loop.objectives["primary"]
    # The post-action receipt updates both stored objectives and the dashboard.
    obs.bag = [{"id": 63, "quantity": 1}]
    loop._publish_objectives(obs)
    assert "Underground Path" in loop.objectives["primary"]
    assert "Bill" not in str(loop.env.set_objectives.call_args.args[0])
    loop._beat_locked = True
    loop.objectives = {"primary": "Heal the party at the Center"}
    loop._publish_objectives(obs)
    assert loop.objectives["primary"] == "Heal the party at the Center"
