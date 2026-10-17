"""Names for a society of things' invented people: two-part names without numbers.

A society of things made since the identity catalog's second version records it in its first
input (:data:`IDENTITY_FIELD`, written by
:func:`~exulanica.world.society_thing_inputs.record_modules`), and its state keeps the record from
genesis. Each of its invented people is then named by a first and a last name from that version
(``assets/catalogs/society/society-legacy-identity.v2.json``), the pair drawn by the society's own
seed without repeats: the ordinal-th pair of a permutation of every pair the version holds, by a
forward shuffle whose step ``i`` swaps in the pair at a position its seed and ``i`` give
(:func:`drawn_names`). So the same society names the same person the same way on any machine, and
no two of its first 1,600 people share a name; past every pair the draw starts again. A name
carries no number.

A society whose first input records no identity, as every one made before this version, names its
people from the first version as it always did
(:func:`~exulanica.world.society_legacy.initial_society`, a number after every name), so its
stored genesis and every replay stay as they were. A kind's beings are named by their kind, as
before.

Pure: no connection, no store.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from functools import cache
from typing import Any, Final

from exulanica.grammar.catalogs import CatalogError, catalog_digest, load_catalog
from exulanica.world.society_catalogs import (
    LEGACY_IDENTITY_CATALOG,
    LEGACY_IDENTITY_DIGESTS,
    ROUTINE_DIRECTORY,
    SCHEMAS,
)

__all__ = [
    "IDENTITY_FIELD",
    "IDENTITY_VERSION",
    "check_identity",
    "drawn_names",
    "identity_record",
    "name_people",
]

#: Where a first input and its society's state record the identity catalog version naming people.
IDENTITY_FIELD: Final = "identity"
#: The version a new society of things records.
IDENTITY_VERSION: Final = 2
#: What a hash names the draw by, beside the society's seed and the step.
_DRAW: Final = "names"
#: How the population a society starts with came, as a society of things records it.
_POPULATED: Final = "populated"


def identity_record() -> dict[str, Any]:
    """What a new society of things' first input records: the catalog and version naming its
    people."""
    return {"catalog": LEGACY_IDENTITY_CATALOG, "version": IDENTITY_VERSION}


def check_identity(record: object) -> None:
    """A recorded identity held to its shape: the identity catalog, at a version that names people
    by pairs (the second); refused by name otherwise."""
    if record != identity_record():
        raise ValueError(
            f"a society of things records the {LEGACY_IDENTITY_CATALOG} catalog at version "
            f"{IDENTITY_VERSION} for its people's names"
        )


@cache
def _pairs(version: int) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """The first and last names of ``version``, held to its published digest."""
    catalog = load_catalog(
        ROUTINE_DIRECTORY.joinpath(f"{LEGACY_IDENTITY_CATALOG}.v{version}.json"),
        SCHEMAS[(LEGACY_IDENTITY_CATALOG, version)],
    )
    if catalog_digest([catalog]) != LEGACY_IDENTITY_DIGESTS[version]:
        raise CatalogError(
            f"{LEGACY_IDENTITY_CATALOG} v{version} is published and stored societies hold the "
            "names it gave: a change is a new version, never an edit to this one"
        )
    values = [dict(entry.values) for entry in catalog.entries]
    first = tuple(str(v["text"]) for v in values if v["kind"] == "first_name")
    last = tuple(str(v["text"]) for v in values if v["kind"] == "last_name")
    return first, last


def _swap(seed: str, step: int, span: int) -> int:
    digest = hashlib.sha256(f"{seed}:{_DRAW}:{step}".encode()).digest()
    return int.from_bytes(digest[:8], "big") % span


def drawn_names(seed: str, count: int, version: int = IDENTITY_VERSION) -> list[str]:
    """The first ``count`` names a society of ``seed`` gives its invented people under
    ``version``, ordinal by ordinal: each the next pair of the seed's shuffle of every
    (first, last) pair, so a shorter list is the start of a longer one. Past every pair the
    shuffle starts again."""
    first, last = _pairs(version)
    total = len(first) * len(last)
    names: list[str] = []
    order = list(range(total))
    for step in range(count):
        position = step % total
        if position == 0 and step:
            order = list(range(total))
        swap = position + _swap(seed, step, total - position)
        order[position], order[swap] = order[swap], order[position]
        pair = order[position]
        names.append(f"{first[pair // len(last)]} {last[pair % len(last)]}")
    return names


def name_people(people: Iterable[dict[str, Any]], seed: str, record: Mapping[str, Any]) -> None:
    """Name each invented person in ``people`` (the population a society starts with) by its
    ordinal under ``record``, the identity its first input recorded, in place. A being the author
    placed, or that came in later, keeps the name its kind gives it."""
    check_identity(record)
    chosen = [
        person
        for person in people
        if person.get("synthetic") is True and person.get("came_by", _POPULATED) == _POPULATED
    ]
    if not chosen:
        return
    last = max(int(person["ordinal"]) for person in chosen)
    names = drawn_names(seed, last + 1, int(record["version"]))
    for person in chosen:
        person["display_name"] = names[int(person["ordinal"])]
