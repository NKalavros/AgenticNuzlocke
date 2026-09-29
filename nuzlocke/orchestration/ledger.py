"""Drives NuzlockeReferee's encounter/death ledgers off step-to-step transitions.

Encounter legality and permadeath tracking are pure bookkeeping, so this stays deterministic
Python rather than an LLM agent role.
"""

from __future__ import annotations

from nuzlocke.referee.rules import FAINT_STATUSES, NuzlockeReferee
from nuzlocke.state.models import PlayerObservation


class LedgerTracker:
    def __init__(self, referee: NuzlockeReferee) -> None:
        self.referee = referee
        self._prev_in_battle = False
        self._battle_area: str | None = None
        self._battle_party_size = 0
        self._prev_party_status: dict[str, str] = {}

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
        return self._ledger_snapshot() != before

    def _track_encounter(self, obs: PlayerObservation) -> None:
        battle = obs.battle or {}
        if obs.in_battle and not self._prev_in_battle:
            self._battle_area = None
            if battle.get("type") == "wild" and obs.map_name:
                enemy = battle.get("enemy") or {}
                self.referee.freeze_encounter(
                    area=obs.map_name,
                    species=str(enemy.get("species") or "unknown"),
                    outcome="engaged",
                )
                self._battle_area = obs.map_name
            self._battle_party_size = len(obs.party)
        elif not obs.in_battle and self._prev_in_battle and self._battle_area:
            outcome = "caught" if len(obs.party) > self._battle_party_size else "resolved"
            self.referee.resolve_encounter(self._battle_area, outcome)
            self._battle_area = None
        self._prev_in_battle = obs.in_battle

    def _track_deaths(self, obs: PlayerObservation, *, step: int) -> None:
        for mon in obs.party:
            nickname = mon.get("nickname") or mon.get("species") or ""
            status = (mon.get("status") or "").lower()
            was_fainted = self._prev_party_status.get(nickname) in FAINT_STATUSES
            if status in FAINT_STATUSES and not was_fainted:
                self.referee.note_faint(mon, context={"map": obs.map_name, "step": step})
            self._prev_party_status[nickname] = status
