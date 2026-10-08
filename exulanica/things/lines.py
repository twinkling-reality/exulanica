"""A line: one plain line of words, held to one rule wherever words are stored or said.

The rule covers everything a thing says and every word a translation states about what came
across: one line of 1 to 200 code points in Unicode normal form C, with no control, format,
surrogate, private-use, line-separator or paragraph-separator character (Unicode categories Cc,
Cf, Cs, Co, Zl and Zp) and no white space at either end. A line not already in normal form C is
refused rather than rewritten, so what is stored is what was written; a caller holding text from
outside normalises it first and stores the normal form.

Pure: no connection, no store.
"""

from __future__ import annotations

import unicodedata
from typing import Final

__all__ = ["HEARD_LINES_MAXIMUM", "LINE_CHARACTERS_MAXIMUM", "LineRefused", "check_line"]

#: The most code points one line holds.
LINE_CHARACTERS_MAXIMUM: Final = 200
#: The most lines one being may keep, whatever a contract keeps: the bound on the field.
HEARD_LINES_MAXIMUM: Final = 64
#: Characters no line holds: they would break a line, hide text or carry no meaning a reader sees.
_REFUSED_CATEGORIES: Final = frozenset({"Cc", "Cf", "Cs", "Co", "Zl", "Zp"})


class LineRefused(ValueError):
    """Text that is not one plain line within the bound."""

    code: Final = "line_out_of_bounds"


def check_line(value: object, *, maximum: int = LINE_CHARACTERS_MAXIMUM) -> str:
    """``value`` as a line, or :class:`LineRefused` saying which rule it breaks."""
    if not isinstance(value, str):
        raise LineRefused("a line is text")
    if unicodedata.normalize("NFC", value) != value:
        raise LineRefused("a line is in Unicode normal form C")
    if not 1 <= len(value) <= maximum:
        raise LineRefused(f"a line holds 1 to {maximum} code points")
    if value != value.strip():
        raise LineRefused("a line has no white space at either end")
    if any(unicodedata.category(character) in _REFUSED_CATEGORIES for character in value):
        raise LineRefused("a line holds no control, format or separator character")
    return value
