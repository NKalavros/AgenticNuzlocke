"""Bits of pokemon-agent's ``dialog.joy_ignore``, which is really 0xD730 (wStatusFlags5).

Bit 6 is set on the naming keyboard's letter grid and on the Pokédex page shown before the
starter's YES/NO. Bit 5 is not a dialog signal on Red Star: it reads 0 through real text.
"""

from __future__ import annotations

JOY_NAMING = 0x40


def is_naming_lock(joy_ignore: int) -> bool:
    return bool(int(joy_ignore) & JOY_NAMING)


def agent_can_act(joy_ignore: int) -> bool:
    """True when the LLM should be prompted (free pad or naming keyboard)."""
    joy = int(joy_ignore)
    return joy == 0 or is_naming_lock(joy)
