"""On-screen text from the tilemap rows ``/map/objects`` returns.

Gen 1 draws every text box and menu as font tiles inside a ┌─┐ │ └─┘ frame.
The bottom box (rows 12-17, full width) is speech; any other frame is a menu,
and the row with ▶ is the highlight. Outside a box the rows are map or logo
tiles that happen to decode as letters, so callers use this only when the
pixel check (``screen.text_box_open`` / ``prompt_box_open``) sees a box.
"""

from __future__ import annotations

from dataclasses import dataclass, field

_CURSORS = "▶▷"
_TEXT_TOP = 12


@dataclass(frozen=True)
class Box:
    top: int
    left: int
    bottom: int
    right: int
    title: str
    lines: tuple[str, ...]


@dataclass(frozen=True)
class ScreenText:
    # Speech in the bottom box, top line first.
    text_lines: list[str] = field(default_factory=list)
    # The rows of the menu that holds the cursor, without the cursor glyph.
    menu_rows: list[str] = field(default_factory=list)
    # Index into ``menu_rows`` of the highlighted row.
    cursor_row: int | None = None
    menu_title: str = ""

    def as_state(self) -> dict[str, object]:
        out: dict[str, object] = {}
        if self.text_lines:
            out["text"] = " ".join(self.text_lines)
        if self.menu_rows:
            out["menu"] = self.menu_rows
            if self.cursor_row is not None:
                out["highlighted"] = self.menu_rows[self.cursor_row]
        if self.menu_title:
            out["menu_title"] = self.menu_title
        return out


def find_boxes(rows: list[str]) -> list[Box]:
    boxes = []
    for top, row in enumerate(rows):
        for left, char in enumerate(row):
            if char != "┌":
                continue
            right = row.find("┐", left + 1)
            if right < 0:
                continue
            bottom = next((r for r in range(top + 1, len(rows)) if _at(rows, r, left) == "└"), None)
            if bottom is None:
                continue
            title = row[left + 1 : right].replace("─", " ").strip()
            lines = tuple(
                rows[r][left + 1 : right].replace("▼", " ").rstrip() for r in range(top + 1, bottom)
            )
            boxes.append(Box(top, left, bottom, right, title, lines))
    return boxes


def _at(rows: list[str], row: int, col: int) -> str:
    return rows[row][col] if 0 <= row < len(rows) and 0 <= col < len(rows[row]) else ""


def parse_screen(rows: list[str] | None) -> ScreenText:
    if not rows:
        return ScreenText()
    text_lines: list[str] = []
    menus: list[Box] = []
    for box in find_boxes(rows):
        if box.top >= _TEXT_TOP and box.left == 0 and box.bottom == len(rows) - 1:
            text_lines = [line.strip() for line in box.lines if line.strip()]
        else:
            menus.append(box)

    # ▶ starting a row is the active menu; ▷ marks the one behind it (BUY under the Mart's
    # item list). A box that only overlaps another box's cursor mid-line is not it.
    def leads(box: Box, glyph: str) -> bool:
        return any(line.strip().startswith(glyph) for line in box.lines)

    menu = next((b for b in menus if leads(b, "▶")), None)
    if menu is None:
        return ScreenText(text_lines=text_lines)
    menu_rows: list[str] = []
    cursor = None
    for line in menu.lines:
        label = line.strip()
        if not label:
            continue
        if (label[0] in "¥×" or label.isdecimal()) and menu_rows:
            # Prices/counts and PC Pokémon levels are continuation lines, not choices.
            menu_rows[-1] = f"{menu_rows[-1]} {label}"
            continue
        if label[0] in _CURSORS:
            cursor = len(menu_rows)
            label = label[1:].strip()
        menu_rows.append(label)
    return ScreenText(
        text_lines=text_lines, menu_rows=menu_rows, cursor_row=cursor, menu_title=menu.title
    )
