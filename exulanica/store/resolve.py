"""Resolving an evidence address back to the original bytes.

This is the closing half of the contract. An address is worth having only if it opens, and it
must open against **original media**, never against a rendition, a thumbnail or any other
derivative. The rendition exists so a model can look at something small; it is not what a
citation resolves to, and there is no function in this module that returns one.

It lives beside the store rather than beside the ingest pipeline because the readers are not
the ingest path. The Selection executor builds citation packets out of these addresses and the
evidence endpoint serves the bytes; neither of those is ingestion, and a read path that had to
import the writer to open a citation would be the wrong way round.

``address_from_span_row`` exists to prove the round trip: a span read back out of the database
reconstructs an address whose digest equals the digest that was stored. If that ever stops
being true, every citation token in every archived answer has silently stopped verifying, and
this is the cheapest place to find out.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from exulanica.errors import IntegrityError
from exulanica.evidence import EvidenceAddress, Modality, TimeInterval
from exulanica.evidence.blob import BlobId
from exulanica.evidence.region import DisplayGeometry, Rect, Region
from exulanica.store.base import ContentAddressedStore

__all__ = ["address_from_span_row", "resolve_original_bytes"]


def address_from_span_row(row: Mapping[str, Any]) -> EvidenceAddress:
    """Rebuild an address from a stored span. The digest must come out identical.

    ``region`` arrives already decoded. It is a ``jsonb`` column and psycopg hands back the
    Python value, so there is nothing here to parse; ``bytea`` arrives as ``bytes`` or as a
    ``memoryview``, which is why the two digest columns are wrapped.
    """
    data = dict(row)
    parsed = data.get("region")
    region = None
    if parsed:
        rect = parsed["rect"]
        display = parsed["display"]
        region = Region(
            rect=Rect(rect["x"], rect["y"], rect["w"], rect["h"]),
            display=DisplayGeometry(
                w=display["w"],
                h=display["h"],
                rotation=display["rotation"],
                sar_num=display["sar_num"],
                sar_den=display["sar_den"],
            ),
            kind=parsed.get("kind", "rect"),
        )
    address = EvidenceAddress(
        blob_id=BlobId(bytes(data["blob_sha256"])),
        track_key=data["track_key"],
        interval=TimeInterval(int(data["t_start_ns"]), int(data["t_end_ns"])),
        modality=Modality(data["modality"]),
        region=region,
        span_format_version=int(data["span_format_version"]),
    )
    stored = bytes(data["span_digest"])
    if address.span_digest != stored:
        raise IntegrityError(
            f"span {data.get('span_id')} rebuilt to digest {address.span_digest_hex} but was "
            f"stored as {stored.hex()}. Every citation token verified against the stored "
            "digest would now fail."
        )
    return address


def resolve_original_bytes(address: EvidenceAddress, store: ContentAddressedStore) -> bytes:
    """The original bytes an address points at, hash-verified on the way out.

    ``store.get`` re-hashes what it read, so a citation cannot resolve to content that is not
    what the address names. That check is the difference between a citation and a link.
    """
    return store.get(address.blob_id)
