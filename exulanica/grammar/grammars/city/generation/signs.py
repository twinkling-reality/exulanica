"""How much fascia a shop's sign needs to be read from across the street.

Nothing draws lettering yet: a sign is a lexicon key and its text on a premises record. The
generators still hold every signed premises to a fascia its text fits at a readable size, so the
lettering that comes later has room.

* **Cap height 250 mm.** A common signage rule of thumb gives about 25 mm of letter height per 3 m
  of reading distance; across a street of 14 to 20 m that is 115 to 170 mm, and 250 mm reads
  comfortably at the far side. The rule of thumb was not re-read from a source in this build.
* **Advance 175 mm** per character, seven tenths of the cap height, the width of a plain sans serif
  letter with its spacing.
* **Margins 250 mm** at each end of the text, one cap height, and **175 mm** above and below it.

So a fascia is at least 600 mm tall (250 + 2 * 175), and a sign of ``n`` characters needs
``500 + 175 * n`` mm of fascia run. Every number here is authored and awaits admitted legibility
statistics; none is measured.
"""

from __future__ import annotations

from typing import Final

__all__ = [
    "SIGN_ADVANCE_MM",
    "SIGN_CAP_HEIGHT_MM",
    "SIGN_END_MARGIN_MM",
    "SIGN_FASCIA_MINIMUM_MM",
    "SIGN_LINE_MARGIN_MM",
    "sign_run_mm",
]

SIGN_CAP_HEIGHT_MM: Final = 250
SIGN_ADVANCE_MM: Final = 175
SIGN_END_MARGIN_MM: Final = 250
SIGN_LINE_MARGIN_MM: Final = 175
SIGN_FASCIA_MINIMUM_MM: Final = SIGN_CAP_HEIGHT_MM + 2 * SIGN_LINE_MARGIN_MM


def sign_run_mm(text: str) -> int:
    """The fascia run a sign's text needs, margins included."""
    return 2 * SIGN_END_MARGIN_MM + SIGN_ADVANCE_MM * len(text)
