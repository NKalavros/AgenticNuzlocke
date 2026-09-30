"""Reserve experience headroom without changing the hard battle-entry level cap."""

from nuzlocke.referee.type_chart import effectiveness, types_for_species


def threshold(obs):
    cap = obs.policy.get("level_cap")
    return max(1, cap - obs.policy.get("level_cap_buffer", 1)) if cap is not None else None


def reserved(obs, mon):
    limit = threshold(obs)
    return limit is not None and (mon.get("level") or 0) >= limit


def eligible(mon):
    return mon.get("hp", 0) > 0 and not mon.get("dead") and not mon.get("ineligible")


def alternatives(obs, *, active_slot=0):
    """Healthy, combat-capable alternatives; status, matchup and level constrain switching.

    This is a conservative heuristic, not a damage or guaranteed-survival calculation.
    """
    from nuzlocke.agents.move_learning import move_data

    enemy = (obs.battle or {}).get("enemy") or {}
    enemy_types = types_for_species(enemy.get("species", ""))
    candidates = []
    for slot, mon in enumerate(obs.party):
        if slot == active_slot or not eligible(mon) or reserved(obs, mon):
            continue
        hp = mon.get("hp", 0) / (mon.get("max_hp") or 1)
        if hp < 0.6 or mon.get("status", "OK") != "OK":
            continue
        floor = max(1, (enemy.get("level") or (threshold(obs) or 7) - 3) - 3)
        if (mon.get("level") or 0) < floor:
            continue
        own_types = types_for_species(mon.get("species", ""))
        if obs.in_battle and any(effectiveness(t, list(own_types)) > 1 for t in enemy_types):
            continue
        attacks = [
            move_data().get(m.get("id"), {}) for m in mon.get("moves", []) if m.get("pp", 0) > 0
        ]
        attacks = [
            m
            for m in attacks
            if m.get("power", 0) > 1
            and effectiveness(m.get("type", "Normal"), list(enemy_types)) > 0
        ]
        if not attacks:
            continue
        strength = max(
            m["power"] * effectiveness(m.get("type", "Normal"), list(enemy_types)) for m in attacks
        )
        candidates.append((slot, mon, (strength, hp, mon.get("level", 0))))
    return [(slot, mon) for slot, mon, _ in sorted(candidates, key=lambda p: p[2], reverse=True)]


def switch_target(obs):
    from nuzlocke.agents.battle import active_mon

    slot = (obs.active_party_slot or 0) if obs.in_battle else 0
    mon = active_mon(obs) if obs.in_battle else (obs.party or [{}])[0]
    if not reserved(obs, mon) and eligible(mon):
        return None
    choices = alternatives(obs, active_slot=slot)
    if choices:
        return choices[0][0]
    if not obs.in_battle and not eligible(mon):
        # Hard eligibility wins when the whole usable team is in the reserve band.
        legal = [(i, m) for i, m in enumerate(obs.party) if i != slot and eligible(m)]
        if legal:
            return max(legal, key=lambda p: p[1].get("hp", 0) / (p[1].get("max_hp") or 1))[0]
    return None


def preparation_limit(cap, buffer=1):
    return max(1, cap - max(0, buffer) - 1)


def switch_order(obs, desired=""):
    slot = (obs.active_party_slot or 0) if obs.in_battle else 0
    choices = [(i, m) for i, m in enumerate(obs.party) if i != slot and eligible(m)]
    safe = {i for i, _ in alternatives(obs, active_slot=slot)}
    target = switch_target(obs)
    return sorted(
        choices,
        key=lambda pair: (
            pair[0] != target if target is not None else False,
            pair[0] not in safe if safe else False,
            not any(
                str(pair[1].get(k, "")).upper() == desired.upper()
                for k in ("species", "nickname", "capture_id")
            ),
            -(pair[1].get("hp", 0) / (pair[1].get("max_hp") or 1)),
        ),
    )
