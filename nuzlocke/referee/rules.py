"""Minimal deterministic referee: level caps, permadeath, encounter legality."""

from __future__ import annotations

from typing import Any

from nuzlocke.state.models import PlayerObservation

# Matches config/rules_red.yaml's level_caps keys, in badge-earned order.
MILESTONE_ORDER: tuple[str, ...] = (
    "brock",
    "misty",
    "lt_surge",
    "erika",
    "koga",
    "saber",
    "blaine",
    "giovanni",
    "elite_four",
)
FAINT_STATUSES = {"faint", "fainted", "dead"}


class NuzlockeReferee:
    def __init__(self, rules: dict[str, Any]) -> None:
        self.rules = rules
        self.encounter_ledger: dict[str, dict[str, Any]] = {}
        self.death_ledger: list[dict[str, Any]] = []
        self._caps = rules.get("level_caps") or {}
        self.current_milestone = MILESTONE_ORDER[0]
        self.current_cap = int(self._caps.get(self.current_milestone, 100))

    def advance(self, badge_count: int) -> None:
        """Badge count N targets MILESTONE_ORDER[N], clamped at the Elite Four."""
        idx = min(max(int(badge_count), 0), len(MILESTONE_ORDER) - 1)
        self.current_milestone = MILESTONE_ORDER[idx]
        self.current_cap = int(self._caps.get(self.current_milestone, self.current_cap))

    def assert_party_legal(self, obs: PlayerObservation) -> list[str]:
        violations: list[str] = []
        for mon in obs.party:
            name = mon.get("nickname") or mon.get("species")
            level = mon.get("level")
            if level is not None and int(level) > self.current_cap:
                violations.append(f"{name} level {level} > cap {self.current_cap}")
            if (mon.get("status") or "").lower() in FAINT_STATUSES:
                violations.append(f"{name} is fainted/dead")
        return violations

    def note_faint(self, mon: dict[str, Any], context: dict[str, Any]) -> None:
        nickname = mon.get("nickname") or mon.get("species")
        if all(entry.get("nickname") != nickname for entry in self.death_ledger):
            self.death_ledger.append(
                {"species": mon.get("species"), "nickname": nickname, **context}
            )

    def freeze_encounter(self, area: str, species: str, outcome: str) -> None:
        self.encounter_ledger.setdefault(area, {"species": species, "outcome": outcome})

    def resolve_encounter(self, area: str, outcome: str) -> None:
        """Update a previously-frozen encounter's outcome (caught/fainted/fled)."""
        if area in self.encounter_ledger:
            self.encounter_ledger[area]["outcome"] = outcome
