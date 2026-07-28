"""Minimal deterministic referee for MVP scaffolding."""

from __future__ import annotations

from typing import Any

from nuzlocke.state.models import PlayerObservation


class NuzlockeReferee:
    def __init__(self, rules: dict[str, Any]) -> None:
        self.rules = rules
        self.encounter_ledger: dict[str, dict[str, Any]] = {}
        self.death_ledger: list[dict[str, Any]] = []
        self.current_milestone = "brock"
        caps = (rules.get("level_caps") or {})
        self.current_cap = int(caps.get("brock", 14))

    def assert_party_legal(self, obs: PlayerObservation) -> list[str]:
        violations: list[str] = []
        for mon in obs.party:
            level = mon.get("level")
            if level is not None and int(level) > self.current_cap:
                violations.append(
                    f"{mon.get('nickname') or mon.get('species')} "
                    f"level {level} > cap {self.current_cap}"
                )
            status = (mon.get("status") or "").lower()
            if status in {"faint", "fainted", "dead"}:
                violations.append(
                    f"{mon.get('nickname') or mon.get('species')} is fainted/dead"
                )
        return violations

    def note_faint(self, mon: dict[str, Any], context: dict[str, Any]) -> None:
        entry = {
            "species": mon.get("species"),
            "nickname": mon.get("nickname"),
            **context,
        }
        self.death_ledger.append(entry)

    def freeze_encounter(self, area: str, species: str, outcome: str) -> None:
        if area in self.encounter_ledger:
            return
        self.encounter_ledger[area] = {
            "species": species,
            "outcome": outcome,
        }
