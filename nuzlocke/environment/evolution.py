"""Recognize evolution text without treating an NPC's 'What?' as an animation."""

import re

from nuzlocke.referee.type_chart import SPECIES_TYPES


def evolution_phase(rows):
    lines = [re.sub(r"[│┌┐└┘─▼]", "", row).strip() for row in rows]
    text = " ".join(line for line in lines if line).upper()
    if re.search(r"\b(?:EVOLVED|STOPPED EVOLVING)\b", text):
        return "result"
    if re.search(r"\bIS EVOLV", text):
        return "animation"
    # Species names are retained by this runner. Match a partially printed evolution
    # announcement, not arbitrary sentences beginning with 'What?'.
    if text.startswith("WHAT?"):
        tail = re.sub(r"[^A-Z0-9♂♀]", "", text[5:])
        if not tail or any(
            (name + "ISEVOLVING").startswith(tail)
            for species in SPECIES_TYPES
            if (name := re.sub(r"[^A-Z0-9♂♀]", "", species.upper()))
        ):
            return "animation"
    return None
