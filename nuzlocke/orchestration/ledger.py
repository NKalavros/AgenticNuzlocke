"""Drives NuzlockeReferee's encounter/death ledgers off step-to-step transitions.

Encounter legality and permadeath tracking are pure bookkeeping — no model
judgment needed — so this stays deterministic Python rather than a separate
LLM agent role.
"""

from __future__ import annotations

from nuzlocke.referee.rules import NuzlockeReferee
from nuzlocke.state.models import PlayerObservation

_FAINT_STATUSES = {"faint", "fainted", "dead"}


class LedgerTracker:
    def __init__(self, referee: NuzlockeReferee) -> None:
        self.referee = referee
        self._prev_in_battle = False
        self._battle_area: str | None = None
        self._battle_party_size = 0
        self._prev_party_status: dict[str, str] = {}

    def update(self, obs: PlayerObservation, *, step: int) -> bool:
        """Advance ledger state for this step; returns True if it just
        committed a new death or encounter outcome (used to gate
        checkpointing away from freshly-decided, still-settling outcomes)."""
        deaths_before = len(self.referee.death_ledger)
        encounters_before = {
            area: entry.get("outcome") for area, entry in self.referee.encounter_ledger.items()
        }
        self._track_encounter(obs)
        self._track_deaths(obs, step=step)
        if len(self.referee.death_ledger) != deaths_before:
            return True
        if len(self.referee.encounter_ledger) != len(encounters_before):
            return True
        return any(
            self.referee.encounter_ledger.get(area, {}).get("outcome") != outcome
            for area, outcome in encounters_before.items()
        )

    def _track_encounter(self, obs: PlayerObservation) -> None:
        battle = obs.battle or {}
        if obs.in_battle and not self._prev_in_battle:
            if battle.get("type") == "wild" and obs.map_name:
                enemy = battle.get("enemy") or {}
                self.referee.freeze_encounter(
                    area=obs.map_name,
                    species=str(enemy.get("species") or "unknown"),
                    outcome="engaged",
                )
                self._battle_area = obs.map_name
            else:
                self._battle_area = None
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
            prev_status = self._prev_party_status.get(nickname)
            if status in _FAINT_STATUSES and prev_status not in _FAINT_STATUSES:
                self.referee.note_faint(mon, context={"map": obs.map_name, "step": step})
            self._prev_party_status[nickname] = status
