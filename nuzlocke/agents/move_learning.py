"""Move-learning transactions, shared by System 1 and the final action policy.

The visible learning dialog gates scratch RAM (wWhichPokemon/wMoveNum). A saved
choice survives YES/NO, the forget list, result text, and a controller restart.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

import yaml

from nuzlocke.agents.jev_policy import accepts
from nuzlocke.environment.screen_text import parse_screen
from nuzlocke.state.models import GameAction as A

HM = {15, 19, 57, 70, 148}


def normalized(name):
    return re.sub(r"[^A-Z0-9]", "", str(name).upper())


@lru_cache(maxsize=1)
def move_data():
    return yaml.safe_load((Path(__file__).parents[1] / "knowledge/moves_red.yaml").read_text())


def facts(move):
    data = dict(move_data().get(move.get("id"), {}))
    data.update({k: v for k, v in move.items() if k in {"id", "name", "pp"}})
    data["source"] = "vanilla Red baseline; ROM may differ"
    if data.get("effect") == "FOCUS_ENERGY_EFFECT":
        data["note"] = "Gen 1 Focus Energy reduces critical-hit chance; low priority."
    return data


def learning_phase(obs, pending=None):
    screen = parse_screen(obs.screen_rows)
    text = " ".join(screen.text_lines).upper()
    compact = normalized(text)
    if not text:
        return None
    if (
        any(word in compact for word in ("FORGET", "FORGOTTEN", "WHICHMOVE"))
        and screen.menu_rows
        and screen.menu_rows != ["YES", "NO"]
    ):
        return "forget"
    if screen.menu_rows == ["YES", "NO"]:
        if "STOPLEARNING" in compact or "ABANDON" in compact:
            return "abandon"
        if any(k in compact for k in ("MAKEROOM", "DELETE", "TRYINGTOLEARN", "FORGET")):
            return "offer"
    if any(
        k in compact
        for k in (
            "TRYINGTOLEARN",
            "LEARNED",
            "DIDNOTLEARN",
            "CANTLEARNMORE",
            "FORGOT",
            "POOF",
            "STOPLEARNING",
            "MAKEROOM",
            "WHICHMOVE",
        )
    ):
        if not pending and any(k in compact for k in ("LEARNED", "FORGOT", "POOF")):
            mid = obs.learning_move_id
            slot = obs.learning_party_slot
            if mid not in move_data() or slot is None or not 0 <= slot < len(obs.party):
                return None
            mon = obs.party[slot]
            names = (move_data()[mid]["name"], mon.get("nickname"), mon.get("species"))
            if not any(n and normalized(n) in compact for n in names):
                return None
        return "page"
    # Partly printed pages between the recognized stages must not get a B mash.
    if pending and not screen.menu_rows:
        return "page"
    return None


def legal_choices(mon, new_id):
    moves = mon.get("moves", [])
    new = move_data().get(new_id, {})
    damaging = [
        i for i, move in enumerate(moves) if move_data().get(move.get("id"), {}).get("power", 0) > 1
    ]
    choices = {"keep": "Keep the existing moves and decline the new move."}
    for i, move in enumerate(moves):
        if move.get("id") in HM:
            continue
        if new.get("power", 0) <= 1 and damaging == [i]:
            continue  # A status move cannot remove the only reliable damaging move.
        choices[f"replace_{i}"] = (
            f"Forget {move['name']} to learn {new.get('name', new_id)}; current move: {json.dumps(facts(move))}"
        )
    return choices


def fallback_choice(mon, new_id, choices):
    # Conservative utility ordering for an unsure Jev answer. Not a damage calculation.
    status = {
        14: 65,
        45: 10,
        73: 65,
        74: 35,
        77: 35,
        78: 65,
        79: 90,
        81: 8,
        92: 65,
        95: 80,
        104: 30,
        105: 80,
        106: 4,
        110: 4,
        113: 50,
        115: 50,
        116: 0,
        135: 80,
        147: 100,
    }

    def score(mid):
        m = move_data().get(mid, {})
        if m.get("power", 0) > 1:
            return 40 + m["power"] * m.get("accuracy", 100) / 100
        return status.get(mid, 20)

    options = [
        (score(m.get("id")), i)
        for i, m in enumerate(mon.get("moves", []))
        if f"replace_{i}" in choices
    ]
    if not options:
        return "keep"
    old, i = min(options)
    return f"replace_{i}" if score(new_id) > old else "keep"


def _toward(cursor, wanted):
    if cursor is None:
        return [A.WAIT_60]
    return [A.PRESS_A if cursor == wanted else A.WALK_DOWN if cursor < wanted else A.WALK_UP]


class MoveLearner:
    def __init__(self):
        self.pending = None

    def snapshot(self):
        return self.pending

    def restore(self, state):
        self.pending = dict(state) if state else None

    def observe(self, obs, record):
        p = self.pending
        if not p or p.get("verified"):
            return
        mon = next(
            (
                m
                for m in obs.party
                if p.get("capture_id") and m.get("capture_id") == p["capture_id"]
            ),
            None,
        )
        if mon is None and p["slot"] < len(obs.party):
            mon = obs.party[p["slot"]]
        if mon is None:
            return
        ids = [m.get("id") for m in mon.get("moves", [])]
        if p["new_id"] in ids:
            expected = p.get("replace_slot")
            if expected is not None and ids[expected] != p["new_id"]:
                raise RuntimeError("learned move appeared in the wrong slot")
            p["verified"] = True
            record("move_learned", {**p, "after": ids})
        elif "DIDNOTLEARN" in normalized(" ".join(parse_screen(obs.screen_rows).text_lines)):
            if p["choice"] != "keep":
                raise RuntimeError("move learning was canceled despite a replacement choice")
            p["verified"] = True
            record("move_declined", dict(p))

    def turn(self, obs, *, decide=None, record=lambda *_: None, confidence_floor=0.55):
        self.observe(obs, record)
        if (
            self.pending
            and self.pending.get("verified")
            and obs.learning_move_id != self.pending["new_id"]
        ):
            self.pending = None
        phase = learning_phase(
            obs, self.pending if not (self.pending or {}).get("verified") else None
        )
        if phase is None:
            if self.pending and self.pending.get("verified"):
                self.pending = None
            elif self.pending and not parse_screen(obs.screen_rows).menu_rows:
                return [A.WAIT_60], "wait for move-learning result"
            elif self.pending:
                raise RuntimeError("move-learning UI closed without a verified result")
            return [], ""
        if self.pending is None or self.pending.get("choice") is None:
            slot, mid = obs.learning_party_slot, obs.learning_move_id
            if slot is None or not 0 <= slot < len(obs.party) or mid not in move_data():
                raise RuntimeError("move-learning screen lacks a verified learner or move ID")
            mon = obs.party[slot]
            ids = [m.get("id") for m in mon.get("moves", [])]
            self.pending = {
                "slot": slot,
                "capture_id": mon.get("capture_id"),
                "species": mon.get("species"),
                "new_id": mid,
                "new_move": move_data()[mid]["name"],
                "before": ids,
                "choice": "automatic" if len(ids) < 4 or mid in ids else None,
            }
            if self.pending["choice"] is None:
                choices = legal_choices(mon, mid)
                fallback = fallback_choice(mon, mid, choices)
                choice = fallback
                if decide:
                    state = {
                        "scene": "move_learning",
                        "pokemon": {**mon, "moves": [facts(m) for m in mon.get("moves", [])]},
                        "new_move": facts({"id": mid}),
                        "party": obs.party,
                        "goal": "Improve this Pokémon's permanent moveset for the Nuzlocke. Preserve strong attacks; prefer useful sleep/paralysis and coverage over redundant weak stat moves.",
                        "suggested_choice": fallback,
                    }
                    questions = {
                        "action": {
                            "type": "choice",
                            "instructions": state["goal"],
                            "criteria": choices,
                        }
                    }
                    read = decide(state=state, questions=questions, allowed=set(choices))
                    accepted = accepts(read, confidence_floor) and read.action in choices
                    if accepted:
                        choice = read.action
                    record(
                        "jev_call",
                        {
                            "scene": "move_learning",
                            "menu": choices,
                            "state_bytes": len(json.dumps(state)),
                            "choice": read.action,
                            "confidence": read.confidence,
                            "probabilities": read.probabilities,
                            "accepted": accepted,
                            "latency_s": read.latency_s,
                        },
                    )
                self.pending["choice"] = choice
                if choice.startswith("replace_"):
                    self.pending["replace_slot"] = int(choice.split("_")[1])
            record("move_learning_choice", dict(self.pending))
        actions = self.actions(obs)
        return (
            actions or [A.WAIT_60],
            f"move learning: {self.pending['species']} {self.pending['new_move']} ({self.pending['choice']}); {phase}",
        )

    def actions(self, obs):
        p = self.pending
        phase = learning_phase(obs, p if not (p or {}).get("verified") else None)
        if phase is None:
            return None
        if not p or p.get("choice") is None:
            return [A.WAIT_60]
        if phase in {"offer", "forget", "abandon"} and (
            obs.learning_move_id != p["new_id"] or obs.learning_party_slot != p["slot"]
        ):
            raise RuntimeError("move-learning prompt no longer matches the saved learner/choice")
        screen = parse_screen(obs.screen_rows)
        if phase in {"offer", "abandon"}:
            yes = p["choice"] != "keep" if phase == "offer" else p["choice"] == "keep"
            return _toward(screen.cursor_row, 0 if yes else 1)
        if phase == "forget":
            if p["choice"] == "keep":
                return [A.PRESS_B]  # Deliberately opens stop-learning confirmation.
            slot = p.get("replace_slot")
            if slot is None:
                return [A.WAIT_60]
            expected = normalized(move_data()[p["before"][slot]]["name"])
            row = next(
                (i for i, name in enumerate(screen.menu_rows) if normalized(name) == expected), None
            )
            if row is None:
                return [A.WAIT_60]  # Never delete a different move on a stale/partial menu.
            return _toward(screen.cursor_row, row)
        return [A.PRESS_A]  # One page only; re-read prompts and results before the next input.
