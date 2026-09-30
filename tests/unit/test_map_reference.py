from nuzlocke.agents.goals import RoomMap, Routes
from nuzlocke.agents.navigation import Navigator
from nuzlocke.knowledge.map_reference import (
    atlas,
    desired_exit,
    guided_path,
    reference,
    shortest_path,
)
from nuzlocke.state.models import PlayerObservation


def route3():
    return PlayerObservation(
        map_id=14,
        map_name="Route 3",
        x=65,
        y=12,
        map_size={"w": 70, "h": 18},
        connections=["up", "left"],
    )


def test_reference_connection_has_the_actual_destination_and_open_crossing_tiles():
    obs = route3()
    target = desired_exit(obs, {"kind": "edge", "dir": "up"})
    assert target["dest_map"] == 15
    assert target["destination"] == "Route 4"
    assert target["tiles"] == [[x, 0] for x in range(57, 62)]
    assert desired_exit(obs, {"kind": "edge", "dir": "right"}) is None


def test_reference_shortest_path_goes_to_exit_without_rediscovering_the_map():
    obs = route3()
    path = shortest_path(obs, [[59, 0]])
    assert path[0] == (65, 12) and path[-1] == (59, 0)
    assert len(path) < 30
    # Live walls and blocked directions override the vanilla route.
    obstacle = path[3]
    changed = shortest_path(obs, [[59, 0]], observed={obstacle: False})
    assert changed and obstacle not in changed
    changed = shortest_path(obs, [[59, 0]], blocked={(65, 12, "left")})
    assert changed and changed[1] != (64, 12)


def test_system1_reference_guidance_only_executes_reachable_observed_floor():
    obs = route3()
    observed = {(65, y): True for y in range(8, 13)}
    routes = Routes((65, 12), observed, size=(70, 18))
    path = guided_path(obs, routes, [[59, 0]])
    assert path == ["up"] * 4


def test_system2_gets_full_reference_map_and_desired_exit_before_exploration():
    obs = route3()
    payload = Navigator().context(obs, RoomMap(), {"kind": "edge", "dir": "up"})
    ref = payload["reference_map"]
    assert len(ref["rows"]) == 18 and all(len(row) == 70 for row in ref["rows"])
    assert ref["desired_exit"]["dest_map"] == 15
    assert ref["suggested_route"]["steps"] > 0
    assert "?" in payload["rows"][0]  # Observed history stays distinct from prior knowledge.


def test_forest_reference_routes_between_its_known_gate_exits():
    obs = PlayerObservation(map_id=51, x=17, y=46, map_size={"w": 34, "h": 48})
    desired = desired_exit(obs, {"kind": "warp", "dest_map": 47})
    assert desired is not None
    path = shortest_path(obs, desired["tiles"])
    assert path and list(path[-1]) in desired["tiles"]
    assert len(path) > 48  # Maze, not a straight line through walls.


def test_reference_is_disabled_for_mismatched_dimensions_and_does_not_mutate():
    obs = route3()
    assert reference(obs.model_copy(update={"map_size": {"w": 72, "h": 18}})) is None
    before = atlas()["maps"]["14"]["rows"][:]
    shortest_path(obs, [[59, 0]], observed={(59, 0): False})
    assert atlas()["maps"]["14"]["rows"] == before
