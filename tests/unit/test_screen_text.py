"""Tilemap rows read on Red Star, parsed into speech, menu rows, and the cursor."""

from __future__ import annotations

from nuzlocke.environment.screen_text import parse_screen

BLANK = " " * 20
NAME_LIST = [
    "┌──NAME───┐         ",
    "│         │         ",
    "│▶NEW NAME│         ",
    "│         │         ",
    "│ RED     │         ",
    "│         │         ",
    "│ ASH     │         ",
    "│         │         ",
    "│ JACK    │         ",
    "│         │         ",
    "│         │         ",
    "└─────────┘         ",
    "┌──────────────────┐",
    "│                  │",
    "│First, what is    │",
    "│                  │",
    "│your name?        │",
    "└──────────────────┘",
]


def test_name_list_and_question():
    screen = parse_screen(NAME_LIST)
    assert screen.text_lines == ["First, what is", "your name?"]
    assert screen.menu_rows == ["NEW NAME", "RED", "ASH", "JACK"]
    assert screen.cursor_row == 0
    assert screen.menu_title == "NAME"
    assert screen.as_state()["highlighted"] == "NEW NAME"


def test_speech_only_drops_the_page_arrow():
    rows = [BLANK] * 12 + [
        "┌──────────────────┐",
        "│                  │",
        "│Hello there!      │",
        "│                  │",
        "│Welcome to the    │",
        "└─────────────────▼┘",
    ]
    screen = parse_screen(rows)
    assert screen.text_lines == ["Hello there!", "Welcome to the"]
    assert screen.menu_rows == []


def test_title_logo_tiles_are_not_a_box():
    rows = ["  ABCDEFGHIJKLMNOP  ", "  QRSTUVWXYZ        "] + [BLANK] * 16
    assert parse_screen(rows).as_state() == {}
    assert parse_screen(None).as_state() == {}


MART = [
    "┌─────────┐┌─MONEY─┐",
    "│▷BUY     ││   ¥793│",
    "│   ┌──────────────┐",
    "│ SE│              │",
    "│   │▶POKé BALL    │",
    "│ QU│         ¥200 │",
    "└───│ ANTIDOTE     │",
    "    │         ¥100 │",
    "    │ PARLYZ HEAL  │",
    "    │         ¥200 │",
    "    │ BURN HEAL    │",
    "    │         ¥250▼│",
    "┌───└──────────────┘",
    "│                  │",
    "│Take your time.   │",
    "│                  │",
    "│                  │",
    "└──────────────────┘",
]


def test_the_mart_list_is_the_active_menu_with_prices_on_their_rows():
    # As read in Viridian Mart on Red Star.
    screen = parse_screen(MART)
    assert screen.menu_rows[:2] == ["POKé BALL ¥200", "ANTIDOTE ¥100"]
    assert screen.cursor_row == 0


def test_hollow_shop_cursor_is_inactive_while_text_prints():
    rows = [r.replace("▶", "▷") for r in MART]
    assert parse_screen(rows).menu_rows == []


def test_pc_levels_do_not_count_as_selectable_rows():
    rows = [
        "┌──────────────┐",
        "│ BULBASAUR    │",
        "│ 12           │",
        "│▶RATTATA      │",
        "│ 12           │",
        "│ PIDGEY       │",
        "│ 12           │",
        "│ CANCEL       │",
        "└──────────────┘",
    ]
    screen = parse_screen(rows)
    assert screen.menu_rows == ["BULBASAUR 12", "RATTATA 12", "PIDGEY 12", "CANCEL"]
    assert screen.cursor_row == 1
