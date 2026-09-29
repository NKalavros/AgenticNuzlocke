"""Early-game beats own the objective. The planner cannot replace them."""

from types import SimpleNamespace

from nuzlocke.knowledge.beats import current_beat, objective_window
from nuzlocke.orchestration.loop import RunLoop
from nuzlocke.state.models import (
    ActionProposal,
    AgentRole,
    GameAction,
    ObjectivesUpdate,
    PlanCard,
    PlanScene,
    PlayerObservation,
)


def _obs(**kwargs) -> PlayerObservation:
    base: dict = {"raw_player": {"name": "RED"}, "x": 4, "y": 4}
    base.update(kwargs)
    return PlayerObservation(**base)


def test_beats_advance_from_the_bedroom_to_route_1():
    bedroom = current_beat(_obs(map_name="Red's House 2F", map_id=38))
    assert bedroom is not None
    assert bedroom.id == "leave_bedroom"

    living = current_beat(_obs(map_name="Red's House 1F", map_id=37))
    assert living is not None
    assert living.id == "exit_house"

    shore = objective_window(_obs(map_name="Pallet Town", x=8, y=16, party=[]))
    assert shore is not None
    assert "north" in shore["primary"].lower()
    assert "water" in shore["primary"].lower()
    assert shore["secondary"].startswith("Choose BULBASAUR")

    lab = current_beat(_obs(map_name="Oak's Lab", party=[]))
    assert lab is not None
    assert lab.id == "get_starter"

    leaving = current_beat(_obs(map_name="Oak's Lab", party=[{"name": "BULBASAUR"}]))
    assert leaving is not None
    assert leaving.id == "leave_lab"

    north = current_beat(_obs(map_name="Pallet Town", party=[{"name": "BULBASAUR"}]))
    assert north is not None
    assert north.id == "leave_pallet"

    assert current_beat(_obs(map_name="Pewter City", party=[{"name": "BULBASAUR"}])) is None
    assert objective_window(_obs(map_name="Pallet Town", x=0, y=0, party=[])) is None


def test_sync_beats_replaces_planner_objectives_and_drops_a_stale_plan():
    loop = RunLoop.__new__(RunLoop)
    loop._beat_locked = False
    loop._beat_id = None
    loop._prompt_beat = None
    loop.plan = PlanCard(scene=PlanScene.OVERWORLD, see="shore", plan="walk_down once")
    loop._seed_objectives = lambda: {"primary": "milestone tail"}  # type: ignore[method-assign]

    hint = loop._sync_beats(_obs(map_name="Pallet Town", x=8, y=16, party=[]), controllable=True)
    assert hint
    assert "fence" in hint.lower() or "north" in hint.lower()
    assert loop.plan is None
    assert "water" in loop.objectives["primary"].lower()
    assert loop._beat_locked is True

    loop.plan = PlanCard(scene=PlanScene.OVERWORLD, see="shore", plan="walk_up once")
    loop._sync_beats(_obs(map_name="Pallet Town", x=8, y=16, party=[]), controllable=True)
    assert loop.plan is not None
    assert loop.plan.plan == "walk_up once"

    loop.env = SimpleNamespace(set_objectives=lambda *_a, **_k: None)
    loop.store = SimpleNamespace(append=lambda *_a, **_k: None)
    loop.memory = SimpleNamespace(enabled=False)
    loop._apply_proposal_meta(
        ActionProposal(
            task_id="t",
            agent=AgentRole.OVERWORLD,
            reason="south looks open",
            actions=[GameAction.WALK_DOWN],
            objectives=ObjectivesUpdate(primary="Leave Pallet Town north onto Route 1"),
        )
    )
    assert "water" in loop.objectives["primary"].lower()

    loop._sync_beats(_obs(map_name="Pewter City", party=[{"name": "BULBASAUR"}]), controllable=True)
    assert loop._beat_locked is False
    assert loop.objectives == {"primary": "milestone tail"}


def test_the_parcel_errand_comes_before_the_north_road():
    mon = [{"name": "BULBASAUR"}]
    parcel = [{"item": "Oak's Parcel"}]
    assert current_beat(_obs(map_name="Viridian City", party=mon)).id == "get_parcel"
    assert current_beat(_obs(map_name="Viridian City", party=mon, bag=parcel)).id == "parcel_south"
    assert current_beat(_obs(map_name="Oak's Lab", party=mon, bag=parcel)).id == "deliver_parcel"
    dex = _obs(map_name="Viridian City", map_id=1, party=mon, flags={"has_pokedex": True})
    assert current_beat(dex).id == "to_route_2"
