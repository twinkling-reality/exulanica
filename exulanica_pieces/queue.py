"""The generation queue a warm session serves: its layout in the bucket and its strict records.

One Serverless AI job, a *session*, loads its route's models once and serves batches from the
bucket until it has been idle too long, is told to stop, or reaches its stop. The bucket is the
only channel, and it carries data only: a queue entry is a job record and its request documents,
each named by its sha256, and the session reads them with the same strict readers a single job
does. No entry holds code, a command, a path or a file name of its own choosing: the session runs
only the code archive it was started with, refuses a job that names another, and reads nothing
outside the bucket's own directories below.

Layout, relative to the bucket's root (the job's mount, or a directory in tests)::

    runs/<session sha256>/      session.json, code.tar and job.sh, staged before the start
    queue/<entry id>/           job.json and requests/<request sha256>.json, then ready.json last
    claimed/<entry id>.json     written by the session when it takes an entry
    done/<entry id>.json        written when every item has ended and its outputs are published
    withdrawn/<entry id>.json   written by the product when it no longer wants an entry run
    session/<session sha256>/   beat-<UTC stamp>.json every 30 s, and stop when the operator asks
    out/                        pieces, receipts and intermediates, published as a job's are

An entry is named by its own id (32 lowercase hex: the product's batch id, or a uuid4 the
operator's tooling draws), never by its job's digest: two identical asks make the same job, and
each is its own entry with its own claim, done marker and charge. Its ``ready.json`` names the one
session that may take it and states ``not_after``: only that session takes the entry, only before
that instant and only while no withdrawal names it, so an entry its asker has given up on, or one
queued for another session on the same bucket, is never run. The session record carries a nonce,
so two sessions started with the same settings still have their own digests, heartbeats and
markers; the product registers no session without one.

The mount refuses renames, so nothing is moved: each marker is a new file, written once. An entry
is ready only when ``ready.json`` exists, and ``ready.json`` names every other file of the entry
with its digest, so a half-copied entry is never taken. A done marker names the receipts its entry
published, so a reader fetches those and lists nothing.

Version 1 of the entry, claim and done records named an entry by its job's digest; the session no
longer serves it, and :func:`read_done` still reads a version 1 done marker, as the run records of
the measured sessions hold them.

Pure: no numpy, no network, so the product reads it too. ``ml/appearance``'s session serves the
queue on the GPU machine and its tooling fills it from an operator's machine; the product's
generation worker (:mod:`exulanica.generation`) fills it and reads its markers over the bucket's S3
endpoint.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from exulanica_pieces.budgets import PieceBudgets
from exulanica_pieces.canonical import (
    Refused,
    canonical_bytes,
    exact_keys,
    is_count,
    is_sha256,
    parse_canonical,
    sha256_hex,
)
from exulanica_pieces.records import cache_key, read_job, read_receipt, read_request

__all__ = [
    "BEAT_PROFILE",
    "CLAIM_PROFILE",
    "DONE_PROFILE",
    "DONE_PROFILE_V1",
    "ENTRY_PROFILE",
    "SESSION_MANIFEST_PROFILE",
    "SESSION_PROFILE",
    "WITHDRAWN_PROFILE",
    "build_claim",
    "build_done",
    "build_ready",
    "build_session",
    "build_session_manifest",
    "build_withdrawn",
    "charges_from_done",
    "entry_files",
    "is_entry_id",
    "read_claim",
    "read_entry",
    "read_session",
    "read_session_manifest",
    "read_withdrawn",
    "uncached_requests",
]

SESSION_PROFILE: Final = "exulanica.generated-asset-session/v1"
ENTRY_PROFILE: Final = "exulanica.generated-asset-queue-entry/v2"
CLAIM_PROFILE: Final = "exulanica.generated-asset-queue-claim/v2"
DONE_PROFILE: Final = "exulanica.generated-asset-queue-done/v2"
#: The done marker of an entry named by its job's digest, as the measured sessions wrote it.
DONE_PROFILE_V1: Final = "exulanica.generated-asset-queue-done/v1"
WITHDRAWN_PROFILE: Final = "exulanica.generated-asset-queue-withdrawn/v1"
BEAT_PROFILE: Final = "exulanica.generated-asset-session-beat/v1"
#: What the product's register of a session needs beside the session record: the pinned models the
#: session runs and the container it runs in, written by the operator's tooling at record time.
SESSION_MANIFEST_PROFILE: Final = "exulanica.generated-asset-session-manifest/v1"
_MANIFEST_KEYS: Final = ("components_sha256", "container", "profile", "session_sha256")
_CONTAINER: Final = re.compile(r"sha256:[0-9a-f]{64}")
#: The session ends after this long with no ready entry, unless its record states less.
IDLE_SECONDS_DEFAULT: Final = 600
#: A session's hard stop: one hour, the service's shortest timeout, unless root extends it.
STOP_SECONDS_MAXIMUM: Final = 3600
#: Bounds on what an entry may hold, so a queue cannot ask the session to read without end.
MAX_REQUESTS: Final = 64
MAX_FILE_BYTES: Final = 1 << 20
_INSTANT: Final = "%Y-%m-%dT%H:%M:%SZ"
_HEX: Final = re.compile(r"[0-9a-f]{64}")
_ENTRY: Final = re.compile(r"[0-9a-f]{32}")
_REQUEST_NAME: Final = re.compile(r"requests/([0-9a-f]{64})\.json")
_SESSION_KEYS: Final = ("code_sha256", "idle_seconds", "profile", "route", "stop_seconds")
#: Added to the session record after the first sessions ran: absent, the record names no nonce.
_SESSION_OPTIONAL: Final = ("nonce",)
_READY_KEYS: Final = (
    "entry_id",
    "files",
    "job_sha256",
    "not_after",
    "profile",
    "queued_at",
    "session_sha256",
)
_CLAIM_KEYS: Final = ("at", "entry_id", "job_sha256", "profile", "session_sha256")
_WITHDRAWN_KEYS: Final = ("at", "entry_id", "profile")
_DONE_KEYS_V1: Final = ("claimed_at", "ended_at", "job_sha256", "profile", "session_sha256")
_DONE_KEYS: Final = (*_DONE_KEYS_V1, "entry_id")
_DONE_RAN_V1: Final = ("items", "request_milliseconds", "results_ended_at")
_DONE_RAN: Final = (*_DONE_RAN_V1, "receipts")
#: Routes a session serves: A makes pieces; C, the creature route, joins when it lands.
SESSION_ROUTES: Final = frozenset({"A", "S"})


def instant(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime(_INSTANT)


def is_entry_id(value: object) -> bool:
    """Whether ``value`` names a queue entry: 32 lowercase hex."""
    return isinstance(value, str) and _ENTRY.fullmatch(value) is not None


def _moment(text: str) -> datetime:
    return datetime.strptime(text, _INSTANT).replace(tzinfo=UTC)


def _instant(value: object, where: str) -> str:
    try:
        datetime.strptime(str(value), _INSTANT).replace(tzinfo=UTC)
    except ValueError as error:
        raise Refused(f"{where} is a UTC instant, YYYY-MM-DDTHH:MM:SSZ") from error
    if not isinstance(value, str):
        raise Refused(f"{where} is a UTC instant, YYYY-MM-DDTHH:MM:SSZ")
    return value


def build_session(
    *,
    route: str,
    code_sha256: str,
    idle_seconds: int = IDLE_SECONDS_DEFAULT,
    stop_seconds: int,
    nonce: str | None = None,
) -> bytes:
    """A session record's canonical bytes; its sha256 names the session. ``nonce`` (32 lowercase
    hex, drawn fresh for each start) keeps two sessions with the same settings apart."""
    document: dict[str, Any] = {
        "code_sha256": code_sha256,
        "idle_seconds": idle_seconds,
        "profile": SESSION_PROFILE,
        "route": route,
        "stop_seconds": stop_seconds,
    }
    if nonce is not None:
        document["nonce"] = nonce
    raw = canonical_bytes(document)
    read_session(raw)
    return raw


def read_session(raw: bytes) -> dict[str, Any]:
    """A session record, strictly: its route, the code archive it runs, its idle and hard stops,
    and its nonce when it has one."""
    parsed = parse_canonical(raw, "session")
    keys = _SESSION_KEYS + tuple(
        key for key in _SESSION_OPTIONAL if isinstance(parsed, dict) and key in parsed
    )
    document = exact_keys(parsed, keys, "session")
    if "nonce" in document and not is_entry_id(document["nonce"]):
        raise Refused("a session's nonce is 32 lowercase hex")
    if document["profile"] != SESSION_PROFILE:
        raise Refused(f"a session's profile is {SESSION_PROFILE}")
    if document["route"] not in SESSION_ROUTES:
        raise Refused(f"a session serves route {' or '.join(sorted(SESSION_ROUTES))}")
    if not is_sha256(document["code_sha256"]):
        raise Refused("a session names the sha256 of the code archive it runs")
    stop = document["stop_seconds"]
    if not is_count(stop, 60) or stop > STOP_SECONDS_MAXIMUM:
        raise Refused(f"a session's hard stop is 60 to {STOP_SECONDS_MAXIMUM} seconds")
    idle = document["idle_seconds"]
    if not is_count(idle, 10) or idle > stop:
        raise Refused("a session's idle stop is 10 seconds to its hard stop")
    return document


def entry_files(job_raw: bytes, requests: Sequence[bytes]) -> dict[str, bytes]:
    """The files of a queue entry by their names in it, ``ready.json`` excepted."""
    files = {"job.json": job_raw}
    for raw in requests:
        files[f"requests/{sha256_hex(raw)}.json"] = raw
    return files


def build_ready(
    entry_id: str,
    job_raw: bytes,
    requests: Sequence[bytes],
    *,
    session_sha256: str,
    queued_at: datetime,
    not_after: datetime,
) -> bytes:
    """``ready.json``: written last, it names the entry, every other file of it by its digest, the
    one session that may take it and the instant after which no session takes it."""
    if not is_entry_id(entry_id):
        raise Refused("an entry is named by 32 lowercase hex")
    if not is_sha256(session_sha256):
        raise Refused("an entry names its session by sha256")
    if not_after <= queued_at:
        raise Refused("an entry's not_after is after it was queued")
    return canonical_bytes(
        {
            "entry_id": entry_id,
            "files": {
                name: sha256_hex(raw) for name, raw in entry_files(job_raw, requests).items()
            },
            "job_sha256": sha256_hex(job_raw),
            "not_after": instant(not_after),
            "profile": ENTRY_PROFILE,
            "queued_at": instant(queued_at),
            "session_sha256": session_sha256,
        }
    )


def _read_file(path: Path, where: str) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise Refused(f"{where} is a plain file")
    if path.stat().st_size > MAX_FILE_BYTES:
        raise Refused(f"{where} is over {MAX_FILE_BYTES} bytes")
    return path.read_bytes()


def read_ready(directory: Path) -> dict[str, Any]:
    """An entry's ``ready.json``, strictly, checked against the directory it sits in."""
    if not is_entry_id(directory.name) or directory.is_symlink():
        raise Refused("a queue entry's directory is named by its entry id, 32 lowercase hex")
    where = f"queue entry {directory.name[:12]}"
    document = exact_keys(
        parse_canonical(_read_file(directory / "ready.json", where), where), _READY_KEYS, where
    )
    if document["profile"] != ENTRY_PROFILE or document["entry_id"] != directory.name:
        raise Refused(f"{where}: ready.json is {ENTRY_PROFILE} for the entry its directory names")
    if not is_sha256(document["job_sha256"]) or not is_sha256(document["session_sha256"]):
        raise Refused(f"{where}: ready.json names its job and its session by sha256")
    queued_at = _instant(document["queued_at"], f"{where}: queued_at")
    not_after = _instant(document["not_after"], f"{where}: not_after")
    if _moment(not_after) <= _moment(queued_at):
        raise Refused(f"{where}: not_after is after queued_at")
    files = document["files"]
    if not isinstance(files, dict) or "job.json" not in files:
        raise Refused(f"{where}: ready.json names job.json and its requests")
    for name, digest in files.items():
        match = _REQUEST_NAME.fullmatch(name)
        if name != "job.json" and (match is None or match.group(1) != digest):
            raise Refused(f"{where}: names a file other than job.json and requests/<sha256>.json")
        if not is_sha256(digest):
            raise Refused(f"{where}: names each file by its sha256")
    if len(files) - 1 > MAX_REQUESTS:
        raise Refused(f"{where}: holds at most {MAX_REQUESTS} requests")
    return document


def read_entry(
    directory: Path,
    *,
    route: str,
    code_sha256: str,
    components_sha256: str,
    budgets: PieceBudgets,
) -> tuple[bytes, list[bytes]]:
    """A ready queue entry's job record and requests, every byte checked, or a refusal.

    The directory holds exactly the files ``ready.json`` names and nothing else; each has the
    digest named; the job is read by the job reader and each request by the request reader; the
    job is for this session's route, code archive and the pinned models it loaded (so a receipt's
    ``components_sha256``, copied from the job, names the models that made it); every item names a
    request the entry holds and every request is named by an item; no item starts from a cut-out,
    since a session makes its own concept pictures."""
    ready = read_ready(directory)
    where = f"queue entry {directory.name[:12]}"
    present = {
        path.relative_to(directory).as_posix()
        for path in directory.rglob("*")
        if path.is_symlink() or not path.is_dir()
    }
    if present != set(ready["files"]) | {"ready.json"}:
        raise Refused(f"{where}: holds exactly the files ready.json names")
    contents = {}
    for name, digest in ready["files"].items():
        raw = _read_file(directory / name, f"{where}: {name}")
        if sha256_hex(raw) != digest:
            raise Refused(f"{where}: {name} is not the file ready.json names")
        contents[name] = raw
    job_raw = contents.pop("job.json")
    if sha256_hex(job_raw) != ready["job_sha256"]:
        raise Refused(f"{where}: job.json is not the job ready.json names")
    job = read_job(job_raw)
    if job["route"] != route:
        raise Refused(f"{where}: the job takes route {job['route']}; this session serves {route}")
    if job["code_sha256"] != code_sha256:
        raise Refused(f"{where}: the job names another code archive than this session runs")
    if job["components_sha256"] != components_sha256:
        raise Refused(f"{where}: the job names other models than this session loaded")
    requests = [contents[name] for name in sorted(contents)]
    for raw in requests:
        read_request(raw, budgets)
    named = {item["request_sha256"] for item in job["items"]}
    if named != {sha256_hex(raw) for raw in requests}:
        raise Refused(f"{where}: its items and its requests name each other exactly")
    if any("cutout_sha256" in item for item in job["items"]):
        raise Refused(f"{where}: a session makes its own concept pictures; no item names a cut-out")
    return job_raw, requests


def uncached_requests(
    requests: Sequence[bytes],
    *,
    components_sha256: str,
    postprocess_version: str,
    receipts: Mapping[str, bytes],
) -> list[bytes]:
    """The requests not every variant of which already has a receipt under the same cache key.

    ``receipts`` holds receipts already fetched, by their sha256; each is read against its request
    before it counts, so a piece is never generated twice and a stray file never stands in for one.
    """
    made: dict[str, set[int]] = {}
    by_digest = {sha256_hex(raw): raw for raw in requests}
    for raw in receipts.values():
        document = parse_canonical(raw, "receipt")
        request_raw = by_digest.get(document.get("request_sha256", ""))
        if request_raw is None:
            continue
        request = parse_canonical(request_raw, "request")
        read_receipt(raw, request)
        key = cache_key(
            document["request_sha256"],
            document["components_sha256"],
            document["postprocess"]["version"],
        )
        wanted = cache_key(document["request_sha256"], components_sha256, postprocess_version)
        if key == wanted:
            made.setdefault(document["request_sha256"], set()).add(document["variant"])
    kept = []
    for digest, raw in by_digest.items():
        variants = parse_canonical(raw, "request")["variants"]
        if made.get(digest, set()) != set(range(variants)):
            kept.append(raw)
    return kept


def build_withdrawn(entry_id: str, at: datetime) -> bytes:
    """A withdrawal: the product no longer wants the entry run, and no session claims it."""
    if not is_entry_id(entry_id):
        raise Refused("an entry is named by 32 lowercase hex")
    return canonical_bytes({"at": instant(at), "entry_id": entry_id, "profile": WITHDRAWN_PROFILE})


def read_withdrawn(raw: bytes, entry_id: str) -> dict[str, Any]:
    """A withdrawal, strictly, checked to name ``entry_id``."""
    document = exact_keys(parse_canonical(raw, "withdrawal"), _WITHDRAWN_KEYS, "withdrawal")
    if document["profile"] != WITHDRAWN_PROFILE or document["entry_id"] != entry_id:
        raise Refused(f"a withdrawal is {WITHDRAWN_PROFILE} naming its entry")
    _instant(document["at"], "withdrawal: at")
    return document


def build_claim(*, entry_id: str, job_sha256: str, session_sha256: str, at: datetime) -> bytes:
    """A claim marker: the session took the entry at ``at``."""
    raw = canonical_bytes(
        {
            "at": instant(at),
            "entry_id": entry_id,
            "job_sha256": job_sha256,
            "profile": CLAIM_PROFILE,
            "session_sha256": session_sha256,
        }
    )
    read_claim(raw)
    return raw


def read_claim(raw: bytes) -> dict[str, Any]:
    """A claim marker, strictly: the entry, its job and the session that took it, and when."""
    document = exact_keys(parse_canonical(raw, "claim marker"), _CLAIM_KEYS, "claim marker")
    if document["profile"] != CLAIM_PROFILE or not is_entry_id(document["entry_id"]):
        raise Refused(f"a claim marker is {CLAIM_PROFILE} naming an entry")
    for key in ("job_sha256", "session_sha256"):
        if not is_sha256(document[key]):
            raise Refused(f"claim marker: {key} is a sha256")
    _instant(document["at"], "claim marker: at")
    return document


def build_done(
    *,
    entry_id: str,
    job_sha256: str,
    session_sha256: str,
    claimed_at: str,
    ended_at: str,
    ran: Mapping[str, Any] | None = None,
    refused: str | None = None,
) -> bytes:
    """A done marker: the entry ran (``ran``: its items, each request's milliseconds, when its
    results ended and the receipts it published) or was refused (``refused``), never both."""
    if (ran is None) == (refused is None):
        raise Refused("a done marker states that its entry ran or that it was refused")
    document: dict[str, Any] = {
        "claimed_at": claimed_at,
        "ended_at": ended_at,
        "entry_id": entry_id,
        "job_sha256": job_sha256,
        "profile": DONE_PROFILE,
        "session_sha256": session_sha256,
    }
    if ran is not None:
        document.update(ran)
        document["receipts"] = sorted(set(document["receipts"]))
    else:
        document["refused"] = refused
    raw = canonical_bytes(document)
    read_done(raw)
    return raw


def read_done(raw: bytes) -> dict[str, Any]:
    """A done marker: the entry either ran (its items, each request's milliseconds and, from
    version 2, the receipts it published) or was refused (the reason), never both. A version 1
    marker, named by its job's digest, reads as it was written."""
    document = parse_canonical(raw, "done")
    if not isinstance(document, dict):
        raise Refused("a done marker is an object")
    first = document.get("profile") == DONE_PROFILE_V1
    if not first and document.get("profile") != DONE_PROFILE:
        raise Refused(f"a done marker's profile is {DONE_PROFILE}")
    keys, ran_keys = (_DONE_KEYS_V1, _DONE_RAN_V1) if first else (_DONE_KEYS, _DONE_RAN)
    ran = set(ran_keys) <= set(document)
    exact_keys(document, (*keys, *(ran_keys if ran else ("refused",))), "done marker")
    if not first and not is_entry_id(document["entry_id"]):
        raise Refused("done marker: entry_id is 32 lowercase hex")
    for key in ("job_sha256", "session_sha256"):
        if not is_sha256(document[key]):
            raise Refused(f"done marker: {key} is a sha256")
    for key in ("claimed_at", "ended_at"):
        _instant(document[key], f"done marker: {key}")
    if _moment(document["ended_at"]) < _moment(document["claimed_at"]):
        raise Refused("done marker: ended_at is not before claimed_at")
    if ran:
        spent = document["request_milliseconds"]
        if not isinstance(spent, dict) or not all(
            is_sha256(key) and is_count(value) for key, value in spent.items()
        ):
            raise Refused("done marker: request_milliseconds maps request digests to milliseconds")
        if not first:
            receipts = document["receipts"]
            if (
                not isinstance(receipts, list)
                or not all(is_sha256(item) for item in receipts)
                or receipts != sorted(set(receipts))
            ):
                raise Refused("done marker: receipts are the receipts' digests, sorted, each once")
    elif not isinstance(document["refused"], str) or not document["refused"]:
        raise Refused("done marker: refused states its reason")
    return document


def charges_from_done(
    done: Sequence[bytes], *, session_sha256: str, account: str
) -> list[dict[str, Any]]:
    """One charge line per request each batch of this session ran, in a GPU run record's shape
    (its cost is filled in by the record's builder at the record's rate)."""
    charges = []
    for raw in done:
        document = read_done(raw)
        if document["session_sha256"] != session_sha256 or "refused" in document:
            continue
        for request_sha256, milliseconds in sorted(document["request_milliseconds"].items()):
            charges.append(
                {
                    "account": account,
                    "job_sha256": document["job_sha256"],
                    "milliseconds": milliseconds,
                    "request_sha256": request_sha256,
                }
            )
    return sorted(charges, key=lambda charge: (charge["job_sha256"], charge["request_sha256"]))


def build_session_manifest(session_raw: bytes, *, components_sha256: str, container: str) -> bytes:
    """A session's manifest: the record it belongs to, its components and its container."""
    raw = canonical_bytes(
        {
            "components_sha256": components_sha256,
            "container": container,
            "profile": SESSION_MANIFEST_PROFILE,
            "session_sha256": sha256_hex(session_raw),
        }
    )
    read_session_manifest(raw, session_raw)
    return raw


def read_session_manifest(raw: bytes, session_raw: bytes) -> dict[str, Any]:
    """A session manifest, strictly, checked to belong to ``session_raw``."""
    read_session(session_raw)
    document = exact_keys(parse_canonical(raw, "session manifest"), _MANIFEST_KEYS, "manifest")
    if document["profile"] != SESSION_MANIFEST_PROFILE:
        raise Refused(f"a session manifest's profile is {SESSION_MANIFEST_PROFILE}")
    if document["session_sha256"] != sha256_hex(session_raw):
        raise Refused("the session manifest belongs to another session record")
    if not is_sha256(document["components_sha256"]):
        raise Refused("session manifest: components_sha256 is a sha256")
    if not isinstance(document["container"], str) or not _CONTAINER.fullmatch(
        document["container"]
    ):
        raise Refused("session manifest: container is sha256:<64 hex>")
    return document
