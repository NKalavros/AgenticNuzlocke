"""Final candy top-up at the leader, after ordinary gym trainers."""


def leader_position(map_id, badges):
    if map_id == 54 and "Boulder" not in badges:
        return (4, 2)
    if map_id == 65 and "Boulder" in badges and "Cascade" not in badges:
        return (4, 3)
    return None


def needs_top_up(obs):
    cap = obs.policy.get("level_cap")
    return bool(
        cap
        and leader_position(obs.map_id, obs.badges)
        and any(not m.get("dead") and 0 < m.get("level", 0) < cap for m in obs.party)
    )


def at_leader(obs):
    return not obs.in_battle and (obs.x, obs.y) == leader_position(obs.map_id, obs.badges)
