"""Verified PC transactions selected by capture identity, through normal menus."""

import re
from copy import deepcopy

from nuzlocke.agents.lead_rotation import LeadRotationError, key, toward
from nuzlocke.environment.screen_text import find_boxes, parse_screen
from nuzlocke.environment.storage import boxed
from nuzlocke.state.models import GameAction as A


class StorageController:
    def __init__(self):
        self.pending = None
        self.progress = None
        self.cycles = 0
        self.closing = False

    def snapshot(self):
        return deepcopy(vars(self))

    def restore(self, state):
        if state:
            self.__dict__.update(deepcopy(state))

    def turn(self, obs, desired, record):
        if obs.in_battle:
            return [], ""
        storage = obs.storage or {}
        if not storage.get("complete"):
            raise LeadRotationError("PC roster is incomplete; cannot verify transfers")
        ids = [m["capture_id"] for m in obs.party]
        if self.pending:
            p = self.pending
            expected = [i for i in p["before"] if i != p["target"]] if p["operation"] == "deposit" else p["before"] + [p["target"]]
            complete = storage["active_box"] == p["box"] if p["operation"] == "box" else ids == expected
            if complete:
                locations = {m["capture_id"]: m["box"] for m in boxed(obs)}
                if p["operation"] == "deposit" and locations.get(p["target"]) != p["box"]:
                    raise LeadRotationError("Deposited Pokémon is missing from its destination box")
                record("storage_verified", p)
                self.pending, self.closing, self.cycles = None, True, 0
            elif ids != p["before"]:
                raise LeadRotationError("PC transfer changed an unexpected party member")
        if self.closing:
            if find_boxes(obs.screen_rows):
                return [A.PRESS_B], "close verified PC transaction"
            self.closing = False
        if not self.pending:
            remove = [m for m in obs.party if m.get("dead") or m["capture_id"] not in desired]
            add = [m for m in boxed(obs) if m["capture_id"] in desired and not m.get("dead") and not m.get("ineligible")]
            if not remove and not add:
                return [], ""
            deposit = bool(
                remove
                and len(obs.party) > 1
                and any(not m.get("dead") and not m.get("ineligible") for m in obs.party if m is not remove[0])
            )
            mon = remove[0] if deposit else add[0] if add and len(obs.party) < 6 else None
            if mon is None:
                raise LeadRotationError("No safe PC transfer order")
            box = storage["active_box"] if deposit else mon["box"]
            if deposit and len(storage["boxes"][box - 1]["members"]) >= 20:
                box = next((b["box"] for b in storage["boxes"] if len(b["members"]) < 20), None)
            if box is None:
                raise LeadRotationError("All PC boxes are full")
            self.pending = {
                "operation": "box" if box != storage["active_box"] else "deposit" if deposit else "withdraw",
                "box": box,
                "target": mon["capture_id"],
                "before": ids,
                "selected": False,
            }
            record("storage_requested", self.pending)
        actions = self.actions(obs)
        signature = [obs.screen_rows, ids, storage["active_box"]]
        if signature != self.progress and actions != [A.WAIT_60]:
            self.progress, self.cycles = signature, 0
        self.cycles += 1
        self.pending["steps"] = self.pending.get("steps", 0) + 1
        if self.cycles > 40 or self.pending["steps"] > 150:
            raise LeadRotationError("PC transaction exceeded its progress limit")
        if actions == [A.PRESS_A] and self._list_cursor(obs) is not None:
            self.pending["selected"] = True
        return actions, f"PC: {self.pending['operation']} {self.pending['target']}"

    def _list_cursor(self, obs):
        if not self.pending or self.pending["operation"] == "box":
            return None
        screen = parse_screen(obs.screen_rows)
        if any(key(r) in {"STATS", "DEPOSIT", "WITHDRAW", "RELEASE", "CHANGEBOX"} for r in screen.menu_rows):
            return None
        mons = (
            obs.party
            if self.pending["operation"] == "deposit"
            else [m for m in boxed(obs) if m["box"] == obs.storage["active_box"]]
        )
        selected = next((key(row.partition("▶")[2].split("│")[0]) for row in obs.screen_rows if "▶" in row), "")
        candidates = [i for i, m in enumerate(mons) if selected and selected == key(m.get("nickname") or m["species"])]
        if len(candidates) > 1:
            raise LeadRotationError("Ambiguous visible PC nickname")
        return candidates[0] if candidates else None

    def actions(self, obs):
        if obs.in_battle or not self.pending:
            return None
        p = self.pending
        screen = parse_screen(obs.screen_rows)
        rows = [key(r).removesuffix("PM") for r in screen.menu_rows]
        cursor = screen.cursor_row
        words = key(" ".join(obs.screen_rows))
        if p["operation"] == "box" and "BOX" in words and "WILLBESAVED" in words:
            p["save_prompt"] = True
        if "RELEASE" in rows and "CHANGEBOX" not in rows:
            raise LeadRotationError("Unexpected release screen")
        if rows == ["YES", "NO"]:
            return toward(cursor, 0) if p["operation"] == "box" and p.get("save_prompt") else [A.PRESS_B]
        if "ACCESSED" in key(" ".join(screen.text_lines)):
            return [A.PRESS_B]
        if cursor is not None:
            label = next((i for i, r in enumerate(rows) if r in {"SOMEONESPC", "SOMEONEPC", "BILLSPC", "BILLPC"}), None)
            if label is not None:
                return toward(cursor, label)
            if "CHANGEBOX" in rows:
                return toward(cursor, rows.index("CHANGEBOX" if p["operation"] == "box" else p["operation"].upper()))
            if "STATS" in rows:
                if not p["selected"] or p["operation"].upper() not in rows:
                    raise LeadRotationError("PC confirmation lacks a verified selection")
                return toward(cursor, rows.index(p["operation"].upper()))
        if p["operation"] == "box":
            match = next((re.search(r"▶\s*BOX\s*(\d+)", r) for r in obs.screen_rows if re.search(r"▶\s*BOX\s*(\d+)", r)), None)
            if match:
                return toward(int(match[1]), p["box"])
        else:
            current = self._list_cursor(obs)
            if current is not None:
                mons = (
                    obs.party if p["operation"] == "deposit" else [m for m in boxed(obs) if m["box"] == obs.storage["active_box"]]
                )
                target = next((i for i, m in enumerate(mons) if m["capture_id"] == p["target"]), None)
                if target is None:
                    raise LeadRotationError("PC target no longer exists")
                return toward(current, target)
        if screen.text_lines and cursor is None:
            return [A.PRESS_B]
        if find_boxes(obs.screen_rows):
            return [A.WAIT_60]
        return [A.PRESS_A] if (obs.x, obs.y, obs.facing) == (13, 4, "up") else None
