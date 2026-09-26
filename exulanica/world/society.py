"""Shared core of the deterministic synthetic society: identity, draws, events and digests.

Every profile builds on these. The v1 engine and the fixed tables its stored histories depend on
live in ``exulanica.world.society_legacy``. The living society, profile ``exulanica-society/v4``,
lives in ``exulanica.world.society_living``.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from typing import Any, ClassVar, Final

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
    """Rows read under the asset read lock named stored bytes nobody read before it was taken.

    A saved world's input depends on the reviewed bytes and licence of every object it places, and
    they are read and checked before the lock, because a holder reads nothing from the store
    (``docs/asset-read-currency.md``). Rows naming other bytes once the lock is held changed in
    between, so the whole request is refused and asking again reads the bytes first. It is a race,
    not an unavailable input: it is not an :class:`UnavailableSocietyInput`, so no input records
    it and playback does not pause for it (the round fails and the next claim retries). The
    application answers ``status`` with ``code``, the product's retry code, for every route.
    """

    status: ClassVar[int] = 409
    code: ClassVar[str] = "busy"


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
