from nuzlocke.environment.dashboard import capture_count, field_log_script


def test_counts_pc_captures_without_counting_starter_evolutions_or_failed_encounters():
    # Six current party members, but nine successful wild captures plus the starter.
    ledger = {str(area): {"outcome": "caught"} for area in [12, 13, 14, 15, 33, 35, 36, 51, 59]}
    ledger["20"] = {"outcome": "engaged"}
    ledger["21"] = {"outcome": "forfeited"}
    assert capture_count(ledger) == 9
    # Legacy Mt. Moon floor keys must not count the same area's catch twice.
    ledger["61"] = {"outcome": "caught"}
    assert capture_count(ledger) == 9
    assert capture_count({}) == 0


def test_field_log_uses_run_telemetry_instead_of_six_party_slots():
    script = field_log_script()
    assert "caught = party.length" not in script
    assert "updateNuzlockeCaught(state);" in script
    assert "state.nuzlocke?.caught" in script
