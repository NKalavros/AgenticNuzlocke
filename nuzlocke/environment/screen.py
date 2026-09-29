"""Screen-region digests and pixel checks for the 160x144 Game Boy frame.

Gen 1 draws its text box in the bottom 6 tile rows (y >= 96). Opening, closing, or scrolling
text does not touch the world digest (rows 0..95), so that is the progress signal; the dialog
digest (rows 96..143) says whether text is still advancing. A frame that cannot be split
hashes whole into both.

Pillow only: NumPy is not in a base ``uv sync``, and a NumPy split would silently fall back to
whole-file hashing and disable the stuck detection built on it.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
from pathlib import Path

FRAME_W = 160
FRAME_H = 144
DIALOG_TOP = 96
# The blinking "more text" arrow is not new text, so the dialog digest skips it. Vanilla draws
# it in tile (18, 16); Red Star's Oak intro draws it lower, on rows 137-141.
_MORE_ARROW = (144, 128, 152, 144)
# A menu box (YES/NO, a name list) is bordered by a dark-light-dark double line this tall.
_PROMPT_BORDER_ROWS = 24


def _md5(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


def _read(path: str | None) -> bytes:
    if not path:
        return b""
    try:
        return Path(path).read_bytes()
    except OSError:
        return b""


def _load_grey(source: str | io.BytesIO | None):
    """The frame as a greyscale Pillow image, or None when it cannot be read."""
    if not source:
        return None
    with contextlib.suppress(Exception):
        from PIL import Image

        with Image.open(source) as img:
            return img.convert("L")
    return None


def digests_from_bytes(data: bytes) -> tuple[str, str]:
    """Return ``(world_digest, dialog_digest)`` for a raw PNG frame."""
    if not data:
        return "0", "0"
    grey = _load_grey(io.BytesIO(data))
    if grey is None or grey.height <= DIALOG_TOP:
        return _md5(data), _md5(data)
    world = grey.crop((0, 0, grey.width, DIALOG_TOP)).tobytes()
    if grey.size == (FRAME_W, FRAME_H):
        grey.paste(255, _MORE_ARROW)
    return _md5(world), _md5(grey.crop((0, DIALOG_TOP, *grey.size)).tobytes())


def text_box_open(path: str | None) -> bool:
    """True when Gen 1's narrative window is on screen.

    That window is a white panel in a double black frame along the bottom: a dark line, a light
    gap, a dark line, rows of paper, then a dark line that closes it. A fade to black fills the
    same rows with no paper between the lines; a dark roof or sign does not span both margins.
    """
    grey = _load_grey(path)
    return grey is not None and _has_text_box(grey)


def prompt_box_open(path: str | None) -> bool:
    """True when a menu box sits above an open text box: a YES/NO or a list.

    One B there answers NO. Gen 1 draws every menu box with a double vertical border; a black
    map edge or a bookshelf is solid or single-lined, so it does not match.
    """
    grey = _load_grey(path)
    if grey is None or not _has_text_box(grey):
        return False
    pixels = grey.load()
    for x in range(grey.width - 2):
        run = 0
        for y in range(DIALOG_TOP):
            double = pixels[x, y] < 48 and pixels[x + 1, y] >= 48 and pixels[x + 2, y] < 48
            run = run + 1 if double else 0
            if run >= _PROMPT_BORDER_ROWS:
                return True
    return False


def _has_text_box(grey) -> bool:
    width, height = grey.size
    if height <= DIALOG_TOP or width < 32:
        return False
    pixels = grey.load()
    for top in range(DIALOG_TOP - 16, height - 32):
        if not _frame_line(pixels, top, width):
            continue
        inner = _inner_frame_line(pixels, top, width)
        if inner is None:
            continue
        while inner + 1 < height and _frame_line(pixels, inner + 1, width):
            inner += 1
        paper = 0
        for y in range(inner + 1, height):
            if _frame_line(pixels, y, width) and paper >= 16:
                return True
            if _paper_row(pixels, y, width):
                paper += 1
            elif paper == 0:
                break
    return False


def _frame_line(pixels, y: int, width: int) -> bool:
    """One stroke of the text-box frame: dark, and reaching both margins."""
    length, start = _longest_dark_run(pixels, y, width)
    end = start + length - 1
    return length >= max(96, (width * 3) // 4) and start <= 16 and end >= width - 17


def _paper_row(pixels, y: int, width: int) -> bool:
    """A row of the white panel. Glyphs darken it; they do not fill it."""
    light = sum(pixels[x, y] > 200 for x in range(8, width - 8))
    return light * 2 >= width - 16


def _inner_frame_line(pixels, top: int, width: int) -> int | None:
    """The inner stroke of a double frame, one light gap below ``top``."""
    for y in range(top + 1, top + 4):
        if _frame_line(pixels, y, width):
            gap = any(_paper_row(pixels, row, width) for row in range(top + 1, y))
            return y if gap else None
    return None


def _longest_dark_run(pixels, y: int, width: int) -> tuple[int, int]:
    """``(length, start)`` of the first longest near-black run on one row."""
    best = best_start = current = 0
    for x in range(width):
        current = current + 1 if pixels[x, y] < 48 else 0
        if current > best:
            best, best_start = current, x - current + 1
    return best, best_start


def digests_from_path(path: str | None) -> tuple[str, str]:
    """Return ``(world_digest, dialog_digest)`` for a PNG on disk."""
    return digests_from_bytes(_read(path))


def frame_digest_from_path(path: str | None) -> str:
    """Whole-file hash, for noop detection."""
    data = _read(path)
    return _md5(data) if data else "0"
