"""Drives NuzlockeReferee's encounter/death ledgers off step-to-step transitions.

Encounter legality and permadeath tracking are pure bookkeeping, so this stays deterministic
Python rather than an LLM agent role.
"""

from __future__ import annotations

from nuzlocke.referee.rules import NuzlockeReferee, is_fainted
from nuzlocke.state.models import PlayerObservation


class LedgerTracker:
    def __init__(self, referee: NuzlockeReferee) -> None:
        self.referee = referee
        self._prev_in_battle = False
        self._battle_area: str | None = None
        self._battle_party_size = 0
        self._prev_fainted: dict[str, bool] = {}
        # This wild battle is the area's first encounter since the player had Poké Balls.
        self.first_encounter = False
        # (in battle, lowest HP fraction in the party, map id) from the last observation.
        self._prev_state: tuple[bool, float, object] | None = None

    def _ledger_snapshot(self) -> tuple[int, dict[str, object]]:
        encounters = self.referee.encounter_ledger
        outcomes = {area: entry.get("outcome") for area, entry in encounters.items()}
        return len(self.referee.death_ledger), outcomes

    def update(self, obs: PlayerObservation, *, step: int) -> bool:
        """Advance ledger state for this step. True when it just committed a new death or
        encounter outcome, which checkpointing waits out while it settles."""
        before = self._ledger_snapshot()
        self._track_encounter(obs)
        self._track_deaths(obs, step=step)
        self._track_wipe(obs, step=step)
        return self._ledger_snapshot() != before

    def _track_encounter(self, obs: PlayerObservation) -> None:
        battle = obs.battle or {}
        if obs.in_battle and not self._prev_in_battle:
            self._battle_area = None
            self.first_encounter = False
            balls = any("ball" in str(item.get("item") or "").casefold() for item in obs.bag)
            # Encounters before the player has Poké Balls do not count (rules_red.yaml).
            if battle.get("type") == "wild" and obs.map_name and balls:
                self.first_encounter = obs.map_name not in self.referee.encounter_ledger
                enemy = battle.get("enemy") or {}
                self.referee.freeze_encounter(
                    area=obs.map_name,
                    species=str(enemy.get("species") or "unknown"),
                    outcome="engaged",
                )
                self._battle_area = obs.map_name
            self._battle_party_size = len(obs.party)
        elif not obs.in_battle and self._prev_in_battle and self._battle_area:
            self.first_encounter = False
            outcome = "caught" if len(obs.party) > self._battle_party_size else "resolved"
            self.referee.resolve_encounter(self._battle_area, outcome)
            self._battle_area = None
        self._prev_in_battle = obs.in_battle

    def _track_deaths(self, obs: PlayerObservation, *, step: int) -> None:
        for mon in obs.party:
            nickname = mon.get("nickname") or mon.get("species") or ""
            fainted = is_fainted(mon)
            if fainted and not self._prev_fainted.get(nickname):
                self.referee.note_faint(mon, context={"map": obs.map_name, "step": step})
            self._prev_fainted[nickname] = fainted

    def _track_wipe(self, obs: PlayerObservation, *, step: int) -> None:
        """Every POKéMON at 0 HP, or the blackout itself: a battle at almost no HP, then a
        different map with the whole party healed. Gen 1 heals and warps the player home or to
        the last Pokémon Center, so the fainted party is usually never observed (run
        20260929-030330-de1d51 blacked out twice unnoticed)."""
        party = [mon for mon in obs.party if mon.get("max_hp")]
        if not party:
            return
        lowest = min(mon.get("hp", 0) / mon["max_hp"] for mon in party)
        context = {"map": obs.map_name, "step": step}
        if all(is_fainted(mon) for mon in party):
            self.referee.note_wipe("every POKéMON fainted", party, context)
        elif self._prev_state is not None:
            was_in_battle, was_lowest, was_map = self._prev_state
            if (
                was_in_battle
                and was_lowest <= 0.2
                and not obs.in_battle
                and lowest == 1.0
                and (was_map != obs.map_id)
            ):
                self.referee.note_wipe(
                    f"blacked out; woke up healed in {obs.map_name}", party, context
                )
        self._prev_state = (obs.in_battle, lowest, obs.map_id)
