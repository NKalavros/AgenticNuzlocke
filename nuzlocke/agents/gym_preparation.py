"""Persistent heal → candy → challenge stages once the leader is the next task."""

from copy import deepcopy

from nuzlocke.environment.screen_text import find_boxes

# gym, city, Center, earned badge, leader name, interaction position.
GYMS = (
    (54, 2, 58, "Boulder", "Brock", (4, 2)),
    (65, 3, 64, "Cascade", "Misty", (4, 3)),
    (92, 5, 89, "Thunder", "Lt. Surge", (5, 2)),
    (134, 6, 133, "Rainbow", "Erika", (4, 4)),
    (157, 7, 154, "Soul", "Koga", (4, 11)),
)


def leader_position(map_id, badges):
    return next(
        (row[5] for index, row in enumerate(GYMS) if row[0] == map_id and len(badges) == index and row[3] not in badges), None
    )


def party_ready(obs):
    living = [m for m in obs.party if not m.get("dead")]
    return bool(living) and all(
        m.get("hp", 0) > 0
        and m.get("hp") == m.get("max_hp")
        and m.get("status", "OK") == "OK"
        and all(move.get("pp", 0) >= move.get("observed_max_pp", 0) for move in m.get("moves", []))
        for m in living
    )


class GymPreparation:
    def __init__(self):
        self.pending = None

    def snapshot(self):
        return deepcopy(self.pending)

    def restore(self, state):
        self.pending = deepcopy(state)

    def observe(self, obs, *, cap, candy_enabled, record):
        state = self.pending
        if state and state["badge"] in obs.badges:
            record("gym_preparation_complete", state)
            self.pending = state = None
        if not state and not obs.in_battle and not obs.cutscene and not find_boxes(obs.screen_rows):
            row = next((r for i, r in enumerate(GYMS) if len(obs.badges) == i and r[3] not in obs.badges), None)
            if row:
                gym, city, center, badge, name, position = row
                ready = obs.map_id == gym and (obs.x, obs.y) == position
                ready |= gym == 92 and obs.map_id in {gym, city, center} and (obs.surge_puzzle or {}).get("phase") == "open"
                ready |= gym == 157 and obs.map_id in {gym, city, center}  # No gym-access quest remains in Fuchsia.
                if ready:
                    self.pending = state = {
                        "gym": gym,
                        "city": city,
                        "center": center,
                        "badge": badge,
                        "name": name,
                        "position": list(position),
                        "cap": cap,
                        "phase": "heal",
                        "accepted": False,
                    }
                    record("gym_preparation_started", state)
        if state and not obs.in_battle:
            team = obs.policy.get("system4")
            if team and team["phase"] != "ready" and state["phase"] != "heal":
                self.annotate(obs)
                return
            before = state["phase"]
            clear = not find_boxes(obs.screen_rows)
            if before == "heal" and state["accepted"] and party_ready(obs) and clear:
                state["phase"] = "prepare" if candy_enabled else "challenge"
            elif (
                before == "prepare"
                and clear
                and not any(
                    not m.get("dead")
                    and m.get("level", 0)
                    < (obs.policy.get("team_plan") or {}).get("levels", {}).get(m.get("capture_id"), state["cap"])
                    for m in obs.party
                )
            ):
                state["phase"] = "challenge" if party_ready(obs) else "heal"
                state["accepted"] = False
            elif before == "challenge" and not party_ready(obs):
                state["phase"], state["accepted"] = "heal", False
            if before != state["phase"]:
                record("gym_preparation_stage", state)
        self.annotate(obs)

    def annotate(self, obs):
        obs.policy["gym_preparation"] = deepcopy(self.pending)
        obs.policy["gym_heal_pending"] = bool(self.pending and self.pending["phase"] == "heal")


def gym_beat(obs):
    """Route state becomes a code-owned objective; normal healing still outranks it."""
    from nuzlocke.knowledge.beats import Beat

    state = obs.policy.get("gym_preparation")
    if not state or obs.in_battle or state["phase"] == "heal":
        return None
    phase, name, gym, city, center = (state[k] for k in ("phase", "name", "gym", "city", "center"))
    if phase == "prepare" and obs.map_id == center:
        return Beat(
            id="prepare_gym",
            text=f"Prepare the living party for {name}: use audited Rare Candies to level {state['cap']}.",
            hint="Heal before candy grants. Use normal menus; verify every living party member's level. Then return to the leader.",
        )
    if phase == "challenge" and obs.map_id == gym:
        x, y = state["position"]
        return Beat(
            id="gym_challenge",
            text=f"Challenge {name}; the party has healed and completed preparation.",
            hint="Reach the leader and interact. Do not repeat completed healing or switch searches; verify the badge after victory.",
            target={"kind": "face", "x": x, "y": y, "dir": "up"},
        )
    destination = city if obs.map_id in {gym, center} else gym if phase == "challenge" else center
    return Beat(
        id="gym_route",
        text=f"{'Return to challenge' if phase == 'challenge' else 'Return to prepare for'} {name}.",
        hint="The party has healed. Clear necessary field obstacles if blocked, then resume this destination; keep the objective.",
        target={"kind": "warp", "dest_map": destination},
    )


def needs_top_up(obs):
    cap = obs.policy.get("level_cap")
    targets = (obs.policy.get("team_plan") or {}).get("levels", {})
    return bool(
        cap
        and (leader_position(obs.map_id, obs.badges) or obs.policy.get("gym_preparation"))
        and any(not m.get("dead") and 0 < m.get("level", 0) < targets.get(m.get("capture_id"), cap) for m in obs.party)
    )


def at_leader(obs):
    return not obs.in_battle and (obs.x, obs.y) == leader_position(obs.map_id, obs.badges)
