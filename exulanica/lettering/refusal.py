"""The one refusal lettering raises, and the reasons it can carry.

A refusal names one reason from a closed set, the same set ``@exulanica/loom-lettering`` uses, so
the shared cases can hold both languages to the same answer. The message says what was wrong in
words; only the reason is shared.
"""

from __future__ import annotations

from typing import Final

__all__ = ["CATALOG_REASONS", "LAYOUT_REASONS", "LetteringRefused"]

#: Why a glyph catalog is refused, in the order the reader checks.
CATALOG_REASONS: Final = (
    "json",
    "shape",
    "promise",
    "characters",
    "kerning",
    "ring",
    "metrics",
)
#: Why a sign layout is refused, in the order the layout rule checks.
LAYOUT_REASONS: Final = (
    "alignment",
    "cap_height",
    "tracking",
    "box",
    "text",
    "character",
    "fit",
    "touch",
)


class LetteringRefused(ValueError):
    """A catalog or a sign this package will not accept, with the shared reason."""

    def __init__(self, reason: str, message: str) -> None:
        if reason not in CATALOG_REASONS and reason not in LAYOUT_REASONS:
            raise ValueError(f"unknown lettering refusal reason {reason!r}")
        super().__init__(f"{reason}: {message}")
        self.reason = reason
