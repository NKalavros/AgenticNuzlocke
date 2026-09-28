from nuzlocke.orchestration.checkpoint import should_checkpoint


def test_saves_on_cadence_outside_battle():
    assert should_checkpoint(
        steps=50, every_steps=50, in_battle=False, last_ledger_change_step=0
    )


def test_does_not_save_off_cadence():
    assert not should_checkpoint(
        steps=51, every_steps=50, in_battle=False, last_ledger_change_step=0
    )


def test_never_saves_mid_battle():
    assert not should_checkpoint(
        steps=50, every_steps=50, in_battle=True, last_ledger_change_step=0
    )


def test_skips_right_after_a_ledger_commit():
    assert not should_checkpoint(
        steps=50,
        every_steps=50,
        in_battle=False,
        last_ledger_change_step=49,
        min_gap_after_ledger_event=3,
    )


def test_resumes_saving_once_gap_after_ledger_event_passes():
    assert should_checkpoint(
        steps=50,
        every_steps=50,
        in_battle=False,
        last_ledger_change_step=40,
        min_gap_after_ledger_event=3,
    )


def test_disabled_when_every_steps_is_zero():
    assert not should_checkpoint(
        steps=50, every_steps=0, in_battle=False, last_ledger_change_step=0
    )


def test_never_saves_at_step_zero():
    assert not should_checkpoint(
        steps=0, every_steps=50, in_battle=False, last_ledger_change_step=-1000
    )


def test_session_save_is_copied_where_load_reads_and_into_the_run(tmp_path):
    from nuzlocke.orchestration.checkpoint import mirror_save

    saved = tmp_path / "data" / "games" / "sess" / "saves" / "auto.state"
    saved.parent.mkdir(parents=True)
    saved.write_bytes(b"state-bytes")
    run = tmp_path / "run"
    copied = mirror_save(saved, run_dir=run, name="auto")
    assert (tmp_path / "data" / "saves" / "auto.state").read_bytes() == b"state-bytes"
    assert copied == run / "savestates" / "auto.state"
    assert copied.read_bytes() == b"state-bytes"


def test_stage_for_boot_places_the_file_for_a_fresh_server(tmp_path):
    from nuzlocke.orchestration.checkpoint import stage_for_boot

    src = tmp_path / "savestates" / "auto.state"
    src.parent.mkdir(parents=True)
    src.write_bytes(b"continue")
    dest = stage_for_boot(tmp_path)
    assert dest == tmp_path / "pokemon-agent-data" / "saves" / "auto.state"
    assert dest.read_bytes() == b"continue"


def test_data_dir_from_ps_matches_the_listening_port():
    from nuzlocke.orchestration.checkpoint import data_dir_from_ps

    text = (
        "pokemon-agent serve --rom red.gb --port 8766 --data-dir /tmp/emu\n"
        "pokemon-agent serve --rom red.gb --port 8765 --data-dir /tmp/other\n"
    )
    assert data_dir_from_ps(text, "8766") == __import__("pathlib").Path("/tmp/emu")
    assert data_dir_from_ps(text, "9999") is None
