"""Recorded kind preferences for autonomous purposeful choices, without changing abilities.

Only purposeful/v3 reads these weights. An omitted key is zero: creature assembly omits
zero-weight entries while retaining the corresponding ability. No kind means the world's
routine still decides; an erased kind instead has no weighted activity. Other abilities' weights
remain outside this module, including hands and following.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from exulanica.abilities.registry import recorded_row
from exulanica.world.society_kinds import kind_here

PURPOSEFUL_KEYS = ("wait", "stand", "talk", "rest", "visit")


def routine_weights(state: Mapping[str, Any]) -> dict[str, dict[str, int]]:
    """Each stated kind's five weights for this minute, absent for historical or untyped people.

    The cache lasts only this call and reads the state's exact kind references and run forms.
    Capability remains authoritative even when a supplied map contains other abilities.
    """
    row = recorded_row(state.get("modules", ()), "purposeful")
    if row is None or row.version < 3:
        return {}
    kinds: dict[tuple[str, str], dict[str, int]] = {}
    people = {}
    for person in state["inhabitants"]:
        reference = person.get("kind")
        if reference is None:
            continue
        key = (reference.get("source", "shipped"), reference["sha256"])
        if key not in kinds:
            kind = kind_here(state, reference)
            abilities = {ability["key"] for ability in kind.document["abilities"]}
            weights = kind.document["routine"]["weights"]
            kinds[key] = {
                name: int(weights.get(name, 0)) if name in abilities else 0
                for name in PURPOSEFUL_KEYS
            }
        people[person["id"]] = kinds[key]
    return people
