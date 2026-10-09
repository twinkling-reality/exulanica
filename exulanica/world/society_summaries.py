"""How a society's event summaries name the one they are about.

Every summary a society's events and its people's explanations give names its person
"{display name} (simulated)", as every society of people has. A visitor that crossed in from another
program is not simulated: in a society whose crossing module is the second version
(``exulanica-ability/crossing/v2``, every society of things made since it was built) a summary names
a visitor by what it is, from outside and decided by its own program or by this world, and a
crossing refused before anybody arrived as from outside. A society that recorded the first version,
or none, names everybody as it always did, so every stored minute replays as it ran.

Pure: it reads the state it is given and nothing else.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

from exulanica.abilities.registry import recorded_row
from exulanica.world.deciders import decided_by_world

__all__ = [
    "FROM_OUTSIDE",
    "PROGRAM_DECIDES",
    "SIMULATED",
    "WORLD_DECIDES",
    "crossing_name",
    "names_visitors",
    "summary_name",
]

#: What a summary says of a person of the society's own: every person a society of people holds.
SIMULATED: Final = "simulated"
#: What it says of a visitor whose own program decides for it, and of one this world decides for.
PROGRAM_DECIDES: Final = "from outside, decided by its own program"
WORLD_DECIDES: Final = "from outside, decided by this world"
#: What it says of a crossing refused before anybody arrived.
FROM_OUTSIDE: Final = "from outside"


def names_visitors(state: Mapping[str, Any]) -> bool:
    """Whether a society's summaries name its visitors by what they are: where its first input
    recorded the crossing module's second version."""
    row = recorded_row(state.get("modules", ()), "crossing")
    return row is not None and row.version >= 2


def summary_name(state: Mapping[str, Any], person: Mapping[str, Any], name: str) -> str:
    """``name`` as a summary says it of ``person``: "(simulated)" after it, or, for a visitor of a
    society that names its visitors, what it is."""
    if person.get("came_by") == "crossed" and names_visitors(state):
        return f"{name} ({WORLD_DECIDES if decided_by_world(person) else PROGRAM_DECIDES})"
    return f"{name} ({SIMULATED})"


def crossing_name(state: Mapping[str, Any], name: str) -> str:
    """``name`` as a summary says it of a crossing refused before anybody arrived, or of a
    departure naming nobody here: from outside, in a society that names its visitors."""
    return f"{name} ({FROM_OUTSIDE if names_visitors(state) else SIMULATED})"
