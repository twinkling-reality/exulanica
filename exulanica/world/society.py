"""Pure deterministic synthetic society for one bounded owned district."""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from typing import Any, Final

from exulanica.canonical import canonical_json

SOCIETY_ENGINE_VERSION: Final = "exulanica-society/v1"
SOCIETY_POPULATION: Final = 128
SOCIETY_TICK_SECONDS: Final = 60
SOCIETY_NAMESPACE: Final = uuid.UUID("234a55f8-2680-4fd0-812d-bd67905fc930")
ROLES: Final = ("baker", "designer", "gardener", "student", "steward", "teacher")
FIRST_NAMES: Final = ("Ari", "Bela", "Cleo", "Dara", "Emi", "Faye", "Ivo", "Juno")
LAST_NAMES: Final = ("Ash", "Bell", "Cove", "Dawn", "Elm", "Fox", "Grove", "Hart")


class SocietyError(Exception):
    pass


class UnknownSociety(SocietyError):
    pass


class StaleSocietyState(SocietyError):
    pass


@dataclass(frozen=True, slots=True)
class SocietyEvent:
    event_id: uuid.UUID
    tick: int
    kind: str
    subject_id: uuid.UUID
    object_id: uuid.UUID | None
    document: dict[str, Any]


def _number(seed: str, domain: str, ordinal: int) -> int:
    return int.from_bytes(
        hashlib.sha256(f"{seed}:{domain}:{ordinal}".encode()).digest()[:8],
        "big",
    )


def _inhabitant_id(society_id: uuid.UUID, ordinal: int) -> uuid.UUID:
    return uuid.uuid5(SOCIETY_NAMESPACE, f"{society_id}:inhabitant:{ordinal}")


def initial_society(
    society_id: uuid.UUID,
    seed: str,
    *,
    population: int = SOCIETY_POPULATION,
) -> dict[str, Any]:
    if (
        not isinstance(seed, str)
        or len(seed) != 64
        or any(c not in "0123456789abcdef" for c in seed)
    ):
        raise ValueError("society seed must be a lowercase SHA-256")
    if population < 100 or population > 512:
        raise ValueError("society population must be between 100 and 512")
    inhabitants = []
    for ordinal in range(population):
        identity = _inhabitant_id(society_id, ordinal)
        home = _number(seed, "home", ordinal) % 32
        work = _number(seed, "work", ordinal) % 24
        inhabitants.append(
            {
                "id": str(identity),
                "ordinal": ordinal,
                "display_name": (
                    f"{FIRST_NAMES[ordinal % len(FIRST_NAMES)]} "
                    f"{LAST_NAMES[(ordinal // len(FIRST_NAMES)) % len(LAST_NAMES)]} "
                    f"{ordinal + 1}"
                ),
                "synthetic": True,
                "household": home,
                "role": ROLES[_number(seed, "role", ordinal) % len(ROLES)],
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
        "weather": {"kind": "clear", "temperature_c_milli": 19_000},
        "resources": {"food_milli": 820, "transit_milli": 760},
    }


def advance_society(
    state: dict[str, Any], seed: str
) -> tuple[dict[str, Any], tuple[SocietyEvent, ...]]:
    """Advance one simulated minute without wall time, randomness, or model calls."""
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
            max(-300_000, min(300_000, x + (phase % 1601) - 800)),
            max(-300_000, min(300_000, z + ((phase // 1601) % 1601) - 800)),
        ]
        inhabitant["need_milli"] = min(1000, int(inhabitant["need_milli"]) + 1)
        inhabitants.append(inhabitant)
    next_state = {
        **state,
        "tick": tick,
        "inhabitants": inhabitants,
    }
    return next_state, tuple(events)


def society_state_sha256(state: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(state)).hexdigest()


def event_document_sha256(event: SocietyEvent) -> str:
    return hashlib.sha256(canonical_json(event.document)).hexdigest()
