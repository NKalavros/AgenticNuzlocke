"""Joypad ignore bit helpers."""

from nuzlocke.environment.joypad import (
    JOY_DIALOG,
    JOY_NAMING,
    agent_can_act,
    is_dialog_lock,
    is_naming_lock,
)


def test_dialog_and_naming_bits() -> None:
    assert is_dialog_lock(JOY_DIALOG)
    assert is_naming_lock(JOY_NAMING)
    assert is_naming_lock(64)
    assert not is_dialog_lock(64)
    assert not is_naming_lock(JOY_DIALOG)


def test_agent_can_act() -> None:
    assert agent_can_act(0)
    assert agent_can_act(JOY_NAMING)
    assert agent_can_act(64)
    assert not agent_can_act(JOY_DIALOG)
    assert not agent_can_act(0x01)
