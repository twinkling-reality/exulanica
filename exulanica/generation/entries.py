"""Queue entries, markers, heartbeats and outputs, as the worker writes and reads them.

The layout and the records are :mod:`exulanica_pieces.queue`'s, the ones the warm session reads and
writes. Every entry is named by its own id, the batch's (:func:`entry_id`), so two identical asks
are two entries, each with its own claim, done marker and charge. The worker:

- writes an entry's job and request documents (:func:`write_files`), then ``ready.json`` last
  (:func:`write_ready`), so the session never takes a half-written entry, and ``ready.json`` names
  the one session that may take it and the instant after which none does;
- withdraws an entry it no longer wants run (:func:`write_withdrawn`), which a session checks
  before it claims;
- reads the claim and done markers the session writes for an entry (:func:`claim`, :func:`done`),
  each checked to name that entry, its job and the session it went to, and to be dated no earlier
  than the entry was queued (less the clocks' allowed difference);
- reads the session's latest heartbeat (:func:`latest_beat`), checked to be that session's;
- reads an entry's outputs (:func:`outputs`): the receipts its done marker names and nothing else,
  each read strictly against the request it names, and each receipt's piece, whose bytes must hash
  to the digest the receipt states.

A marker or output that does not read raises :class:`EntryRefused` with a code, which the worker
ends the batch with; nothing here deletes, and nothing read is trusted further than its digest and
its reader.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final

from exulanica_pieces.canonical import Refused, parse_canonical, sha256_hex
from exulanica_pieces.queue import (
    BEAT_PROFILE,
    DONE_PROFILE,
    build_ready,
    build_withdrawn,
    entry_files,
    read_claim,
    read_done,
)
from exulanica_pieces.records import read_receipt

from exulanica.generation.bucket import GenerationBucket, GenerationBucketRefused

__all__ = [
    "CLOCK_ALLOWANCE",
    "EntryRefused",
    "Output",
    "claim",
    "done",
    "entry_id",
    "latest_beat",
    "outputs",
    "write_files",
    "write_ready",
    "write_withdrawn",
]

_INSTANT: Final = "%Y-%m-%dT%H:%M:%SZ"
#: How far a session's clock and this server's may differ. A marker dated more than this before its
#: entry was queued is not that entry's; a deadline is acted on only this long after it passes.
CLOCK_ALLOWANCE: Final = timedelta(minutes=2)


class EntryRefused(ValueError):
    """A marker or output of an entry that does not read as that entry's, with a code."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code


@dataclass(frozen=True, slots=True)
class Output:
    """One item a session made: its receipt (bytes and the read document) and its piece's bytes."""

    receipt_sha256: str
    receipt: bytes
    document: Mapping[str, Any]
    piece_sha256: str
    piece: bytes

    @property
    def request_sha256(self) -> str:
        return str(self.document["request_sha256"])

    @property
    def variant(self) -> int:
        return int(self.document["variant"])

    @property
    def within(self) -> bool:
        return bool(self.document["verdict"]["within"])


def entry_id(piece_batch_id: uuid.UUID) -> str:
    """The name of a batch's entry in the bucket: the batch's id as 32 lowercase hex."""
    return piece_batch_id.hex


def _at(text: str) -> datetime:
    return datetime.strptime(text, _INSTANT).replace(tzinfo=UTC)


def write_files(
    bucket: GenerationBucket, entry: str, job_raw: bytes, requests: Sequence[bytes]
) -> None:
    """Write an entry's job and request documents. No session takes the entry before
    :func:`write_ready`."""
    prefix = f"queue/{entry}/"
    for name, raw in entry_files(job_raw, requests).items():
        bucket.put(prefix + name, raw)


def write_ready(
    bucket: GenerationBucket,
    entry: str,
    job_raw: bytes,
    requests: Sequence[bytes],
    *,
    session_sha256: str,
    queued_at: datetime,
    not_after: datetime,
) -> None:
    """Write an entry's ``ready.json``, last: from here the session ``session_sha256``, and no
    other, may take it until ``not_after``. Written once, bounded (the worker holds the
    workspace's lock while it writes it): a write that fails may still have reached the bucket, and
    the worker follows the batch either way."""
    ready = build_ready(
        entry,
        job_raw,
        requests,
        session_sha256=session_sha256,
        queued_at=queued_at,
        not_after=not_after,
    )
    bucket.put_once(f"queue/{entry}/ready.json", ready)


def _get(bucket: GenerationBucket, key: str, code: str) -> bytes | None:
    try:
        return bucket.get(key)
    except GenerationBucketRefused as refused:
        raise EntryRefused(code, str(refused)) from refused


def _check(
    document: Mapping[str, Any],
    *,
    entry: str,
    job_sha256: str,
    session_sha256: str,
    queued_at: datetime,
    instant: str,
    what: str,
) -> None:
    if (
        document.get("entry_id") != entry
        or document["job_sha256"] != job_sha256
        or document["session_sha256"] != session_sha256
    ):
        raise EntryRefused(
            "marker_not_this_entry", f"the {what} names another entry, job or session"
        )
    if _at(document[instant]) < queued_at - CLOCK_ALLOWANCE:
        raise EntryRefused(
            "marker_not_this_entry", f"the {what} is dated before its entry was queued"
        )


def claim(
    bucket: GenerationBucket,
    entry: str,
    *,
    job_sha256: str,
    session_sha256: str,
    queued_at: datetime,
) -> dict[str, Any] | None:
    """The entry's claim marker, strictly, or None before a session took it."""
    raw = _get(bucket, f"claimed/{entry}.json", "marker_unreadable")
    if raw is None:
        return None
    try:
        document = read_claim(raw)
    except Refused as refused:
        raise EntryRefused("marker_unreadable", str(refused)) from refused
    _check(
        document,
        entry=entry,
        job_sha256=job_sha256,
        session_sha256=session_sha256,
        queued_at=queued_at,
        instant="at",
        what="claim marker",
    )
    return document


def done(
    bucket: GenerationBucket,
    entry: str,
    *,
    job_sha256: str,
    session_sha256: str,
    queued_at: datetime,
) -> dict[str, Any] | None:
    """The entry's done marker, strictly, or None while it runs."""
    raw = _get(bucket, f"done/{entry}.json", "marker_unreadable")
    if raw is None:
        return None
    try:
        document = read_done(raw)
    except Refused as refused:
        raise EntryRefused("marker_unreadable", str(refused)) from refused
    if document["profile"] != DONE_PROFILE:
        raise EntryRefused("marker_unreadable", f"an entry's done marker is {DONE_PROFILE}")
    _check(
        document,
        entry=entry,
        job_sha256=job_sha256,
        session_sha256=session_sha256,
        queued_at=queued_at,
        instant="claimed_at",
        what="done marker",
    )
    return document


def latest_beat(bucket: GenerationBucket, session_sha256: str) -> dict[str, Any] | None:
    """The session's latest heartbeat, or None before its first."""
    beats = [key for key in bucket.keys(f"session/{session_sha256}/") if "/beat-" in key]
    if not beats:
        return None
    raw = _get(bucket, max(beats), "heartbeat_unreadable")
    if raw is None:
        return None
    document = parse_canonical(raw, "heartbeat")
    if (
        not isinstance(document, dict)
        or document.get("profile") != BEAT_PROFILE
        or document.get("session_sha256") != session_sha256
    ):
        raise Refused("the latest heartbeat is not this session's")
    _at(str(document.get("at")))
    return document


def outputs(
    bucket: GenerationBucket,
    marker: Mapping[str, Any],
    requests: Mapping[str, Mapping[str, Any]],
) -> list[Output]:
    """The outputs a done marker names: each receipt it lists, read against the request it names
    (from ``requests``, by digest) and naming the marker's job, and each receipt's piece, checked
    against the digest the receipt states. Any that does not is :class:`EntryRefused`
    ``outputs_unreadable``."""
    found: list[Output] = []
    for receipt_sha256 in marker["receipts"]:
        where = f"receipt {receipt_sha256[:12]}"
        raw = _get(bucket, f"out/receipts/{receipt_sha256}.json", "outputs_unreadable")
        if raw is None or sha256_hex(raw) != receipt_sha256:
            raise EntryRefused("outputs_unreadable", f"{where} is missing or not its bytes")
        try:
            header = parse_canonical(raw, "receipt")
            if not isinstance(header, dict) or header.get("job_sha256") != marker["job_sha256"]:
                raise Refused(f"{where} is not of this entry's job")
            request = requests.get(str(header.get("request_sha256")))
            if request is None:
                raise Refused(f"{where} names a request this entry did not hold")
            document = read_receipt(raw, request)
        except Refused as refused:
            raise EntryRefused("outputs_unreadable", str(refused)) from refused
        piece_sha256 = document["output"]["sha256"]
        piece = _get(bucket, f"out/pieces/{piece_sha256}.glb", "outputs_unreadable")
        if piece is None or sha256_hex(piece) != piece_sha256:
            raise EntryRefused(
                "outputs_unreadable", f"the piece of {where} is missing or not its bytes"
            )
        found.append(
            Output(
                receipt_sha256=receipt_sha256,
                receipt=raw,
                document=document,
                piece_sha256=piece_sha256,
                piece=piece,
            )
        )
    keys = [(output.request_sha256, output.variant) for output in found]
    if len(set(keys)) != len(keys):
        raise EntryRefused("outputs_unreadable", "two receipts name one request's variant")
    return sorted(found, key=lambda output: (output.request_sha256, output.variant))


def write_withdrawn(bucket: GenerationBucket, entry: str, at: datetime) -> None:
    """Withdraw an entry: a session that has not claimed it never does."""
    bucket.put(f"withdrawn/{entry}.json", build_withdrawn(entry, at))
