"""Frozen v1 encoding: the fixed tables stored v1, v2 and v3 societies were generated from.

Nothing new may use this module. The names, roles, ``home:{n}``/``work:{n}`` labels, the fixed
weather and resources blocks and the plus or minus 300 m position bound are not vocabulary or
world facts. They are part of the byte contract of societies that already exist: v1 genesis and
transitions, and v2 and v3 genesis through :func:`initial_society`, hash them, and
``tests/test_society_legacy.py`` pins those digests. They exist only so stored histories replay.
Changing any value here changes every replay. The current profile, ``exulanica-society/v4`` in
``exulanica.world.society_living``, uses none of them: its roles, homes and workplaces come from
the place's premises or are recorded as unavailable, and its positions always lie on the place's
navigation graph.
"""

from __future__ import annotations

import uuid
from typing import Any, Final

from exulanica.world.society import (
    SOCIETY_ENGINE_VERSION,
    SOCIETY_NAMESPACE,
    SOCIETY_POPULATION,
    SOCIETY_TICK_SECONDS,
    SocietyEvent,
    _inhabitant_id,
    _number,
)
from exulanica.world.society_engines import society_engine

#: This genesis is the v1 engine's own, so its population bounds are v1's row of the engine
#: table; a later profile that builds on it passes its own row's bounds.
_V1: Final = society_engine(SOCIETY_ENGINE_VERSION)

__all__ = ["advance_society", "initial_society"]

LEGACY_ROLES: Final = ("baker", "designer", "gardener", "student", "steward", "teacher")
LEGACY_FIRST_NAMES: Final = ("Ari", "Bela", "Cleo", "Dara", "Emi", "Faye", "Ivo", "Juno")
LEGACY_LAST_NAMES: Final = ("Ash", "Bell", "Cove", "Dawn", "Elm", "Fox", "Grove", "Hart")
LEGACY_WEATHER: Final = {"kind": "clear", "temperature_c_milli": 19_000}
LEGACY_RESOURCES: Final = {"food_milli": 820, "transit_milli": 760}
#: An authored bound on v1 wandering, recorded nowhere but here. Not a district extent.
LEGACY_POSITION_BOUND_MM: Final = 300_000


def initial_society(
    society_id: uuid.UUID,
    seed: str,
    *,
    population: int = SOCIETY_POPULATION,
    minimum_population: int = _V1.population_minimum,
    maximum_population: int = _V1.population_maximum,
) -> dict[str, Any]:
    """The seeded population, held to the calling profile's own bounds from the engine table."""
    if (
        not isinstance(seed, str)
        or len(seed) != 64
        or any(c not in "0123456789abcdef" for c in seed)
    ):
        raise ValueError("society seed must be a lowercase SHA-256")
    if population < minimum_population or population > maximum_population:
        raise ValueError(
            f"society population must be between {minimum_population} and {maximum_population}"
        )
    inhabitants = []
    first, last = LEGACY_FIRST_NAMES, LEGACY_LAST_NAMES
    for ordinal in range(population):
        identity = _inhabitant_id(society_id, ordinal)
        home = _number(seed, "home", ordinal) % 32
        work = _number(seed, "work", ordinal) % 24
        inhabitants.append(
            {
                "id": str(identity),
                "ordinal": ordinal,
                "display_name": (
                    f"{first[ordinal % len(first)]} "
                    f"{last[(ordinal // len(first)) % len(last)]} "
                    f"{ordinal + 1}"
                ),
                "synthetic": True,
                "household": home,
                "role": LEGACY_ROLES[_number(seed, "role", ordinal) % len(LEGACY_ROLES)],
                "home_node": f"home:{home}",
                "work_node": f"work:{work}",
                "schedule": {
                    "depart_home_minute": 420 + _number(seed, "depart", ordinal) % 120,
                    "depart_work_minute": 960 + _number(seed, "return", ordinal) % 180,
                },
                "position_mm": [
                    -260_000 + (_number(seed, "x", ordinal) % 520_001),
                    -260_000 + (_number(seed, "z", ordinal) % 520_001),
                ],
                "destination": f"home:{home}",
                "need_milli": 500 + _number(seed, "need", ordinal) % 401,
                "memory": [],
            }
        )
    relationships = [
        {
            "left": inhabitants[ordinal]["id"],
            "right": inhabitants[ordinal + 1]["id"],
            "kind": "household",
            "strength_milli": 850,
        }
        for ordinal in range(0, population - 1, 2)
    ]
    return {
        "profile": SOCIETY_ENGINE_VERSION,
        "society_id": str(society_id),
        "tick": 0,
        "tick_seconds": SOCIETY_TICK_SECONDS,
        "inhabitants": inhabitants,
        "relationships": relationships,
        "weather": dict(LEGACY_WEATHER),
        "resources": dict(LEGACY_RESOURCES),
    }


def advance_society(
    state: dict[str, Any], seed: str
) -> tuple[dict[str, Any], tuple[SocietyEvent, ...]]:
    """Advance one simulated minute without wall time, randomness, or model calls."""
    if state.get("profile") != SOCIETY_ENGINE_VERSION:
        raise ValueError("unsupported legacy society profile")
    tick = int(state["tick"]) + 1
    minute = tick % 1440
    society_id = uuid.UUID(str(state["society_id"]))
    inhabitants = []
    events: list[SocietyEvent] = []
    for held in state["inhabitants"]:
        inhabitant = dict(held)
        schedule = inhabitant["schedule"]
        departing = minute in {
            int(schedule["depart_home_minute"]),
            int(schedule["depart_work_minute"]),
        }
        if departing:
            going_to_work = minute == int(schedule["depart_home_minute"])
            inhabitant["destination"] = (
                inhabitant["work_node"] if going_to_work else inhabitant["home_node"]
            )
            kind = "departed"
            event_id = uuid.uuid5(
                SOCIETY_NAMESPACE,
                f"{society_id}:{tick}:{inhabitant['ordinal']}:{kind}",
            )
            document = {
                "synthetic": True,
                "summary": (
                    f"{inhabitant['display_name']} departed for "
                    f"{inhabitant['destination']} on the simulated schedule."
                ),
            }
            events.append(
                SocietyEvent(
                    event_id,
                    tick,
                    kind,
                    uuid.UUID(inhabitant["id"]),
                    None,
                    document,
                )
            )
            memory = [*inhabitant["memory"], str(event_id)][-16:]
            inhabitant["memory"] = memory
        x, z = inhabitant["position_mm"]
        phase = _number(seed, f"path:{tick}", int(inhabitant["ordinal"]))
        inhabitant["position_mm"] = [
            max(-LEGACY_POSITION_BOUND_MM, min(LEGACY_POSITION_BOUND_MM, x + (phase % 1601) - 800)),
            max(
                -LEGACY_POSITION_BOUND_MM,
                min(LEGACY_POSITION_BOUND_MM, z + ((phase // 1601) % 1601) - 800),
            ),
        ]
        inhabitant["need_milli"] = min(1000, int(inhabitant["need_milli"]) + 1)
        inhabitants.append(inhabitant)
    next_state = {
        **state,
        "tick": tick,
        "inhabitants": inhabitants,
    }
    return next_state, tuple(events)
