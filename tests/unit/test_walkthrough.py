"""Walkthrough excerpt selection tests."""

from __future__ import annotations

from nuzlocke.knowledge.walkthrough import excerpt_for_context, load_full_walkthrough, skill_dir


def test_walkthrough_files_exist() -> None:
    assert (skill_dir() / "SKILL.md").is_file()
    assert (skill_dir() / "reference.md").is_file()
    assert "Pallet" in load_full_walkthrough()


def test_excerpt_picks_house_and_stuck() -> None:
    text = excerpt_for_context(map_name="Red's House 2F", reason="noop stairs")
    assert "2F" in text or "stairs" in text.lower()
    assert "Stuck" in text or "stuck" in text.lower()


def test_excerpt_picks_fence_and_parcel_geometry() -> None:
    fence = excerpt_for_context(map_name="Pallet Town", reason="fence post noop")
    assert "post" in fence.lower()
    parcel = excerpt_for_context(map_name="Oak's Lab", reason="aide parcel")
    assert "aide" in parcel.lower() or "oak" in parcel.lower()
    ledge = excerpt_for_context(map_name="Route 1", reason="viridian south ledge")
    assert "gap" in ledge.lower() or "ledge" in ledge.lower()


def test_excerpt_lab() -> None:
    text = excerpt_for_context(reason="need starter in oak lab")
    assert "Lab" in text or "starter" in text.lower()


def test_unmatched_late_game_context_does_not_leak_early_game_sections() -> None:
    # No keyword rule matches a mid/late-game map/reason — must not fall
    # back to Pallet/bedroom-specific hints, only the generic stuck cheatsheet.
    text = excerpt_for_context(map_name="Cinnabar Island", reason="cannot find the mansion exit")
    assert "Pallet Town" not in text
    assert "Red's House" not in text
    assert "stuck" in text.lower()


def test_surge_guidance_tracks_missing_prerequisites_without_waiting_for_stuck():
    from nuzlocke.knowledge.walkthrough import progression_hint
    from nuzlocke.state.models import PlayerObservation

    obs = PlayerObservation(badges=["Boulder", "Cascade"], map_id=3)
    assert "visit Bill" in progression_hint(obs)
    assert "robbed house" in progression_hint(obs)
    obs.bag = [{"id": 63, "item": "S.S. Ticket", "quantity": 1}]
    assert "Ticket is held but HM01 is missing" in progression_hint(obs)
    obs.bag = [{"id": 196, "item": "HM01", "quantity": 1}]
    assert "teach it" in progression_hint(obs)
    obs.bag = []
    obs.party = [{"hp": 20, "moves": [{"name": "CUT"}]}]
    assert "CUT is learned" in progression_hint(obs)
    obs.party[0]["dead"] = True
    assert "visit Bill" in progression_hint(obs)
    obs.badges.append("Thunder")
    assert "Post-Thunder" in progression_hint(obs) and "Erika" in progression_hint(obs)
    obs.badges.append("Rainbow")
    assert "Post-Rainbow" in progression_hint(obs)
    obs.badges = ["Boulder"]
    assert not progression_hint(obs)
    obs.badges.append("Cascade")
    obs.in_battle = True
    assert not progression_hint(obs)


def test_surge_locations_select_the_route_checklist():
    for name in ["Bill's House", "Route 5", "Route 6", "Vermilion City", "S.S. Anne 2F"]:
        text = excerpt_for_context(map_name=name)
        assert "Lt. Surge" in text and "Bill first" in text


def test_bill_and_surge_map_ids_are_not_shifted_dependency_labels():
    from nuzlocke.environment.maps import map_name

    assert map_name(88) == "Bill's House"
    assert map_name(92) == "Vermilion Gym"
    assert map_name(95) == "S.S. Anne 1F"
    assert map_name(101) == "S.S. Anne Captain's Room"
    assert map_name(119) == "Underground Path (North-South)"
    assert map_name(121) == "Underground Path (West-East)"
    assert map_name(134) == "Celadon Gym"
    assert map_name(232) == "Rock Tunnel B1F"


def test_erika_guidance_is_stage_specific_and_stops_after_rainbow():
    from nuzlocke.knowledge.walkthrough import erika_stage, progression_hint
    from nuzlocke.state.models import PlayerObservation

    obs = PlayerObservation(map_id=5, badges=["Boulder", "Cascade", "Thunder"])
    for mid, y, stage in [
        (5, 1, "return_cerulean"),
        (3, 1, "route9"),
        (21, 18, "route9"),
        (82, 3, "rock_tunnel"),
        (232, 25, "rock_tunnel"),
        (21, 53, "lavender"),
        (19, 3, "underground_west"),
        (121, 2, "underground_west"),
        (6, 10, "celadon"),
        (134, 4, "gym"),
    ]:
        obs.map_id, obs.y = mid, y
        assert erika_stage(obs) == stage
        hint = progression_hint(obs)
        assert "Erika" in hint and "Lt. Surge — Bill" not in hint
    obs.in_battle = True
    assert not progression_hint(obs)
    obs.in_battle = False
    obs.badges.append("Rainbow")
    assert erika_stage(obs) is None and "Post-Rainbow" in progression_hint(obs)


def test_boss_briefing_covers_surge_and_erika():
    from nuzlocke.knowledge.trainers import next_boss

    assert "Raichu L24" in next_boss(2)
    assert "Victreebel L29" in next_boss(3)
