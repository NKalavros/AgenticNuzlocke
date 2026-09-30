"""Change the lead through the ordinary party menu before it can share unwanted XP."""

import re

from nuzlocke.agents.battle import party_cursor
from nuzlocke.agents.level_buffer import switch_target
from nuzlocke.environment.evolution import evolution_phase
from nuzlocke.environment.screen_text import find_boxes, parse_screen
from nuzlocke.state.models import GameAction as A


def key(text):
    return re.sub(r"[^A-Z]", "", text.upper().replace("É", "E"))


def toward(cursor, wanted):
    if cursor is None:
        return [A.WAIT_60]
    return [A.PRESS_A if cursor == wanted else A.WALK_DOWN if cursor < wanted else A.WALK_UP]


class LeadRotation:
    def __init__(self):
        self.pending = None

    def snapshot(self):
        return self.pending

    def restore(self, state):
        self.pending = dict(state) if state else None

    def observe(self, obs, record):
        if obs.in_battle:
            # A trainer can interrupt while START is opening. Reassess health after
            # the battle instead of resuming a stale choice with a now-injured target.
            self.pending = None
            return
        if (
            self.pending
            and not self.pending.get("verified")
            and obs.party
            and obs.party[0].get("capture_id") == self.pending["target"]
        ):
            self.pending["verified"] = True
            record("lead_rotated", dict(self.pending))

    def turn(self, obs, record=lambda *_: None):
        self.observe(obs, record)
        if obs.in_battle or obs.cutscene or evolution_phase(obs.screen_rows):
            return [], ""
        if self.pending is None:
            if obs.policy.get("preparing") or find_boxes(obs.screen_rows):
                return [], ""
            slot = switch_target(obs)
            if slot is None or not obs.party[slot].get("capture_id"):
                return [], ""
            self.pending = {
                "target": obs.party[slot]["capture_id"],
                "species": obs.party[slot].get("species"),
                "old_lead": obs.party[0].get("capture_id"),
                "verified": False,
            }
            record("lead_rotation_choice", dict(self.pending))
        actions = self.actions(obs)
        if actions is None:
            self.pending = None
            return [], ""
        self.pending["cycles"] = self.pending.get("cycles", 0) + 1
        if self.pending["cycles"] > 40:
            raise RuntimeError(
                "Lead rotation did not finish after 40 cycles; paused for inspection"
            )
        return actions, f"reserve XP: rotate lead to {self.pending['species']}"

    def actions(self, obs):
        if not self.pending or obs.in_battle or obs.cutscene or evolution_phase(obs.screen_rows):
            return None
        p = self.pending
        if obs.party and obs.party[0].get("capture_id") == p["target"]:
            return (
                [A.PRESS_B, A.WAIT_60]
                if find_boxes(obs.screen_rows) or party_cursor(obs) is not None
                else None
            )
        slot = next(
            (i for i, m in enumerate(obs.party) if m.get("capture_id") == p["target"]), None
        )
        if slot is None:
            raise RuntimeError("lead rotation lost its target Pokémon")
        screen = parse_screen(obs.screen_rows)
        rows = [key(row) for row in screen.menu_rows]
        if "SWITCH" in rows:
            return toward(screen.cursor_row, rows.index("SWITCH"))
        cursor = party_cursor(obs)
        if cursor is not None:
            moving = "MOVEPOKEMON" in key(" ".join(screen.text_lines))
            return toward(cursor, 0 if moving else slot)
        if "POKEMON" in rows:
            return toward(screen.cursor_row, rows.index("POKEMON"))
        if find_boxes(obs.screen_rows):
            return [A.WAIT_60]  # A blank menu is still being drawn; no repeated START.
        return [A.PRESS_START]
