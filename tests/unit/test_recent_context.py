from nuzlocke.agents.roles import _with_extras


def test_recent_injected_without_coaching_notes():
    payload = _with_extras(
        {},
        recent=[{"step": 1, "actions": ["walk_up_2"], "outcome": "noop x1"}],
        memory="LANDMARK stairs: top-right",
    )
    assert "recent" in payload
    assert payload["recent"][0]["outcome"] == "noop x1"
    assert payload["memory"].startswith("LANDMARK")
    assert "recent_note" not in payload
    assert "memory_note" not in payload


def test_button_counts_tell_the_planner_this_tile_was_already_paged():
    payload = _with_extras(
        {},
        beat="Face a starter ball from the south and confirm it.",
        buttons_on_this_tile={"press_a": 1, "press_b": 12},
    )
    assert payload["beat"].startswith("Face a starter")
    assert payload["buttons_on_this_tile"]["press_b"] == 12
    assert "book" in payload["buttons_note"]
    assert "walk" in payload["buttons_note"]


def test_failed_approaches_injected_without_ram_coords():
    payload = _with_extras({}, failed_approaches=[["walk_up_2"], ["walk_up"]])
    assert payload["failed_approaches"] == [["walk_up_2"], ["walk_up"]]
    assert "recent_positions" not in payload
