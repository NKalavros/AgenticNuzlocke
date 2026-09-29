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
