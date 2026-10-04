"""What a repair says after a reply the token limit cut, by how the reply ran on.

The model never sees the reply it wrote, so the message names what went wrong
(``TruncatedResponseError.runaway``; None when the reply was neither shape plainly) instead of
asking it to be shorter. Shared by the Companion's drafters and its query planner.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

from exulanica.models.errors import TruncatedResponseError
from exulanica.models.response import Runaway

__all__ = ["RUNAWAY_REPAIRS", "runaway_repair"]

#: What a drafter's repair says after a reply the token limit cut, by how it ran on
#: (``TruncatedResponseError.runaway``; None when it was neither plainly). The model never sees the
#: reply it wrote, so the message names what went wrong instead of asking it to be shorter.
RUNAWAY_REPAIRS: Final[Mapping[str | None, str]] = {
    Runaway.WHITESPACE: (
        "That form ran on in blank space after one of its values until it was cut off. Fill it in "
        "again on one line, with no line breaks and no spaces between its parts, a comma between "
        "fields, and stop at its closing brace."
    ),
    Runaway.REPETITION: (
        "That form named the same option over and over until it was cut off. Fill it in again, "
        "naming each option once, and stop at its closing brace."
    ),
    None: (
        "That form ran on until it was cut off. Fill it in again on one line, naming each option "
        "once, and stop at its closing brace."
    ),
}


def runaway_repair(rejected: TruncatedResponseError) -> str:
    """The repair for a reply the token limit cut, named by how it ran on."""
    return RUNAWAY_REPAIRS[rejected.runaway]
