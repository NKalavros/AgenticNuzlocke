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


def test_data_dir_from_ps_matches_the_wrapped_server():
    from nuzlocke.orchestration.checkpoint import data_dir_from_ps

    text = "/venv/bin/python -m nuzlocke.environment.pa_serve serve --rom red.gb --port 8765 --data-dir /tmp/emu\n"
    assert data_dir_from_ps(text, "8765") == __import__("pathlib").Path("/tmp/emu")
