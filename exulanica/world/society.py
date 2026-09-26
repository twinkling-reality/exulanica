"""Shared core of the deterministic synthetic society: identity, draws, events and digests.

Every profile builds on these. The v1 engine and the fixed tables its stored histories depend on
live in ``exulanica.world.society_legacy``. The living society, profile ``exulanica-society/v4``,
lives in ``exulanica.world.society_living``.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, ClassVar, Final, TypeVar

from exulanica.canonical import canonical_json

SOCIETY_ENGINE_VERSION: Final = "exulanica-society/v1"
SOCIETY_POPULATION: Final = 128
SOCIETY_TICK_SECONDS: Final = 60
SOCIETY_NAMESPACE: Final = uuid.UUID("234a55f8-2680-4fd0-812d-bd67905fc930")


class SocietyError(Exception):
    pass


class UnknownSociety(SocietyError):
    pass


class UnavailableSocietyInput(SocietyError):
    pass


class SocietyBytesNotRead(RuntimeError):
    """Rows read under the asset read lock name stored bytes other than those read before it.

    A society's input depends on stored bytes (each placed object's reviewed asset and licence,
    and a district's sources and artifacts), and every input a transaction authorizes has them
    read and checked before the lock, because a holder reads nothing from the store
    (``docs/asset-read-currency.md``). A reviewed asset row that changed between that read and the
    lock names other bytes, so the whole transaction is refused and asking again reads the bytes
    first. It is a race, not an unavailable input: it is not an :class:`UnavailableSocietyInput`,
    so no input records it and playback does not pause for it (the round fails and the next claim
    retries). The application answers ``status`` with ``code``, the product's retry code, for every
    route.
    """

    status: ClassVar[int] = 409
    code: ClassVar[str] = "busy"


#: How many times a whole transaction that met :class:`SocietyBytesNotRead` is asked again. Each
#: try reads its inputs' bytes before its lock, so it meets the race again only when a reviewed
#: asset row changes again in that window, and the product never changes one: the importer refuses
#: to rebind or republish a key (``exulanica/world/asset_import.py``). A declared contract.
RETRIES_AFTER_A_RACE: Final = 1

_T = TypeVar("_T")


def asked_again_after_a_race(action: Callable[[bool], _T]) -> _T:
    """``action``, one whole transaction, asked again after the race, up to the declared count.

    ``action`` is told whether this is its last try, so a step that must not be left open, such as
    recording a model's answer, can end terminally rather than meet the race once more. Each try
    before the last rolled back and holds nothing.
    """
    for attempt in range(RETRIES_AFTER_A_RACE + 1):
        last = attempt == RETRIES_AFTER_A_RACE
        try:
            return action(last)
        except SocietyBytesNotRead:
            if last:
                raise
    raise AssertionError("the loop returns or raises on its last try")


#: The inputs, and the reviewed assets, each connection's current work will ask a society to
#: authorize, announced before the first of them takes the asset read lock (:func:`inputs_ahead`).
_AHEAD: ContextVar[tuple[tuple[int, tuple[dict[str, Any], ...], frozenset[str]], ...]] = ContextVar(
    "society_inputs_ahead", default=()
)


@contextmanager
def inputs_ahead(
    connection: object,
    documents: Iterable[dict[str, Any]] = (),
    *,
    assets: Iterable[str] = (),
) -> Iterator[None]:
    """Announce what ``connection``'s transaction will authorize, while the block runs.

    Every authorization takes the global asset read lock and holds it until the transaction
    commits, so the society's runtime reads the stored bytes of every announced input, and of each
    announced reviewed asset (by content digest), before the first authorization in the
    transaction takes the lock. A repository that authorizes several inputs in one transaction
    announces them all first; inside a block, announcing again adds to what is announced.
    """
    frame = (id(connection), tuple(documents), frozenset(assets))
    token = _AHEAD.set((*_AHEAD.get(), frame))
    try:
        yield
    finally:
        _AHEAD.reset(token)


def announced_inputs(connection: object) -> tuple[tuple[dict[str, Any], ...], frozenset[str]]:
    """Every input and reviewed asset digest announced for ``connection`` in the running blocks."""
    documents: list[dict[str, Any]] = []
    assets: set[str] = set()
    for owner, announced, digests in _AHEAD.get():
        if owner == id(connection):
            documents.extend(announced)
            assets |= digests
    return tuple(documents), frozenset(assets)


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


def society_state_sha256(state: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(state)).hexdigest()


def event_document_sha256(event: SocietyEvent) -> str:
    return hashlib.sha256(canonical_json(event.document)).hexdigest()
