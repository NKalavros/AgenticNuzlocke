"""System 3's executable action contract, shared by actor and final arbiter."""

from __future__ import annotations

from pydantic import BaseModel, Field

from nuzlocke.agents import battle
from nuzlocke.environment.screen_text import parse_screen
from nuzlocke.state.models import GameAction, PlayerObservation


class PolicyDecision(BaseModel):
    legal_sequences: dict[str, list[GameAction]] = Field(default_factory=dict)
    required: str | None = None
    rejection: str | None = None

    def validate(self, actions: list[GameAction]) -> str | None:
        if self.rejection:
            return self.rejection
        if actions and all(a == GameAction.WAIT_60 for a in actions):
            return None
        allowed = self.legal_sequences
        if self.required:
            return None if actions == allowed.get(self.required) else f"required:{self.required}"
        if allowed and actions not in allowed.values():
            return "sequence is not a legal choice on this screen"
        return None


def decision(obs: PlayerObservation, *, first_encounter: bool = False) -> PolicyDecision:
    from nuzlocke.agents.system1 import menu_actions
    from nuzlocke.agents.system3 import forced_battle_choice

    if obs.policy.get("wiped"):
        return PolicyDecision(rejection="run ended in a wipe")
    party_cursor = battle.party_cursor(obs)
    if obs.in_battle and party_cursor is not None:
        legal = {"back": [GameAction.PRESS_B]}
        for i, mon in enumerate(obs.party):
            if (
                mon.get("hp")
                and not mon.get("dead")
                and not mon.get("ineligible")
                and i != (obs.active_party_slot or 0)
            ):
                legal[f"party_{i}"] = menu_actions(f"choose_{i}", party_cursor)
        return PolicyDecision(legal_sequences=legal)
    screen = battle.parse_battle(obs.screen_rows)
    if obs.in_battle and screen.kind:
        if screen.kind == "moves" and (
            battle.active_mon(obs).get("dead") or battle.active_mon(obs).get("ineligible")
        ):
            return PolicyDecision(legal_sequences={"back": [GameAction.PRESS_B]}, required="back")
        if screen.kind == "menu":
            choices = battle.menu_questions(obs)["action"]["criteria"]
            sequences = {k: battle.actions_for(screen, k) for k in choices}
            forced = forced_battle_choice(obs, first_encounter)
            if forced:
                sequences[forced] = battle.actions_for(screen, forced)
            active = battle.active_mon(obs)
            if active.get("dead") or active.get("ineligible"):
                sequences.pop("fight", None)
                forced = "pkmn" if "pkmn" in sequences else "run" if "run" in sequences else None
                if forced is None:
                    return PolicyDecision(rejection="no legal battle participant")
            return PolicyDecision(legal_sequences=sequences, required=forced)
        pp = battle._pp(obs)
        sequences = {
            f"move_{i}": battle.actions_for(screen, f"move_{i}")
            for i, name in enumerate(screen.options)
            if pp.get(name.upper(), 1) > 0
        }
        if not sequences:
            # Back to FIGHT permits the game's automatic Struggle when every PP is exhausted.
            return PolicyDecision(legal_sequences={"back": [GameAction.PRESS_B]}, required="back")
        return PolicyDecision(legal_sequences=sequences)
    menu = parse_screen(obs.screen_rows)
    if menu.menu_rows and menu.cursor_row is not None:
        rows = menu.menu_rows
        legal = {f"row_{i}": menu_actions(f"choose_{i}", menu.cursor_row) for i in range(len(rows))}
        legal["back"] = [GameAction.PRESS_B]
        # Actual bag rows carry counts. Never let a fallback use a potion.
        if any("×" in row for row in rows):
            legal = {"back": [GameAction.PRESS_B]}
            for i, row in enumerate(rows):
                allowed = (obs.in_battle and first_encounter and "BALL" in row.upper()) or (
                    not obs.in_battle
                    and obs.policy.get("preparing")
                    and "RARE CANDY" in row.upper()
                )
                if allowed or row.upper() == "CANCEL":
                    legal[f"row_{i}"] = menu_actions(f"choose_{i}", menu.cursor_row)
        # Party menus: screen text plus roster identifies selectable rows.
        for i, row in enumerate(rows):
            for mon in obs.party:
                names = [mon.get("nickname"), mon.get("species")]
                if (
                    any(n and str(n).upper() in row.upper() for n in names)
                    and obs.in_battle
                    and (mon.get("dead") or mon.get("ineligible"))
                ):
                    legal.pop(f"row_{i}", None)
        return PolicyDecision(legal_sequences=legal)
    return PolicyDecision()
