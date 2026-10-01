"""The bounded context a project gives a reader, in a fixed order, recomputed at every read.

A pure function over the items a reader may see, their current revisions and the state of what
they name. The repository gathers those under the reader's own authorization; this module decides
only which of them fit and in what order, so the rule can be read, tested and replayed without a
database.

Nothing here is stored. An assembly is computed from current rows every time it is asked for, so
an item deleted after one assembly is absent from the next, and there is no cached prompt or
summary it could come back through. What a caller may keep is :attr:`Assembly.assembly_sha256`,
which covers the project's revision and each entry's item and revision and no text.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final

from exulanica.canonical import canonical_json

__all__ = [
    "ASSEMBLY_PROFILE",
    "DEFAULT_MAX_BYTES",
    "DEFAULT_MAX_ENTRIES",
    "KIND_ORDER",
    "MAX_BYTES",
    "MAX_ENTRIES",
    "MIN_BYTES",
    "Assembly",
    "Budget",
    "Candidate",
    "assemble",
    "entry_bytes",
    "focus_words",
]

ASSEMBLY_PROFILE: Final = "exulanica.project-context/v1"

#: How many entries and how many bytes of their canonical JSON an assembly may hold. Defaults a
#: reader gets without asking; the bounds are the contract's (``docs/project-context.md``).
DEFAULT_MAX_ENTRIES: Final = 24
MAX_ENTRIES: Final = 64
DEFAULT_MAX_BYTES: Final = 8_192
MIN_BYTES: Final = 1_024
MAX_BYTES: Final = 32_768

#: What a person set out to do comes first, then how they want it done, then what is still open,
#: then what was decided, then what the simulation showed.
KIND_ORDER: Final = ("goal", "preference", "task", "question", "decision", "event")

#: A word of a focus: three or more letters or digits, compared without case. A focus orders
#: entries; it never admits one the reader could not otherwise see.
_WORD: Final = re.compile(r"[^\W_]{3,}")


@dataclass(frozen=True, slots=True)
class Budget:
    max_entries: int = DEFAULT_MAX_ENTRIES
    max_bytes: int = DEFAULT_MAX_BYTES

    def __post_init__(self) -> None:
        if type(self.max_entries) is not int or not 1 <= self.max_entries <= MAX_ENTRIES:
            raise ValueError(f"max_entries is between 1 and {MAX_ENTRIES}")
        if type(self.max_bytes) is not int or not MIN_BYTES <= self.max_bytes <= MAX_BYTES:
            raise ValueError(f"max_bytes is between {MIN_BYTES} and {MAX_BYTES}")


@dataclass(frozen=True, slots=True)
class Candidate:
    """One item a reader may see, as an entry would carry it.

    ``entry`` is the served entry, provenance included and nothing hidden from this reader in it.
    ``required_available`` is False when the item exists only to point at records and none of
    them is available now: a decision whose every edit stands on a deleted source.
    """

    item_id: uuid.UUID
    revision: int
    kind: str
    changed_at: dt.datetime
    text: str | None
    entry: Mapping[str, Any]
    required_available: bool = True


@dataclass(frozen=True, slots=True)
class Assembly:
    profile: str
    entries: tuple[Mapping[str, Any], ...]
    used_bytes: int
    omitted: Mapping[str, int]
    assembly_sha256: str
    budget: Budget = field(default_factory=Budget)


def focus_words(text: str | None) -> frozenset[str]:
    return frozenset() if not text else frozenset(w.casefold() for w in _WORD.findall(text))


def entry_bytes(entry: Mapping[str, Any]) -> int:
    """What an entry costs: the bytes of its canonical JSON, the form a caller sends onward."""
    return len(canonical_json(_jsonable(entry)))


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(v) for v in value]
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, dt.datetime):
        return value.isoformat()
    return value


def assemble(
    candidates: Sequence[Candidate],
    *,
    project_revision: int,
    budget: Budget,
    focus: str | None = None,
    omitted: Mapping[str, int] | None = None,
) -> Assembly:
    """The entries that fit, in order, and a count of every candidate left out and why.

    Order: items sharing more words with ``focus`` first, then :data:`KIND_ORDER`, then the most
    recently changed, then the item id, so two reads of the same rows give the same assembly. An
    entry that does not fit the remaining bytes is left out whole, never cut: a preference with
    its last clause missing can say the opposite of what the person wrote. ``omitted`` carries the
    reasons the repository already applied (proposals, resolved items) into the same count.
    """
    words = focus_words(focus)
    counts = {"over_budget": 0, "reference_unavailable": 0, **(omitted or {})}

    def order(candidate: Candidate) -> tuple[int, int, float, str]:
        overlap = len(words & focus_words(candidate.text)) if words else 0
        return (
            -overlap,
            KIND_ORDER.index(candidate.kind),
            -candidate.changed_at.timestamp(),
            str(candidate.item_id),
        )

    chosen: list[Mapping[str, Any]] = []
    pinned: list[list[Any]] = []
    used = 0
    for candidate in sorted(candidates, key=order):
        if not candidate.required_available:
            counts["reference_unavailable"] += 1
            continue
        cost = entry_bytes(candidate.entry)
        if len(chosen) >= budget.max_entries or used + cost > budget.max_bytes:
            counts["over_budget"] += 1
            continue
        chosen.append(candidate.entry)
        pinned.append([str(candidate.item_id), candidate.revision])
        used += cost
    digest = hashlib.sha256(
        canonical_json({"project_revision": project_revision, "entries": pinned})
    ).hexdigest()
    return Assembly(
        profile=ASSEMBLY_PROFILE,
        entries=tuple(chosen),
        used_bytes=used,
        omitted=counts,
        assembly_sha256=digest,
        budget=budget,
    )
