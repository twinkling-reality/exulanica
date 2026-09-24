"""The bounded evidence packet, and the tokens that make a hallucinated citation impossible.

``architecture-overview.md`` 5.3: "The model never sees the corpus. It sees an **EvidencePacket**
of at most 24 EvidenceItems, assembled by the deterministic query path. Each item carries a
random 10-character token that is valid only within that one packet, mapped server side to
``(span_id, assertion_id)`` for the lifetime of the request."

The token design is doing something specific, and it is worth being precise about what:

    "The token space is unforgeable and packet-scoped. The model cannot construct a valid
    reference to anything outside its packet, because tokens are random per request and resolve
    only through a server-side map. A hallucinated citation is not a wrong citation, it is a
    lookup failure, detected deterministically. There is no 'plausible-looking' failure mode."

That last sentence is the reason this is not a confidence heuristic. A model inventing
``ev_7Kq2mN`` produces a token that resolves to nothing, and the difference between "cited
correctly" and "made it up" is a dictionary lookup rather than a judgement.

**Value references** are the second mechanism. A clause may contain no digit sequence unless a
value reference covers it, so a confidently invented date, count or duration cannot survive. The
values are computed here from the query result, never from the model, and each one carries the
exact string the answer is permitted to use.

**Two things a packet refuses to be built from.** A result reached under
``include_proposals`` cannot be cited, because an ``auto_provisional`` link is a guess and a
historical clause may not rest on one. And an empty result produces an empty packet rather than
a smaller one, because the correct response to no evidence is abstention, not a shorter answer.

**Everything in ``text`` is untrusted.** Captions and OCR are model output over pixels the
system did not author, and a photograph of a sign reading "ignore your instructions" is a
photograph a user may legitimately own. The packet carries the tier so the composer's prompt can
say so, and the answer validator does not trust the composer to have listened: a clause is
checked against the packet, not against what the packet's text asked for.
"""

from __future__ import annotations

import datetime as dt
import secrets
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

import psycopg

from exulanica.evidence import EvidenceAddress
from exulanica.selection.executor import SelectionResult, Support
from exulanica.store.resolve import address_from_span_row

__all__ = [
    "MAX_PACKET_ITEMS",
    "TOKEN_LENGTH",
    "ConfirmedPerson",
    "ConfirmedPlace",
    "ContentEvidenceItem",
    "ContentEvidencePacket",
    "EvidenceItem",
    "EvidencePacket",
    "ValueReference",
    "build_content_packet",
    "build_packet",
]

#: Section 5.3. A cap, not a target: a packet is as small as the evidence is.
MAX_PACKET_ITEMS: Final = 24

TOKEN_LENGTH: Final = 10

#: No ``0O1lI``. A token appears in an answer object and may be read aloud in a bug report, and
#: two tokens that differ only by a confusable pair would make a citation failure look like a
#: transcription error. 31 symbols over 10 places is about 50 bits, which is far more than a
#: per-request namespace of at most 24 needs.
_TOKEN_ALPHABET: Final = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"

#: What a claim's provenance class means for whether it may support a historical clause. A
#: capture-supported fact and a user statement may; a model inference may be described but not
#: asserted, which the composer's prompt states and the validator does not depend on.
_TRUST: Final[dict[str, str]] = {
    "capture": "capture_supported",
    "user": "user_stated",
    "inference": "model_inference",
    "external": "external_lookup",
}


#: The support dimension of a photograph the Selection holds because of a place's confirmed link
#: (:class:`~exulanica.selection.executor.Support`).
_PLACE_DIMENSION: Final = "place"

#: The support dimension of a photograph the Selection holds because of another entity's
#: confirmed link, a person's among them (:class:`~exulanica.selection.executor.Support`).
_ENTITY_DIMENSION: Final = "entity"

#: The one class of entity whose confirmed link on a photograph is stated as who is in it.
_PERSON_CLASS: Final = "person"


@dataclass(frozen=True, slots=True)
class ConfirmedPlace:
    """A place the account holder confirmed a cited photograph was taken at.

    Read from the link that put the photograph in the Selection. A packet is built only from
    confirmed links (:func:`build_packet` carries nothing from a Selection that admitted
    proposals), and only a person's own decision writes a confirmed link
    (``confirmed_needs_a_human`` in ``exulanica/migrations/0001_spine.sql``). So this is the
    account holder's statement about where the photograph was taken, never something a model saw
    in it, and the composer is told it as that.

    A person linked the same way is carried as :class:`ConfirmedPerson`, and an object is not.
    """

    entity_id: uuid.UUID
    #: How the composer's request names the place: its saved name, which the boundary every hosted
    #: request passes sends only under the account holder's right and otherwise writes as the
    #: request's placeholder, ``[place A]``; or that placeholder itself, where another saved name
    #: reads as the same words. Set when the request's names are decided
    #: (:class:`~exulanica.selection.request_names.RequestNames`), and ``None`` in a packet as
    #: built. A place with no saved name has neither and is not stated at all.
    reference: str | None = None


@dataclass(frozen=True, slots=True)
class ConfirmedPerson:
    """A person the account holder confirmed is in a cited photograph.

    Read, like :class:`ConfirmedPlace`, from the confirmed link that put the photograph in the
    Selection, so it is the account holder's statement of who is in the photograph, never
    something a model saw in it. The account holder's rule is that a person's name never reaches
    a hosted model, with or without a right, so the composer is told this person only by the
    request's placeholder, ``[person A]``, and the browser restores the name.

    Carried only for a person who is in the library, not merged into another and whose consent
    stands: the Companion answers nothing about a deleted or merged entity, and a person who
    withdrew has their name withheld from every surface, so a statement that they are in a
    photograph, which is the same fact in other words, is withheld too.
    """

    entity_id: uuid.UUID
    #: The request's placeholder for this person, set when the request's names are decided
    #: (:class:`~exulanica.selection.request_names.RequestNames`), and ``None`` in a packet as
    #: built. A person with no saved name has no placeholder and is not stated at all.
    reference: str | None = None


@dataclass(frozen=True, slots=True)
class EvidenceItem:
    """One thing the model may cite, and the address it resolves to."""

    token: str
    span_id: uuid.UUID
    assertion_id: uuid.UUID | None
    address: EvidenceAddress
    capture_id: uuid.UUID
    captured_at: str | None
    #: The claim text, when this item is an assertion. UNTRUSTED: model output over pixels.
    text: str | None
    #: One of the values of :data:`_TRUST`, or ``capture_supported`` for a bare photograph.
    trust: str
    #: The places the account holder confirmed this photograph was taken at, on the line of the
    #: span the link rests on (the whole photograph, for a place the vision stage proposed). Empty
    #: on a claim's line and on a photograph no place link selected.
    confirmed_places: tuple[ConfirmedPlace, ...] = ()
    #: The people the account holder confirmed are in this photograph, on the line of the span
    #: the link rests on, the way ``confirmed_places`` are. Empty where no person link selected it.
    confirmed_people: tuple[ConfirmedPerson, ...] = ()

    @property
    def uri(self) -> str:
        """The permalink form, for a citation the user can open."""
        return self.address.to_uri()


@dataclass(frozen=True, slots=True)
class ValueReference:
    """A number the answer is allowed to say, and where it came from.

    ``text`` is the exact rendering. The validator compares digit sequences against this string,
    so "3" and "three" are different things and only the first needs a reference.
    """

    key: str
    text: str
    #: What the number is about, for the composer. Never parsed.
    label: str


@dataclass(frozen=True, slots=True)
class EvidencePacket:
    """At most :data:`MAX_PACKET_ITEMS` items, with a per-request token namespace."""

    items: tuple[EvidenceItem, ...]
    values: tuple[ValueReference, ...]
    #: Matches the Selection found before the packet cap. Reported so the composer can say "at
    #: least", and so a silent truncation is impossible.
    total_matched: int
    #: True when the underlying Selection admitted unconfirmed links. A packet in this state
    #: carries no items at all; see :func:`build_packet`.
    citable: bool

    @property
    def is_empty(self) -> bool:
        return not self.items

    def resolve(self, token: str) -> EvidenceItem | None:
        """The item a citation token names, or None. The whole of citation verification.

        **Surrounding brackets are stripped, and that is not leniency about what is citable.**
        The packet renders each photograph as ``[A6EF9VWNT6]`` because brackets are what make the
        token findable in a wall of text, and a model told to cite "the bracketed token" copies
        the brackets with it. Measured: the reasoning core cited ``'[BXEGUBQ9V9]'`` for a token
        that was in the packet, and every clause was discarded for referring to something that
        does not exist.

        Normalising a formatting variant cannot weaken the guarantee. A token is a fixed
        alphanumeric code from a per-request random space, so ``[X]`` resolves if and only if
        ``X`` does; an invented token still resolves to nothing whether it arrives bracketed or
        bare. What would weaken it is accepting a prefix, a fuzzy match or a near-miss, and none
        of those is here.
        """
        return self._by_token.get(token.strip().strip("[]"))

    def canonical(self, token: str) -> str | None:
        """The packet's own spelling of the token :meth:`resolve` accepts, or None.

        The one form every reader of an answer uses. The route keys ``citations`` by the bare
        token, so a clause that kept the brackets the composer copied cited a photograph no
        client could look up: measured in the rehearsal of the personal path, the page offered
        no chip for ``[2EXZHVS3UA]`` while the map held ``2EXZHVS3UA``.
        """
        item = self.resolve(token)
        return None if item is None else item.token

    def value(self, key: str) -> ValueReference | None:
        return self._by_key.get(key)

    @property
    def _by_token(self) -> Mapping[str, EvidenceItem]:
        return {item.token: item for item in self.items}

    @property
    def _by_key(self) -> Mapping[str, ValueReference]:
        return {value.key: value for value in self.values}

    @property
    def truncated(self) -> bool:
        return self.total_matched > len({item.capture_id for item in self.items})


@dataclass(frozen=True, slots=True)
class ContentEvidenceItem:
    """Packet-scoped handle to one immutable typed content lineage."""

    token: str
    truth_class: str
    result_kind: str
    source_id: str
    lineage_ids: tuple[str, ...]
    label: str | None
    personal_visit_evidence: bool


@dataclass(frozen=True, slots=True)
class ContentEvidencePacket:
    items: tuple[ContentEvidenceItem, ...]
    total_matched: int

    def resolve(self, token: str) -> ContentEvidenceItem | None:
        normalized = token.strip().strip("[]")
        return next((item for item in self.items if item.token == normalized), None)


def build_content_packet(result: SelectionResult) -> ContentEvidencePacket:
    """Bound records of every origin without merging truth classes.

    Source, memory, authored, invented and simulated records each keep their own class.
    ``invented`` is generated content: a pure function of a seed, a grammar version and a
    catalog. It has its own truth class so that a generated subject never reaches a model as
    ``"other"``, and ``"other"`` keeps meaning only that the origin is not one this map knows.
    """
    taken: set[str] = set()
    items = tuple(
        ContentEvidenceItem(
            token=_token(taken),
            truth_class={
                "personal": "authorized_memory",
                "imported": "admitted_source",
                "authored": "authored_version",
                "invented": "invented_world",
                "simulated": "simulation",
            }.get(item.origin_kind, "other"),
            result_kind=item.result_kind,
            source_id=item.source_id,
            lineage_ids=item.lineage_ids,
            label=item.label,
            personal_visit_evidence=item.personal_visit_evidence,
        )
        for item in result.content[:MAX_PACKET_ITEMS]
    )
    return ContentEvidencePacket(items=items, total_matched=result.total_matched)


def _token(taken: set[str]) -> str:
    while True:
        candidate = "".join(secrets.choice(_TOKEN_ALPHABET) for _ in range(TOKEN_LENGTH))
        if candidate not in taken:
            taken.add(candidate)
            return candidate


def build_packet(
    connection: psycopg.Connection,
    result: SelectionResult,
    *,
    workspace_id: uuid.UUID,
    now: dt.datetime | None = None,
) -> EvidencePacket:
    """Turn a Selection result into the bounded thing a model is allowed to read.

    Deterministic apart from the tokens, which are deliberately not: a token that could be
    predicted from the request would be a token a caller could construct, and the whole
    unforgeability argument rests on it being drawn per request.
    """
    if result.includes_proposals:
        # An auto_provisional link may drive layout and filtering and may never support a
        # factual claim. Rather than tagging each item and hoping the composer honours the tag,
        # the packet carries nothing: a Selection that included guesses cannot be cited from,
        # and the caller must re-run it confirmed-only to get an answer with citations.
        return EvidencePacket(
            items=(), values=(), total_matched=result.total_matched, citable=False
        )

    spans: list[tuple[Support, uuid.UUID, str | None]] = []
    for capture in result.captures:
        for support in capture.support:
            spans.append((support, capture.capture_id, capture.captured_at))
            if len(spans) >= MAX_PACKET_ITEMS:
                break
        if len(spans) >= MAX_PACKET_ITEMS:
            break

    items = _load_items(connection, workspace_id, spans)
    values = _values(result, items, now=now)
    return EvidencePacket(
        items=items, values=values, total_matched=result.total_matched, citable=True
    )


def _load_items(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    spans: Sequence[tuple[Support, uuid.UUID, str | None]],
) -> tuple[EvidenceItem, ...]:
    """Read the span rows and the claim text, and rebuild each address.

    The address is rebuilt through ``address_from_span_row``, which raises if the reconstructed
    digest does not equal the stored one. That check is not decoration here: the token in the
    answer resolves to this address, and an address that no longer hashes to what was stored is
    a citation that has silently stopped verifying.

    A place or person link supports its photograph's whole line rather than adding one, so
    stating it changes no item count and no token.
    """
    if not spans:
        return ()
    places: dict[tuple[uuid.UUID, uuid.UUID | None], dict[uuid.UUID, None]] = {}
    linked: dict[tuple[uuid.UUID, uuid.UUID | None], dict[uuid.UUID, None]] = {}
    for support, _, _ in spans:
        if support.entity_id is None:
            continue
        key = (support.span_id, support.assertion_id)
        if support.dimension == _PLACE_DIMENSION:
            places.setdefault(key, {})[support.entity_id] = None
        elif support.dimension == _ENTITY_DIMENSION:
            linked.setdefault(key, {})[support.entity_id] = None
    people = _stated_people(
        connection, workspace_id, {entity for found in linked.values() for entity in found}
    )
    span_ids = list({support.span_id for support, _, _ in spans})
    rows = {
        row["span_id"]: row
        for row in connection.execute(
            "select s.* from evidence_span s where s.workspace_id = %s "
            "and s.span_id = any(%s::uuid[]) "
            "and not tombstone_blocks_any_span(s.workspace_id, array[s.span_id]) "
            "and exists (select 1 from capture c where c.workspace_id=s.workspace_id "
            "and c.blob_sha256=s.blob_sha256 and c.deleted_at is null)",
            (workspace_id, span_ids),
        ).fetchall()
    }
    assertion_ids = [s.assertion_id for s, _, _ in spans if s.assertion_id is not None]
    claims = {}
    if assertion_ids:
        claims = {
            row["assertion_id"]: row
            for row in connection.execute(
                "select a.assertion_id, a.kind, a.object_value from assertion a "
                "where a.workspace_id = %s and a.assertion_id = any(%s::uuid[]) "
                "and a.status = 'active'",
                (workspace_id, assertion_ids),
            ).fetchall()
        }

    taken: set[str] = set()
    items: list[EvidenceItem] = []
    seen: set[tuple[uuid.UUID, uuid.UUID | None]] = set()
    for support, capture_id, captured_at in spans:
        span_id, assertion_id = support.span_id, support.assertion_id
        if (span_id, assertion_id) in seen or span_id not in rows:
            continue
        seen.add((span_id, assertion_id))
        if assertion_id is not None and assertion_id not in claims:
            continue
        claim = claims.get(assertion_id) if assertion_id else None
        value = claim["object_value"] if claim else None
        items.append(
            EvidenceItem(
                token=_token(taken),
                span_id=span_id,
                assertion_id=assertion_id,
                address=address_from_span_row(rows[span_id]),
                capture_id=capture_id,
                captured_at=captured_at,
                text=value if isinstance(value, str) else None,
                trust=_TRUST.get(claim["kind"], "model_inference")
                if claim
                else "capture_supported",
                confirmed_places=tuple(
                    ConfirmedPlace(entity_id=place)
                    for place in places.get((span_id, assertion_id), {})
                ),
                confirmed_people=tuple(
                    ConfirmedPerson(entity_id=entity)
                    for entity in linked.get((span_id, assertion_id), {})
                    if entity in people
                ),
            )
        )
    return tuple(items)


def _stated_people(
    connection: psycopg.Connection, workspace_id: uuid.UUID, linked: set[uuid.UUID]
) -> frozenset[uuid.UUID]:
    """Which linked entities are people the packet may state as in a photograph.

    A person, in the library, merged into nobody, and not a person who withdrew:
    ``person_subject_is_withdrawn`` is the predicate the graph withholds a withdrawn person's name
    by (``exulanica/graph/entities.py``), asked rather than restated.
    """
    if not linked:
        return frozenset()
    rows = connection.execute(
        "select e.entity_id from entity e where e.workspace_id = %s "
        "and e.entity_id = any(%s::uuid[]) and e.class::text = %s "
        "and e.deleted_at is null and e.merged_into is null "
        "and not tombstone_blocks_entity(e.workspace_id, e.entity_id) "
        "and not exists (select 1 from person_subject s where s.workspace_id = e.workspace_id "
        "and s.entity_id = e.entity_id "
        "and person_subject_is_withdrawn(s.workspace_id, s.subject_id))",
        (workspace_id, list(linked), _PERSON_CLASS),
    ).fetchall()
    return frozenset(row["entity_id"] for row in rows)


def _values(
    result: SelectionResult, items: Sequence[EvidenceItem], *, now: dt.datetime | None
) -> tuple[ValueReference, ...]:
    """Every number the answer may contain, computed from the result and nothing else.

    Deliberately narrow. A number that is not here cannot be said, and the right response to
    "the composer wanted to say something this list does not cover" is to add the value here,
    where it is derived from the query result, rather than to relax the check.
    """
    values = [
        ValueReference(
            key="capture_count",
            text=str(result.total_matched),
            label="how many captures the Selection matched",
        ),
        ValueReference(
            key="shown_count",
            text=str(len({item.capture_id for item in items})),
            label="how many of them are in this packet",
        ),
    ]
    dates = sorted({item.captured_at[:10] for item in items if item.captured_at})
    for ordinal, date in enumerate(dates):
        values.append(
            ValueReference(
                key=f"date_{ordinal}",
                text=date,
                label="a capture date inside the Selection",
            )
        )
    if len(dates) >= 2:
        values.append(
            ValueReference(key="earliest_date", text=dates[0], label="the earliest capture date")
        )
        values.append(
            ValueReference(key="latest_date", text=dates[-1], label="the latest capture date")
        )
    for ordinal, entity in enumerate(result.entities):
        values.append(
            ValueReference(
                key=f"entity_{ordinal}_captures",
                text=str(entity.capture_count),
                label=f"how many captures entity {entity.entity_id} appears in",
            )
        )
    if now is not None:
        values.append(
            ValueReference(
                key="today", text=now.date().isoformat(), label="today's date, for a meta clause"
            )
        )
    return tuple(values)
