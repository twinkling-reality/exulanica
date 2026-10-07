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
    queue/<job sha256>/         job.json and requests/<request sha256>.json, then ready.json last
    claimed/<job sha256>.json   written by the session when it takes an entry
    done/<job sha256>.json      written when every item has ended and its outputs are published
    session/<session sha256>/   beat-<UTC stamp>.json every 30 s, and stop when the operator asks
    out/                        pieces, receipts and intermediates, published as a job's are

The mount refuses renames, so nothing is moved: each marker is a new file, written once. An entry
is ready only when ``ready.json`` exists, and ``ready.json`` names every other file of the entry
with its digest, so a half-copied entry is never taken.

Pure: no numpy, no network. :mod:`exulanica_appearance.assets.session` serves the queue on the
GPU machine; :mod:`exulanica_appearance.assets.nebius` fills it from this Mac.
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
    "ENTRY_PROFILE",
    "SESSION_PROFILE",
    "build_ready",
    "build_session",
    "charges_from_done",
    "entry_files",
    "read_entry",
    "read_session",
    "uncached_requests",
]

SESSION_PROFILE: Final = "exulanica.generated-asset-session/v1"
ENTRY_PROFILE: Final = "exulanica.generated-asset-queue-entry/v1"
CLAIM_PROFILE: Final = "exulanica.generated-asset-queue-claim/v1"
DONE_PROFILE: Final = "exulanica.generated-asset-queue-done/v1"
BEAT_PROFILE: Final = "exulanica.generated-asset-session-beat/v1"
#: The session ends after this long with no ready entry, unless its record states less.
IDLE_SECONDS_DEFAULT: Final = 600
#: A session's hard stop: one hour, the service's shortest timeout, unless root extends it.
STOP_SECONDS_MAXIMUM: Final = 3600
#: Bounds on what an entry may hold, so a queue cannot ask the session to read without end.
MAX_REQUESTS: Final = 64
MAX_FILE_BYTES: Final = 1 << 20
_INSTANT: Final = "%Y-%m-%dT%H:%M:%SZ"
_HEX: Final = re.compile(r"[0-9a-f]{64}")
_REQUEST_NAME: Final = re.compile(r"requests/([0-9a-f]{64})\.json")
_SESSION_KEYS: Final = ("code_sha256", "idle_seconds", "profile", "route", "stop_seconds")
_READY_KEYS: Final = ("files", "job_sha256", "profile", "queued_at")
_DONE_KEYS: Final = ("claimed_at", "ended_at", "job_sha256", "profile", "session_sha256")
_DONE_RAN: Final = ("items", "request_milliseconds", "results_ended_at")
#: Routes a session serves: A makes pieces; C, the creature route, joins when it lands.
SESSION_ROUTES: Final = frozenset({"A", "S"})


def instant(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime(_INSTANT)


def _instant(value: object, where: str) -> str:
    try:
        datetime.strptime(str(value), _INSTANT).replace(tzinfo=UTC)
    except ValueError as error:
        raise Refused(f"{where} is a UTC instant, YYYY-MM-DDTHH:MM:SSZ") from error
    if not isinstance(value, str):
        raise Refused(f"{where} is a UTC instant, YYYY-MM-DDTHH:MM:SSZ")
    return value


def build_session(
    *, route: str, code_sha256: str, idle_seconds: int = IDLE_SECONDS_DEFAULT, stop_seconds: int
) -> bytes:
    """A session record's canonical bytes; its sha256 names the session."""
    raw = canonical_bytes(
        {
            "code_sha256": code_sha256,
            "idle_seconds": idle_seconds,
            "profile": SESSION_PROFILE,
            "route": route,
            "stop_seconds": stop_seconds,
        }
    )
    read_session(raw)
    return raw


def read_session(raw: bytes) -> dict[str, Any]:
    """A session record, strictly: its route, the code archive it runs, its idle and hard stops."""
    document = exact_keys(parse_canonical(raw, "session"), _SESSION_KEYS, "session")
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


def build_ready(job_raw: bytes, requests: Sequence[bytes], queued_at: datetime) -> bytes:
    """``ready.json``: written last, it names every other file of the entry by its digest."""
    return canonical_bytes(
        {
            "files": {
                name: sha256_hex(raw) for name, raw in entry_files(job_raw, requests).items()
            },
            "job_sha256": sha256_hex(job_raw),
            "profile": ENTRY_PROFILE,
            "queued_at": instant(queued_at),
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
    if _HEX.fullmatch(directory.name) is None or directory.is_symlink():
        raise Refused("a queue entry's directory is named by its job's sha256")
    where = f"queue entry {directory.name[:12]}"
    document = exact_keys(
        parse_canonical(_read_file(directory / "ready.json", where), where), _READY_KEYS, where
    )
    if document["profile"] != ENTRY_PROFILE or document["job_sha256"] != directory.name:
        raise Refused(f"{where}: ready.json is {ENTRY_PROFILE} for the job its directory names")
    _instant(document["queued_at"], f"{where}: queued_at")
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
    directory: Path, *, route: str, code_sha256: str, budgets: PieceBudgets
) -> tuple[bytes, list[bytes]]:
    """A ready queue entry's job record and requests, every byte checked, or a refusal.

    The directory holds exactly the files ``ready.json`` names and nothing else; each has the
    digest named; the job is read by the job reader and each request by the request reader; the
    job is for this session's route and code archive; every item names a request the entry holds
    and every request is named by an item; no item starts from a cut-out, since a session makes
    its own concept pictures."""
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
    if sha256_hex(job_raw) != directory.name:
        raise Refused(f"{where}: job.json is not the job its directory names")
    job = read_job(job_raw)
    if job["route"] != route:
        raise Refused(f"{where}: the job takes route {job['route']}; this session serves {route}")
    if job["code_sha256"] != code_sha256:
        raise Refused(f"{where}: the job names another code archive than this session runs")
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


def read_done(raw: bytes) -> dict[str, Any]:
    """A done marker: the batch either ran (its items and each request's milliseconds) or was
    refused (the reason), never both."""
    document = parse_canonical(raw, "done")
    if not isinstance(document, dict):
        raise Refused("a done marker is an object")
    ran = set(_DONE_RAN) <= set(document)
    exact_keys(document, (*_DONE_KEYS, *(_DONE_RAN if ran else ("refused",))), "done marker")
    if document["profile"] != DONE_PROFILE:
        raise Refused(f"a done marker's profile is {DONE_PROFILE}")
    for key in ("job_sha256", "session_sha256"):
        if not is_sha256(document[key]):
            raise Refused(f"done marker: {key} is a sha256")
    for key in ("claimed_at", "ended_at"):
        _instant(document[key], f"done marker: {key}")
    if ran:
        spent = document["request_milliseconds"]
        if not isinstance(spent, dict) or not all(
            is_sha256(key) and is_count(value) for key, value in spent.items()
        ):
            raise Refused("done marker: request_milliseconds maps request digests to milliseconds")
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
