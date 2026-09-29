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
        self.duplicate_encounter = False
        self._battle_owned = 0
        self._encounter_classified = False
        # (in battle, lowest HP fraction in the party, map id) from the last observation.
        self._prev_state: tuple[bool, float, object] | None = None

    def _ledger_snapshot(self) -> tuple[int, dict[str, object]]:
        encounters = self.referee.encounter_ledger
        outcomes = {area: entry.get("outcome") for area, entry in encounters.items()}
        return len(self.referee.death_ledger), outcomes

    def update(self, obs: PlayerObservation, *, step: int) -> bool:
        """Advance ledger state for this step. True when it just committed a new death or
        encounter outcome. The current loop commits paired checkpoints after each cycle."""
        before = self._ledger_snapshot()
        self.referee.identify(obs)
        self._track_encounter(obs)
        self._track_deaths(obs, step=step)
        self._track_wipe(obs, step=step)
        return self._ledger_snapshot() != before

    def _track_encounter(self, obs: PlayerObservation) -> None:
        from nuzlocke.referee.families import family

        battle = obs.battle or {}
        self.referee.balls_acquired |= any(
            "ball" in str(item.get("item") or "").casefold() and item.get("quantity", 1) > 0
            for item in obs.bag
        )
        if obs.in_battle and not self._prev_in_battle:
            self.referee.battle_eligible = {
                m["capture_id"]
                for m in obs.party
                if not m.get("dead") and (m.get("level") or 0) <= self.referee.current_cap
            }
            self._battle_area = None
            self.first_encounter = False
            self.duplicate_encounter = False
            self._encounter_classified = False
            self._battle_party_size = len(obs.party)
            self._battle_owned = obs.flags.get("pokedex_owned", 0)
        if obs.in_battle and not self._encounter_classified:
            area = str(obs.map_id) if obs.map_id is not None else obs.map_name
            species = str((battle.get("enemy") or {}).get("species") or "unknown")
            # Battle flags change before the enemy structure finishes loading.
            if battle.get("type") == "wild" and (species == "unknown" or "?" in species):
                self._prev_in_battle = True
                return
            if battle.get("type") not in {"wild", "trainer"}:
                self._prev_in_battle = True
                return
            self._encounter_classified = True
            clauses = self.referee.rules.get("clauses", {})
            duplicate = (
                clauses.get("duplicates_clause", False) or clauses.get("species_clause", False)
            ) and family(species) in self.referee.owned_families
            self.duplicate_encounter = duplicate
            if (
                battle.get("type") == "wild"
                and area
                and self.referee.balls_acquired
                and not duplicate
            ):
                self.first_encounter = area not in self.referee.encounter_ledger
                if self.first_encounter:
                    self.referee.freeze_encounter(area=area, species=species, outcome="engaged")
                    self._battle_area = area
        elif not obs.in_battle and self._prev_in_battle:
            if self._battle_area:
                caught = (
                    len(obs.party) > self._battle_party_size
                    or obs.flags.get("pokedex_owned", 0) > self._battle_owned
                )
                outcome = "caught" if caught else "forfeited"
                if caught:
                    self.referee.owned_families.add(
                        family(self.referee.encounter_ledger[self._battle_area]["species"])
                    )
                self.referee.resolve_encounter(self._battle_area, outcome)
            self.first_encounter = False
            self.duplicate_encounter = False
            self._battle_area = None
            self.referee.battle_eligible.clear()
        self._prev_in_battle = obs.in_battle

    def snapshot(self) -> dict:
        return dict(self.__dict__, referee=None)

    def restore(self, data: dict) -> None:
        self.__dict__.update({k: v for k, v in data.items() if k != "referee"})

    def _track_deaths(self, obs: PlayerObservation, *, step: int) -> None:
        for mon in obs.party:
            nickname = mon.get("capture_id") or mon.get("nickname") or mon.get("species") or ""
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
        if obs.battle_lost or all(is_fainted(mon) or self.referee.is_dead(mon) for mon in party):
            self.referee.note_wipe("every POKéMON fainted", party, context)
        elif self._prev_state is not None:
            was_in_battle, was_lowest, was_map = self._prev_state
            if (
                (was_in_battle or was_lowest < 1)
                and was_lowest < 1
                and not obs.in_battle
                and lowest == 1.0
                and (was_map != obs.map_id)
                and obs.map_id in {0, 37, 41, 58, 64, 68}
            ):
                self.referee.note_wipe(
                    f"blacked out; woke up healed in {obs.map_name}", party, context
                )
        self._prev_state = (obs.in_battle, lowest, obs.map_id)
