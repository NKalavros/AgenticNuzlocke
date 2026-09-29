"""Joypad ignore bit helpers."""

from nuzlocke.environment.joypad import JOY_NAMING, agent_can_act, is_naming_lock


def test_naming_bit() -> None:
    assert is_naming_lock(JOY_NAMING)
    assert is_naming_lock(64)
    assert not is_naming_lock(0x20)


def test_agent_can_act() -> None:
    assert agent_can_act(0)
    assert agent_can_act(JOY_NAMING)
    assert agent_can_act(64)
    assert not agent_can_act(0x20)
    assert not agent_can_act(0x01)
