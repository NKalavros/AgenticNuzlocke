"""Deterministic starter, shop, healing, and audited candy preparation menus."""

from __future__ import annotations

from nuzlocke.agents.system1 import _special_page, menu_actions
from nuzlocke.agents.system3 import HEALING_CENTERS, current_beat
from nuzlocke.environment.screen_text import is_pokedex_page, parse_screen
from nuzlocke.state.models import GameAction as A


def preparation_turn(loop, obs):
    screen = parse_screen(obs.screen_rows)
    text = " ".join(obs.screen_rows).upper()
    rows = [r.upper() for r in screen.menu_rows]
    cursor = screen.cursor_row
    if rows == ["YES", "NO"] and "NICKNAME" in text:
        return menu_actions("choose_1", cursor), "nickname: NO"
    if obs.in_battle:
        if is_pokedex_page(obs.screen_rows):
            return [A.PRESS_A, A.WAIT_60], "caught Pokémon's Pokédex page"
        return [], ""
    from nuzlocke.knowledge.objects import fossil_question, has_fossil

    if fossil_question(obs.map_id, obs.screen_rows) and not has_fossil(obs):
        if rows == ["YES", "NO"] and cursor is not None:
            return menu_actions("choose_0", cursor), "accept one Mt. Moon fossil"
        return [A.WAIT_60], "wait for the fossil YES/NO; B would decline it"
    if obs.map_id == 61 and has_fossil(obs) and "GOT THE" in text and "FOSSIL" in text:
        return [A.PRESS_A, A.WAIT_60], "acknowledge fossil receipt"
    if not obs.party and is_pokedex_page(obs.screen_rows):
        loop._starter_seen = next((s for s in ("BULBASAUR", "CHARMANDER", "SQUIRTLE") if s in text), None)
        return ([A.PRESS_A, A.WAIT_60] if loop._starter_seen else [A.WAIT_60]), "read starter species"
    if not obs.party and rows == ["YES", "NO"] and loop._starter_seen:
        yes = loop._starter_seen == "BULBASAUR"
        if not yes:
            # Remember the rejected ball and select another on the next overworld cycle.
            loop._rejected_starters = getattr(loop, "_rejected_starters", set()) | {(obs.x, obs.y)}
        return menu_actions("choose_0" if yes else "choose_1", cursor), "confirm Bulbasaur" if yes else "decline other starter"
    if not obs.party:
        return [], ""
    if obs.battle_style == "SHIFT":
        result = loop.env._post_json("/nuzlocke/prepare", {"set_style": True})
        loop.store.append("configuration", result)
        return [A.WAIT_60], "set battle style"
    special = _special_page(obs.screen_rows)
    if special:
        return special.actions, special.reason
    if getattr(loop, "_closing_preparation", False):
        from nuzlocke.environment.screen_text import find_boxes

        if find_boxes(obs.screen_rows):
            return [A.PRESS_B], "close preparation menus"
        loop._closing_preparation = False
    # Fixed menus with no strategic choice should never consume an LLM call.
    beat = current_beat(obs)
    nurse_prompt = obs.map_id in HEALING_CENTERS and (obs.x, obs.y) == (3, 3)
    if beat and beat.id in {"heal_nurse", "heal_team"} and nurse_prompt and cursor is not None:
        choice = rows.index("HEAL") if "HEAL" in rows else 0 if rows == ["YES", "NO"] else None
        if choice is not None:
            preparation = getattr(loop, "gym_preparation", None)
            if preparation and preparation.pending and preparation.pending["phase"] == "heal":
                preparation.pending["accepted"] = True
            return menu_actions(f"choose_{choice}", cursor), "accept healing"
    dead = [m for m in obs.party if m.get("dead")]
    storage = getattr(loop, "storage", None)
    if (
        (dead or storage and (storage.pending or storage.closing))
        and obs.map_id in HEALING_CENTERS
        and not obs.policy.get("system4")
    ):
        if storage is not None and (obs.x, obs.y) == (13, 4):
            return storage.turn(obs, [m["capture_id"] for m in obs.party if not m.get("dead")], loop.store.append)
        return [], ""
    from nuzlocke.agents.gym_preparation import at_leader

    stage = obs.policy.get("gym_preparation")
    team = obs.policy.get("system4")
    team_levels = team and team["phase"] == "levels" and obs.map_id in HEALING_CENTERS
    if team and not team_levels:
        return [], ""
    if stage and stage["phase"] == "heal":
        return [], ""
    gym_top_up = at_leader(obs) and not stage
    gym_center = stage and stage["phase"] == "prepare" and obs.map_id == stage["center"]
    if (obs.map_id not in {40, 41, 58, 64, 68} and not gym_top_up and not gym_center and not team_levels) or any(
        m.get("dead") for m in obs.party
    ):
        return [], ""
    if obs.map_id == 40 and (len(obs.party) != 1 or obs.party[0].get("species") != "Bulbasaur"):
        return [], ""
    settings = loop.run_cfg.get("rare_candy") or {}
    setting = (
        ("misty_level" if obs.map_id == 64 else "post_brock_level")
        if "Boulder" in obs.badges
        else {40: "rival_level", 41: "first_center_level", 58: "brock_level"}.get(obs.map_id, "brock_level")
    )
    default = (21 if obs.map_id == 64 else 18) if "Boulder" in obs.badges else {40: 8, 41: 12, 58: 14}.get(obs.map_id, 14)
    from nuzlocke.agents.level_buffer import preparation_limit

    target = min(
        preparation_limit(loop.referee.current_cap, int(loop.run_cfg.get("level_cap_buffer", 1))),
        int(settings.get(setting, default)),
    )
    if gym_top_up:
        target = loop.referee.current_cap
    if gym_center:
        target = min(stage["cap"], loop.referee.current_cap)
    targets = (obs.policy.get("team_plan") or {}).get("levels", {}) if team_levels else {}
    if targets:
        target = max(targets.values())
    if loop._preparing_target:
        target = loop._preparing_target
    candidates = [
        (i, m)
        for i, m in enumerate(obs.party)
        if (m.get("level") or target) < targets.get(m.get("capture_id"), m["level"] if targets else target)
    ]
    if not candidates:
        if loop._preparing_target:
            loop._preparing_target = None
            loop._closing_preparation = True
            return [A.PRESS_B], "preparation complete; close menu"
        return [], ""
    healthy = all(m.get("hp") == m.get("max_hp") and m.get("status", "OK") == "OK" for m in obs.party)
    request = {"target": target}
    if targets:
        request["targets"] = [targets.get(m.get("capture_id"), m["level"]) for m in obs.party]
    if not loop._preparing_target:
        if not healthy or screen.text_lines or rows:
            return [], ""
        if not (loop.run_cfg.get("rare_candy") or {}).get("enabled"):
            if gym_top_up:
                raise RuntimeError("Gym leader requires party at the cap; enable Rare Candy preparation")
            return [], ""
        result = loop.env._post_json("/nuzlocke/prepare", request)
        loop.store.append("candy_grant", result)
        loop._preparing_target = target
        loop._preparation_wait_cycles = 0
        obs.policy["preparing"] = True
        return [A.PRESS_START, A.WAIT_60], "open bag for preparation"
    loop._preparation_wait_cycles = getattr(loop, "_preparation_wait_cycles", 0) + 1
    if loop._preparation_wait_cycles > 60:
        raise RuntimeError("Candy preparation made no level progress for 60 cycles; paused for inspection")
    from nuzlocke.agents.inventory import candy_bag_actions

    bag_actions = candy_bag_actions(obs)
    if bag_actions is not None:
        if bag_actions == [A.WAIT_60]:
            if team_levels and healthy:
                loop.store.append("candy_grant", loop.env._post_json("/nuzlocke/prepare", request))
                return [A.WAIT_60], "refill the remaining audited candy deficit"
            raise RuntimeError("Audited Rare Candies are missing from the bag before preparation finished")
        return bag_actions, "scroll bag to audited Rare Candy" if bag_actions != [A.PRESS_A] else "select audited Rare Candy"
    if cursor is not None and rows:
        for name in ("RARE CANDY", "PACK", "ITEM"):
            index = next((i for i, r in enumerate(rows) if name in r), None)
            if index is not None:
                return menu_actions(f"choose_{index}", cursor), "use audited rare candy"
        if "USE" in rows:
            return menu_actions(f"choose_{rows.index('USE')}", cursor), "use candy"
        for slot, mon in candidates:
            index = next((i for i, r in enumerate(rows) if str(mon.get("nickname") or mon.get("species")).upper() in r), None)
            if index is not None:
                return menu_actions(f"choose_{index}", cursor), f"prepare party slot {slot} to {target}"
    if ("HP" in text or "USE ITEM ON WHICH" in text) and any(
        str(m.get("nickname") or m.get("species")).upper() in text for m in obs.party
    ):
        slot = candidates[0][0]
        cursor = obs.menu_index or 0
        return menu_actions(f"choose_{slot}", cursor), f"candy for party slot {slot}"
    if screen.text_lines:
        return [A.PRESS_A, A.WAIT_60], "finish candy result"
    if not rows:
        return [A.PRESS_START, A.WAIT_60], "open preparation menu"
    return [], ""
