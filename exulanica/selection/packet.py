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
from exulanica.selection.executor import SelectionResult
from exulanica.store.resolve import address_from_span_row

__all__ = [
    "MAX_PACKET_ITEMS",
    "TOKEN_LENGTH",
    "EvidenceItem",
    "EvidencePacket",
    "ValueReference",
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

    spans: list[tuple[uuid.UUID, uuid.UUID | None, uuid.UUID, str | None]] = []
    for capture in result.captures:
        for support in capture.support:
            spans.append((support.span_id, support.assertion_id, capture.capture_id,
                          capture.captured_at))
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
    spans: Sequence[tuple[uuid.UUID, uuid.UUID | None, uuid.UUID, str | None]],
) -> tuple[EvidenceItem, ...]:
    """Read the span rows and the claim text, and rebuild each address.

    The address is rebuilt through ``address_from_span_row``, which raises if the reconstructed
    digest does not equal the stored one. That check is not decoration here: the token in the
    answer resolves to this address, and an address that no longer hashes to what was stored is
    a citation that has silently stopped verifying.
    """
    if not spans:
        return ()
    span_ids = list({span_id for span_id, _, _, _ in spans})
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
    assertion_ids = [a for _, a, _, _ in spans if a is not None]
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
    for span_id, assertion_id, capture_id, captured_at in spans:
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
            )
        )
    return tuple(items)


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
