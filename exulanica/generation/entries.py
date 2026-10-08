"""Queue entries, markers, heartbeats and outputs, as the worker writes and reads them.

The layout and the records are :mod:`exulanica_pieces.queue`'s, the ones the warm session reads and
writes. The worker:

- writes an entry's job and request documents, then ``ready.json`` last, so the session never takes
  a half-written entry (:func:`queue_entry`);
- reads the claim and done markers the session writes for a job (:func:`claimed`, :func:`done`),
  each checked to name the job and the session it is asked about;
- reads the session's latest heartbeat (:func:`latest_beat`), checked to be that session's;
- reads a job's outputs (:func:`outputs`): every receipt that names the job, read strictly against
  the request it names, and its piece, whose bytes must hash to the digest the receipt states.

Nothing here deletes, and nothing read is trusted further than its digest and its reader.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

from exulanica_pieces.canonical import Refused, parse_canonical, sha256_hex
from exulanica_pieces.queue import (
    BEAT_PROFILE,
    CLAIM_PROFILE,
    build_ready,
    entry_files,
    read_done,
)
from exulanica_pieces.records import read_receipt

from exulanica.generation.bucket import GenerationBucket, GenerationBucketRefused

__all__ = [
    "Output",
    "claimed",
    "done",
    "latest_beat",
    "outputs",
    "queue_entry",
]

_INSTANT: Final = "%Y-%m-%dT%H:%M:%SZ"


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


def queue_entry(
    bucket: GenerationBucket, job_raw: bytes, requests: Sequence[bytes], queued_at: datetime
) -> str:
    """Write an entry: its files first, ``ready.json`` last. Returns the job's digest."""
    job_sha256 = sha256_hex(job_raw)
    prefix = f"queue/{job_sha256}/"
    for name, raw in entry_files(job_raw, requests).items():
        bucket.put(prefix + name, raw)
    bucket.put(prefix + "ready.json", build_ready(job_raw, requests, queued_at))
    return job_sha256


def _marker(bucket: GenerationBucket, key: str, where: str) -> bytes | None:
    try:
        return bucket.get(key)
    except GenerationBucketRefused as refused:
        raise Refused(f"{where}: {refused}") from refused


def claimed(bucket: GenerationBucket, job_sha256: str, session_sha256: str) -> bool:
    """Whether the session has taken the job's entry (its claim marker names both)."""
    raw = _marker(bucket, f"claimed/{job_sha256}.json", "claim marker")
    if raw is None:
        return False
    document = parse_canonical(raw, "claim marker")
    if (
        not isinstance(document, dict)
        or document.get("profile") != CLAIM_PROFILE
        or document.get("job_sha256") != job_sha256
        or document.get("session_sha256") != session_sha256
    ):
        raise Refused("the claim marker is not this session's claim of this job")
    return True


def done(bucket: GenerationBucket, job_sha256: str, session_sha256: str) -> dict[str, Any] | None:
    """The job's done marker, strictly, or None while it runs."""
    raw = _marker(bucket, f"done/{job_sha256}.json", "done marker")
    if raw is None:
        return None
    document = read_done(raw)
    if document["job_sha256"] != job_sha256 or document["session_sha256"] != session_sha256:
        raise Refused("the done marker is not this session's end of this job")
    return document


def latest_beat(bucket: GenerationBucket, session_sha256: str) -> dict[str, Any] | None:
    """The session's latest heartbeat, or None before its first."""
    beats = [key for key in bucket.keys(f"session/{session_sha256}/") if "/beat-" in key]
    if not beats:
        return None
    raw = _marker(bucket, max(beats), "heartbeat")
    if raw is None:
        return None
    document = parse_canonical(raw, "heartbeat")
    if (
        not isinstance(document, dict)
        or document.get("profile") != BEAT_PROFILE
        or document.get("session_sha256") != session_sha256
    ):
        raise Refused("the latest heartbeat is not this session's")
    datetime.strptime(str(document.get("at")), _INSTANT).replace(tzinfo=UTC)
    return document


def outputs(
    bucket: GenerationBucket, job_sha256: str, requests: Mapping[str, Mapping[str, Any]]
) -> list[Output]:
    """Every output the job published, each receipt read against the request it names (from
    ``requests``, by digest) and each piece checked against the digest its receipt states. A
    receipt for another job is passed over; one naming a request the job did not hold is refused."""
    found: list[Output] = []
    for key in bucket.keys("out/receipts/"):
        name = key.rsplit("/", 1)[-1]
        if not name.endswith(".json"):
            continue
        raw = _marker(bucket, key, "receipt")
        if raw is None or sha256_hex(raw) != name.removesuffix(".json"):
            raise Refused(f"receipt {name[:12]} is not the bytes its name states")
        header = parse_canonical(raw, "receipt")
        if not isinstance(header, dict) or header.get("job_sha256") != job_sha256:
            continue
        request = requests.get(str(header.get("request_sha256")))
        if request is None:
            raise Refused(f"receipt {name[:12]} names a request this job did not hold")
        document = read_receipt(raw, request)
        piece_sha256 = document["output"]["sha256"]
        piece = _marker(bucket, f"out/pieces/{piece_sha256}.glb", "piece")
        if piece is None or sha256_hex(piece) != piece_sha256:
            raise Refused(f"the piece of receipt {name[:12]} is missing or not its bytes")
        found.append(
            Output(
                receipt_sha256=sha256_hex(raw),
                receipt=raw,
                document=document,
                piece_sha256=piece_sha256,
                piece=piece,
            )
        )
    return sorted(found, key=lambda output: (output.request_sha256, output.variant))
