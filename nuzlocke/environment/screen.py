"""Screen-region digests for the 160x144 Game Boy frame.

Gen 1 draws its text box in the bottom 6 tile rows (y >= 96). Hashing the
*whole* PNG makes any animating or scrolling text look like progress — which
is how a 33-minute Prof Oak dialogue loop went undetected in run
``20260821-164159-3c5a68``: the frame changed every cycle while the world
behind the text box never did.

So split the frame:

- **world region** (rows 0..95)  — did anything in the game world change?
- **dialog region** (rows 96..143) — is text still advancing?

The world digest is the honest "did we make progress" signal. Opening or
closing an NPC text box does not touch it; walking, menus (Gen 1 draws the
START menu top-right), battles, and map transitions all do.

Pillow only — deliberately no NumPy. NumPy reaches this venv through PyBoy in
the optional ``emu`` extra, so a base ``uv sync`` does not have it, and a
NumPy-based split would silently fall back to whole-file hashing and quietly
disable the stuck detection that depends on it.

On an unreadable frame both digests still fall back to the whole-file hash,
which is exactly the old behaviour.
"""

from __future__ import annotations

import hashlib
import io

FRAME_W = 160
FRAME_H = 144
# Gen 1 text box: bottom 6 tile rows of the 18-row screen.
DIALOG_TOP = 96


def _whole(data: bytes) -> tuple[str, str]:
    digest = hashlib.md5(data).hexdigest() if data else "0"
    return digest, digest


def digests_from_bytes(data: bytes) -> tuple[str, str]:
    """Return ``(world_digest, dialog_digest)`` for a raw PNG frame."""
    if not data:
        return "0", "0"
    try:
        from PIL import Image

        with Image.open(io.BytesIO(data)) as img:
            grey = img.convert("L")
            width, height = grey.size
            if height <= DIALOG_TOP:
                return _whole(data)
            world = grey.crop((0, 0, width, DIALOG_TOP)).tobytes()
            dialog = grey.crop((0, DIALOG_TOP, width, height)).tobytes()
    except Exception:
        return _whole(data)
    return (
        hashlib.md5(world).hexdigest(),
        hashlib.md5(dialog).hexdigest(),
    )


def text_box_open(path: str | None) -> bool:
    """True when a Gen 1 narrative box is drawn in the bottom six tile rows.

    The box is a white panel with a black frame: two or more rows that are
    mostly dark (top and bottom edges) and a run of rows whose only dark
    pixels are the left and right edges. A sprite animating above that box
    is still the same conversation.
    """
    if not path:
        return False
    try:
        from PIL import Image

        with Image.open(path) as img:
            grey = img.convert("L")
    except Exception:
        return False
    width, height = grey.size
    if height <= DIALOG_TOP or width < 32:
        return False
    bar_rows = 0
    side_rows = 0
    for y in range(DIALOG_TOP, height):
        dark = 0
        for x in range(width):
            if grey.getpixel((x, y)) < 48:
                dark += 1
        if dark >= width // 2:
            bar_rows += 1
        elif 2 <= dark <= 16:
            side_rows += 1
    return bar_rows >= 2 and side_rows >= 8


def digests_from_path(path: str | None) -> tuple[str, str]:
    """Return ``(world_digest, dialog_digest)`` for a PNG on disk."""
    if not path:
        return "0", "0"
    try:
        with open(path, "rb") as fh:
            return digests_from_bytes(fh.read())
    except OSError:
        return "0", "0"


def frame_digest_from_path(path: str | None) -> str:
    """Whole-frame hash — the pre-split fingerprint, kept for noop detection."""
    if not path:
        return "0"
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError:
        return "0"
    return hashlib.md5(data).hexdigest() if data else "0"
