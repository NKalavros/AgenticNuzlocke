import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from nuzlocke.agents.inventory import candy_bag_actions
from nuzlocke.agents.policy import decision
from nuzlocke.agents.preparation import preparation_turn
from nuzlocke.state.models import GameAction as A
from nuzlocke.state.models import PlayerObservation as O

FIXTURE = json.loads((Path(__file__).parents[1] / "fixtures/candy_bag_scrolled.json").read_text())


def obs():
    return O(
        **FIXTURE,
        map_id=65,
        x=4,
        y=3,
        badges=["Boulder"],
        battle_style="SET",
        policy={"preparing": True},
        party=[{"species": "Beedrill", "level": 19, "hp": 57, "max_hp": 57, "status": "OK"}],
    )


def runner():
    return SimpleNamespace(
        _preparing_target=21,
        _closing_preparation=False,
        run_cfg={},
        referee=SimpleNamespace(current_cap=21),
    )


def test_real_fifth_item_scroll_is_owned_by_actor_and_arbiter():
    o = obs()
    assert all("RARE CANDY" not in row for row in o.screen_rows)
    assert preparation_turn(runner(), o)[0] == [A.WALK_DOWN]
    assert decision(o).validate([A.WALK_DOWN]) is None
    assert decision(o).validate([A.PRESS_B]) == "required:candy_bag"
    assert decision(o).validate([A.PRESS_A]) == "required:candy_bag"


def test_candy_selected_after_scroll_and_cancel_scrolls_back_up():
    o = obs()
    # Same live menu frame, now scrolled down one row to reveal the candy.
    o.screen_rows[4] = "    │ TM34         │"
    o.screen_rows[6] = "    │ HELIX FOSSIL │"
    o.screen_rows[8] = "    │ NUGGET       │"
    o.screen_rows[10] = "    │▶RARE CANDY   │"
    o.screen_rows[11] = "    │         × 6  │"
    assert candy_bag_actions(o) == [A.PRESS_A]
    o.screen_rows[10] = "    │▶CANCEL       │"
    o.screen_rows[11] = "    │              │"
    assert candy_bag_actions(o) == [A.WALK_UP]


def test_no_unapproved_candy_use_or_mart_scroll():
    o = obs()
    o.policy["preparing"] = False
    assert candy_bag_actions(o) is None
    o.policy["preparing"] = True
    o.in_battle = True
    assert candy_bag_actions(o) is None
    o.in_battle = False
    o.screen_rows = [row.replace("×10", "¥200") for row in o.screen_rows]
    assert candy_bag_actions(o) is None


def test_missing_candy_and_stalled_preparation_pause():
    o, loop = obs(), runner()
    loop._preparation_wait_cycles = 60
    with pytest.raises(RuntimeError, match="no level progress"):
        preparation_turn(loop, o)
    loop._preparation_wait_cycles = 0
    o.bag = o.bag[:-1]
    with pytest.raises(RuntimeError, match="missing from the bag"):
        preparation_turn(loop, o)
    assert decision(o).validate([A.WAIT_60]) is None
