from nuzlocke.referee.type_chart import battle_matchup, matchup_hint, types_for_species


def test_types_for_species_known():
    assert types_for_species("Charizard") == ("Fire", "Flying")
    assert types_for_species("Squirtle") == ("Water",)


def test_types_for_species_unknown_returns_empty():
    assert types_for_species("Missingno") == ()


def test_water_vs_fire_is_super_effective():
    assert matchup_hint(["Water"], ["Fire"]) == "super effective"


def test_fire_vs_water_is_not_very_effective():
    assert matchup_hint(["Fire"], ["Water"]) == "not very effective"


def test_electric_vs_ground_is_no_effect():
    assert matchup_hint(["Electric"], ["Ground"]) == "no effect"


def test_normal_vs_ghost_is_no_effect():
    assert matchup_hint(["Normal"], ["Ghost"]) == "no effect"


def test_bug_vs_poison_is_super_effective_gen1_quirk():
    # Gen 1 specific: nerfed to not-very-effective from Gen 2 onward.
    assert matchup_hint(["Bug"], ["Poison"]) == "super effective"


def test_ghost_vs_psychic_is_no_effect_gen1_bug():
    # CATCH_23 bug: intended super effective, actually does nothing in Gen 1.
    assert matchup_hint(["Ghost"], ["Psychic"]) == "no effect"


def test_dual_type_defender_multiplies():
    # Grass vs Water/Ground (e.g. a Poliwrath-like matchup on Ground side) -> 2x*2x
    assert matchup_hint(["Grass"], ["Water", "Ground"]) == "super effective"


def test_best_of_multiple_attacker_types_wins():
    # Grass/Poison vs Fire: Grass is resisted (0.5x) but Poison is neutral
    # (1x) — the better of the two types should decide the hint.
    assert matchup_hint(["Grass", "Poison"], ["Fire"]) == "normal"


def test_battle_matchup_builds_party_hints():
    party = [
        {"nickname": "SHELLY", "species": "Squirtle", "types": ["Water"]},
        {"nickname": "EMBER", "species": "Charmander", "types": ["Fire"]},
    ]
    result = battle_matchup(party, "Geodude")
    assert result["enemy_types"] == ["Rock", "Ground"]
    assert result["party"]["SHELLY"] == "super effective"
    assert result["party"]["EMBER"] == "not very effective"


def test_battle_matchup_unknown_enemy_returns_none():
    party = [{"nickname": "SHELLY", "species": "Squirtle", "types": ["Water"]}]
    assert battle_matchup(party, "Missingno") is None
