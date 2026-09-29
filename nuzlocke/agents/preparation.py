"""Deterministic starter, shop, healing, and audited candy preparation menus."""

from __future__ import annotations

from nuzlocke.agents.system1 import _special_page, menu_actions
from nuzlocke.agents.system3 import current_beat
from nuzlocke.environment.screen_text import parse_screen
from nuzlocke.state.models import GameAction as A


def preparation_turn(loop, obs):
    screen = parse_screen(obs.screen_rows)
    text = " ".join(obs.screen_rows).upper()
    rows = [r.upper() for r in screen.menu_rows]
    cursor = screen.cursor_row
    if rows == ["YES", "NO"] and "NICKNAME" in text:
        return menu_actions("choose_1", cursor), "nickname: NO"
    if obs.in_battle:
        if "HT" in text and "WT" in text:
            return [A.PRESS_A, A.WAIT_60], "caught Pokémon's Pokédex page"
        return [], ""
    if not obs.party and "WT" in text and "HT" in text:
        loop._starter_seen = next(
            (s for s in ("BULBASAUR", "CHARMANDER", "SQUIRTLE") if s in text), None
        )
        return (
            [A.PRESS_A, A.WAIT_60] if loop._starter_seen else [A.WAIT_60]
        ), "read starter species"
    if not obs.party and rows == ["YES", "NO"] and loop._starter_seen:
        yes = loop._starter_seen == "BULBASAUR"
        if not yes:
            # Remember the rejected ball and select another on the next overworld cycle.
            loop._rejected_starters = getattr(loop, "_rejected_starters", set()) | {(obs.x, obs.y)}
        return menu_actions(
            "choose_0" if yes else "choose_1", cursor
        ), "confirm Bulbasaur" if yes else "decline other starter"
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
    if beat and beat.id.startswith("heal") and "HEAL" in rows and cursor is not None:
        return menu_actions(f"choose_{rows.index('HEAL')}", cursor), "accept healing"
    if rows == ["YES", "NO"] and beat and beat.id.startswith("heal"):
        return menu_actions("choose_0", cursor), "accept healing"
    balls = any("ball" in str(i.get("item", "")).lower() for i in obs.bag)
    if obs.map_id == 42 and "▷" in text and "▶" not in text and screen.text_lines:
        return [A.PRESS_B, A.WAIT_60], "page the shop's question before its menu activates"
    if obs.map_id == 42 and obs.flags.get("has_pokedex") and rows and cursor is not None:
        if balls:
            choice = next((i for i, r in enumerate(rows) if r == "QUIT"), None)
            return (
                menu_actions(f"choose_{choice}", cursor) if choice is not None else [A.PRESS_B]
            ), "leave shop"
        wanted = next(
            (i for i, r in enumerate(rows) if r == "BUY" or "BALL" in r or r == "YES"), None
        )
        if wanted is not None:
            return menu_actions(f"choose_{wanted}", cursor), "buy balls"
    dead = [m for m in obs.party if m.get("dead")]
    if dead and obs.map_id in {41, 58}:
        if rows and cursor is not None:
            for label in ("SOMEONE", "BILL", "DEPOSIT"):
                index = next((i for i, row in enumerate(rows) if label in row), None)
                if index is not None:
                    if rows[index] == "DEPOSIT":
                        loop._closing_preparation = True
                    return menu_actions(f"choose_{index}", cursor), "open storage for dead Pokémon"
            for mon in dead:
                index = next(
                    (
                        i
                        for i, row in enumerate(rows)
                        if str(mon.get("nickname") or mon.get("species")).upper() in row
                    ),
                    None,
                )
                if index is not None:
                    return menu_actions(
                        f"choose_{index}", cursor
                    ), "deposit permanently dead Pokémon"
            return [A.PRESS_B], "close unrelated menu before using storage"
        if "DEPOSIT" in text and "POK" in text and obs.menu_index is not None:
            slot = next(i for i, m in enumerate(obs.party) if m.get("dead"))
            return menu_actions(f"choose_{slot}", obs.menu_index), "select dead Pokémon for deposit"
        return [], ""
    if obs.map_id not in {40, 41, 58} or any(m.get("dead") for m in obs.party):
        return [], ""
    if obs.map_id == 40 and (len(obs.party) != 1 or obs.party[0].get("species") != "Bulbasaur"):
        return [], ""
    settings = loop.run_cfg.get("rare_candy") or {}
    target = min(
        loop.referee.current_cap,
        int(
            settings.get(
                {40: "rival_level", 41: "first_center_level", 58: "brock_level"}[obs.map_id],
                {40: 8, 41: 12, 58: 14}[obs.map_id],
            )
        ),
    )
    candidates = [(i, m) for i, m in enumerate(obs.party) if (m.get("level") or target) < target]
    if not candidates:
        if loop._preparing_target:
            loop._preparing_target = None
            loop._closing_preparation = True
            return [A.PRESS_B], "preparation complete; close menu"
        return [], ""
    healthy = all(
        m.get("hp") == m.get("max_hp") and m.get("status", "OK") == "OK" for m in obs.party
    )
    if not loop._preparing_target:
        if not healthy or screen.text_lines or rows:
            return [], ""
        if not (loop.run_cfg.get("rare_candy") or {}).get("enabled"):
            return [], ""
        result = loop.env._post_json("/nuzlocke/prepare", {"target": target})
        loop.store.append("candy_grant", result)
        loop._preparing_target = target
        obs.policy["preparing"] = True
        return [A.PRESS_START, A.WAIT_60], "open bag for preparation"
    if cursor is not None and rows:
        for name in ("RARE CANDY", "PACK", "ITEM"):
            index = next((i for i, r in enumerate(rows) if name in r), None)
            if index is not None:
                return menu_actions(f"choose_{index}", cursor), "use audited rare candy"
        if "USE" in rows:
            return menu_actions(f"choose_{rows.index('USE')}", cursor), "use candy"
        for slot, mon in candidates:
            index = next(
                (
                    i
                    for i, r in enumerate(rows)
                    if str(mon.get("nickname") or mon.get("species")).upper() in r
                ),
                None,
            )
            if index is not None:
                return menu_actions(
                    f"choose_{index}", cursor
                ), f"prepare party slot {slot} to {target}"
    if ("HP" in text or "USE ITEM ON WHICH" in text) and any(
        str(m.get("nickname") or m.get("species")).upper() in text for m in obs.party
    ):
        slot = candidates[0][0]
        cursor = obs.menu_index or 0
        return menu_actions(f"choose_{slot}", cursor), f"candy for party slot {slot}"
    if "TRYING TO LEARN" in text or "DELETE" in text or "FORGET" in text:
        return [], ""  # The verified move-learning handler owns these decisions.
    if screen.text_lines:
        return [A.PRESS_A, A.WAIT_60], "finish candy result"
    if not rows:
        return [A.PRESS_START, A.WAIT_60], "open preparation menu"
    return [], ""
