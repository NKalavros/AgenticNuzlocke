"""System 3's executable action contract, shared by actor and final arbiter."""

from __future__ import annotations

from pydantic import BaseModel, Field

from nuzlocke.agents import battle
from nuzlocke.environment.screen_text import parse_screen
from nuzlocke.state.models import GameAction, PlayerObservation


class PolicyDecision(BaseModel):
    legal_sequences: dict[str, list[GameAction]] = Field(default_factory=dict)
    required: str | None = None
    forbidden_actions: list[GameAction] = Field(default_factory=list)
    rejection: str | None = None

    def validate(self, actions: list[GameAction]) -> str | None:
        if self.rejection:
            return self.rejection
        if actions and all(a == GameAction.WAIT_60 for a in actions):
            return None
        if any(action in self.forbidden_actions for action in actions):
            return "leader interaction requires final party preparation"
        allowed = self.legal_sequences
        if self.required:
            return None if actions == allowed.get(self.required) else f"required:{self.required}"
        if allowed and actions not in allowed.values():
            return "sequence is not a legal choice on this screen"
        return None


def decision(obs: PlayerObservation, *, first_encounter: bool = False) -> PolicyDecision:
    from nuzlocke.agents.system1 import _special_page, menu_actions
    from nuzlocke.agents.system3 import forced_battle_choice

    if obs.policy.get("wiped"):
        return PolicyDecision(rejection="run ended in a wipe")
    from nuzlocke.agents.move_learning import learning_phase

    if "learning_actions" in obs.policy or learning_phase(obs):
        actions = [GameAction(a) for a in obs.policy.get("learning_actions", ["wait_60"])]
        return PolicyDecision(legal_sequences={"learn_move": actions}, required="learn_move")
    special = _special_page(obs.screen_rows)
    if special and ("evol" in special.reason):
        return PolicyDecision(legal_sequences={"evolution": special.actions}, required="evolution")
    if "shop_actions" in obs.policy:
        return PolicyDecision(
            legal_sequences={"shop": [GameAction(a) for a in obs.policy["shop_actions"]]},
            required="shop",
        )
    from nuzlocke.knowledge.objects import fossil_question, has_fossil

    if not obs.in_battle and fossil_question(obs.map_id, obs.screen_rows) and not has_fossil(obs):
        prompt = parse_screen(obs.screen_rows)
        actions = (
            menu_actions("choose_0", prompt.cursor_row)
            if prompt.menu_rows == ["YES", "NO"] and prompt.cursor_row is not None
            else [GameAction.WAIT_60]
        )
        return PolicyDecision(legal_sequences={"fossil": actions}, required="fossil")
    from nuzlocke.agents.gym_preparation import at_leader, needs_top_up

    if at_leader(obs) and needs_top_up(obs) and not obs.policy.get("preparing"):
        # Healing may require leaving this tile. Block the challenge, not the exit.
        return PolicyDecision(forbidden_actions=[GameAction.PRESS_A, GameAction.A_UNTIL_DIALOG_END])
    if "rotation_actions" in obs.policy:
        return PolicyDecision(
            legal_sequences={
                "rotate_lead": [GameAction(a) for a in obs.policy["rotation_actions"]]
            },
            required="rotate_lead",
        )
    party_cursor = battle.party_cursor(obs)
    if obs.in_battle and party_cursor is not None:
        from nuzlocke.agents.level_buffer import switch_target

        target = switch_target(obs)
        legal = {"back": [GameAction.PRESS_B]}
        for i, mon in enumerate(obs.party):
            if (
                mon.get("hp")
                and not mon.get("dead")
                and not mon.get("ineligible")
                and i != (obs.active_party_slot or 0)
            ):
                legal[f"party_{i}"] = menu_actions(f"choose_{i}", party_cursor)
        return PolicyDecision(
            legal_sequences=legal, required=f"party_{target}" if target is not None else None
        )
    screen = battle.parse_battle(obs.screen_rows)
    if obs.in_battle and screen.kind:
        if screen.kind == "moves" and (
            battle.active_mon(obs).get("dead")
            or battle.active_mon(obs).get("ineligible")
            or forced_battle_choice(obs, first_encounter) is not None
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
