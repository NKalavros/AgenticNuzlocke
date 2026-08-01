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
