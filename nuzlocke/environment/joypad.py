"""Gen 1 / pokemon-agent joypad ignore bit helpers.

``wJoyIgnore`` (exposed as ``dialog.joy_ignore``):

- bit 5 (0x20): text box locks D-pad; A/B still advance text
- bit 6 (0x40): naming keyboard (letter grid) — agent must decide, do not wait-spin
"""

from __future__ import annotations

JOY_DIALOG = 0x20
JOY_NAMING = 0x40


def is_dialog_lock(joy_ignore: int) -> bool:
    return bool(int(joy_ignore) & JOY_DIALOG)


def is_naming_lock(joy_ignore: int) -> bool:
    return bool(int(joy_ignore) & JOY_NAMING)


def agent_can_act(joy_ignore: int) -> bool:
    """True when the LLM should be prompted (free pad or naming keyboard)."""
    joy = int(joy_ignore)
    return joy == 0 or is_naming_lock(joy)
