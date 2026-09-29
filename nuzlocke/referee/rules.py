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
        # Why the run is lost (every POKéMON fainted), or None. A Nuzlocke ends there.
        self.wiped: str | None = None
        self.roster: dict[str, dict[str, Any]] = {}
        self.owned_families: set[str] = set()
        self.balls_acquired = False
        self.battle_eligible: set[str] = set()
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
            identity = mon.get("capture_id")
            grandfathered = obs.in_battle and identity in self.battle_eligible
            if level is not None and int(level) > self.current_cap and not grandfathered:
                violations.append(f"{name} level {level} > cap {self.current_cap}")
            if is_fainted(mon) or self.is_dead(mon):
                violations.append(f"{name} is fainted/dead")
        return violations

    def note_faint(self, mon: dict[str, Any], context: dict[str, Any]) -> None:
        nickname = mon.get("nickname") or mon.get("species")
        identity = mon.get("capture_id") or nickname
        if all(
            (entry.get("capture_id") or entry.get("nickname")) != identity
            for entry in self.death_ledger
        ):
            self.death_ledger.append(
                {
                    "species": mon.get("species"),
                    "nickname": nickname,
                    "capture_id": mon.get("capture_id"),
                    **context,
                }
            )

    def note_wipe(self, reason: str, party: list[dict[str, Any]], context: dict[str, Any]) -> None:
        """Every POKéMON fainted. Each is dead, and the run is over."""
        for mon in party:
            self.note_faint(mon, context)
        self.wiped = self.wiped or reason

    def freeze_encounter(self, area: str, species: str, outcome: str) -> None:
        self.encounter_ledger.setdefault(area, {"species": species, "outcome": outcome})

    def resolve_encounter(self, area: str, outcome: str) -> None:
        """Update a previously-frozen encounter's outcome (caught/fainted/fled)."""
        if area in self.encounter_ledger and self.encounter_ledger[area]["outcome"] == "engaged":
            self.encounter_ledger[area]["outcome"] = outcome

    def is_dead(self, mon: dict[str, Any]) -> bool:
        identity = mon.get("capture_id")
        return any(
            (identity == e.get("capture_id"))
            if identity and e.get("capture_id")
            else (mon.get("nickname") or mon.get("species")) == e.get("nickname")
            for e in self.death_ledger
        )

    def identify(self, obs: PlayerObservation) -> None:
        from nuzlocke.referee.families import family

        used: set[str] = set()
        for mon in obs.party:
            fam = family(str(mon.get("species") or mon.get("nickname") or "unknown"))
            ot = mon.get("ot_id")
            match = next(
                (
                    key
                    for key, value in self.roster.items()
                    if key not in used and value["family"] == fam and value.get("ot_id") == ot
                ),
                None,
            )
            if match is None:
                match = f"capture-{len(self.roster) + 1:04d}"
                self.roster[match] = {"family": fam, "ot_id": ot}
            used.add(match)
            mon["capture_id"] = match
            mon["dead"] = self.is_dead(mon)
            mon["ineligible"] = mon["dead"] or (
                (mon.get("level") or 0) > self.current_cap
                and not (obs.in_battle and match in self.battle_eligible)
            )
            self.roster[match].update(species=mon.get("species"), nickname=mon.get("nickname"))
            pp_ceiling = self.roster[match].setdefault("observed_max_pp", {})
            for move in mon.get("moves", []):
                key = str(move.get("id") or move.get("name"))
                pp_ceiling[key] = max(pp_ceiling.get(key, 0), move.get("pp") or 0)
                move["observed_max_pp"] = pp_ceiling[key]
            self.owned_families.add(fam)

    def snapshot(self) -> dict[str, Any]:
        return {
            "encounters": self.encounter_ledger,
            "deaths": self.death_ledger,
            "wiped": self.wiped,
            "roster": self.roster,
            "owned_families": sorted(self.owned_families),
            "balls_acquired": self.balls_acquired,
            "battle_eligible": sorted(self.battle_eligible),
        }

    def restore(self, data: dict[str, Any]) -> None:
        self.encounter_ledger = data["encounters"]
        self.death_ledger = data["deaths"]
        self.wiped = data["wiped"]
        self.roster = data["roster"]
        self.owned_families = set(data["owned_families"])
        self.balls_acquired = data["balls_acquired"]
        self.battle_eligible = set(data["battle_eligible"])


def is_fainted(mon: dict[str, Any]) -> bool:
    """HP 0. pokemon-agent reports a fainted POKéMON's status as "OK", never "FNT"."""
    if (mon.get("status") or "").lower() in FAINT_STATUSES:
        return True
    return mon.get("hp") == 0 and bool(mon.get("max_hp"))
