"""The spending witness: what a ledger committed, kept where a database restore does not reach.

A restored database holds an older ledger, and an older ledger holds less spending than was done:
without something outside it, a restore would hand the spent allowance back. The witness is that
something. One record per witnessed authority holds the ledger's sequence and head digest, what it
has committed (for the authority and for each workspace grant), its current terms and every
revocation, and every write that changes what is committed updates it, in this order:

1. take the authority's witness lock (before any database lock, in every path);
2. read the record, and hand it to the database function, which compares it with the ledger
   under the authority's row lock and refuses when they disagree;
3. write the record the function returns, *unconfirmed*, before the database commits, keeping
   what the record before it held (``prior``);
4. commit, then write the same record again, *confirmed*, without the prior.

A commit that fails after step 3 leaves the witness one step ahead, unconfirmed, and naming the
ledger's head as its previous one: the database reads that as a step that never happened, and the
next record is built from the prior. A confirmed step the ledger lacks, or a witness further ahead,
means the database was restored behind it (``ledger_behind_witness``), and a restore's
reconciliation counts the prior of an unconfirmed record as well, since its step may never have
committed. A witness behind or beside the ledger, a missing or unreadable one, or a copy
(``state: copy``) suspends the authority until an operator reauthorizes it.

THE DIRECTORY. The directory carries a marker (``witness-directory.json``) holding its own
identifier, written once by the operator commands, never by a spending process. Every witness a
process reads names that identifier, and the database records, per authority, the directory its
witness is kept in. A process whose directory has no marker, or another one, cannot prove it reads
the authority's witness: it is refused alone (``witness_directory_mismatch``) and suspends nobody.

What this does not cover, stated so no deployment infers it: the lock is a POSIX advisory lock, so
every process that spends under an authority must share the directory on one host (a local
filesystem, not NFS). A witness restored together with the database from the same backup agrees
with it and protects nothing. The one ambiguity left is a restore to exactly the ledger's state
before its last step, made after that step committed and before it was confirmed; that step's
liability, at most one attempt's reservation, is not carried forward.
"""

from __future__ import annotations

import collections
import contextlib
import datetime as dt
import errno
import fcntl
import hashlib
import json
import os
import threading
import time
import uuid
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Protocol

from exulanica.canonical import canonical_json
from exulanica.errors import ExulanicaError

__all__ = [
    "RECORD_PROFILE",
    "FileSpendingWitness",
    "SpendingWitness",
    "WitnessHandle",
    "WitnessUnavailable",
    "advance_record",
]

#: The envelope every record sits in, as the restore checkpoint's does.
ENVELOPE_PROFILE: Final = "exulanica.digest-bound-record/v1"
RECORD_PROFILE: Final = "exulanica.spending-witness/v1"
#: The marker naming a witness directory, and what it holds.
DIRECTORY_MARKER: Final = "witness-directory.json"
DIRECTORY_PROFILE: Final = "exulanica.spending-witness-directory/v1"
_LIVE: Final = "live"
_COPY: Final = "copy"

#: What an unconfirmed record keeps of the record its step was taken from.
_PRIOR_FIELDS: Final = (
    "epoch",
    "sequence",
    "head_sha256",
    "committed_usd",
    "committed_calls",
    "terms",
    "grants",
    "revoked",
)

#: How long a process waits for another to finish its step before it refuses to spend.
DEFAULT_LOCK_TIMEOUT_S: Final = 10.0
#: How often a process asks again for a file lock another process holds: first quickly, since a
#: step holds it for milliseconds, then less often. The file lock is not first come, first served
#: between processes; within one, :class:`_TurnLock` is.
_POLL_FIRST_S: Final = 0.0005
_POLL_MOST_S: Final = 0.004


class WitnessUnavailable(ExulanicaError):
    """The witness could not be locked, read or written just now. Nothing was spent."""


class WitnessHandle(Protocol):
    """One authority's witness, held under its lock for one step."""

    @property
    def document(self) -> dict[str, Any] | None:
        """What the database compares with its ledger: the record and whether it is live, a
        copy, absent or unreadable; None when this process has no witness at all."""
        ...

    @property
    def record(self) -> dict[str, Any] | None:
        """The live record as read, or None."""
        ...

    def write(
        self, record: Mapping[str, Any], *, confirmed: bool, as_copy: bool = False
    ) -> None: ...


class SpendingWitness(Protocol):
    """Where every authority's witness is kept."""

    def hold(self, authority_id: uuid.UUID) -> contextlib.AbstractContextManager[WitnessHandle]: ...

    def ensure_directory_id(self) -> uuid.UUID:
        """The directory's identifier, written into its marker first where it has none. For the
        operator commands only: a spending process never names a directory."""
        ...


@dataclass
class _FileHandle:
    witness: FileSpendingWitness
    authority_id: uuid.UUID
    status: str
    body: dict[str, Any] | None
    #: The directory's identifier from its marker, or None where it has no readable one.
    directory_id: uuid.UUID | None = None

    @property
    def document(self) -> dict[str, Any] | None:
        # The envelope's state and the directory's marker are what they are, whatever a record
        # holds under the same names.
        named = {"directory_id": None if self.directory_id is None else str(self.directory_id)}
        if self.status in ("absent", "unreadable"):
            return {"status": self.status, **named}
        assert self.body is not None
        return {**self.body, "status": self.status, **named}

    @property
    def record(self) -> dict[str, Any] | None:
        return self.body if self.status == _LIVE else None

    def write(self, record: Mapping[str, Any], *, confirmed: bool, as_copy: bool = False) -> None:
        """Write ``record`` as this authority's witness: live, or with ``as_copy`` still a copy,
        which a step reconciling a restore from a copy writes until its commit is confirmed."""
        body = {**record, "confirmed": confirmed, "profile": RECORD_PROFILE}
        body.pop("status", None)
        body.pop("directory_id", None)
        if confirmed:
            # Committed: the step it was taken from no longer matters.
            body.pop("prior", None)
        if body.get("authority_id") != str(self.authority_id):
            raise ValueError("a witness record names the authority it is kept for")
        state = _COPY if as_copy else _LIVE
        self.witness._write(self.authority_id, body, state=state)
        self.status = state
        self.body = body


class _TurnLock:
    """A lock the threads of one process take in the order they asked for it.

    ``threading.Lock`` is not: a thread that releases it and asks again at once usually wins it
    back, so a thread spending in a loop can hold out an operator's command, or another request,
    until it times out. Here a release hands the lock to the longest waiter directly.
    """

    def __init__(self) -> None:
        self._guard = threading.Lock()
        self._held = False
        self._waiting: collections.deque[threading.Event] = collections.deque()

    def acquire(self, timeout: float) -> bool:
        with self._guard:
            if not self._held and not self._waiting:
                self._held = True
                return True
            turn = threading.Event()
            self._waiting.append(turn)
        if turn.wait(timeout):
            return True
        with self._guard:
            if turn.is_set():
                # Handed over just as the wait ended: it is this thread's now.
                return True
            self._waiting.remove(turn)
            return False

    def release(self) -> None:
        with self._guard:
            if self._waiting:
                self._waiting.popleft().set()
            else:
                self._held = False


class FileSpendingWitness:
    """Every authority's witness as a file in one directory, one lock file beside each."""

    def __init__(self, directory: Path, *, lock_timeout_s: float = DEFAULT_LOCK_TIMEOUT_S) -> None:
        if lock_timeout_s <= 0:
            raise ValueError("a witness lock timeout is positive")
        self.directory = Path(directory)
        self.lock_timeout_s = lock_timeout_s
        # Threads of one process queue here first, in turn, so the file lock is contended
        # between processes rather than between every thread of each.
        self._threads: dict[uuid.UUID, _TurnLock] = {}
        self._guard = threading.Lock()

    def __repr__(self) -> str:
        return f"FileSpendingWitness({str(self.directory)!r})"

    def path(self, authority_id: uuid.UUID) -> Path:
        return self.directory / f"{authority_id}.witness.json"

    def _lock_path(self, authority_id: uuid.UUID) -> Path:
        return self.directory / f"{authority_id}.lock"

    def _thread_lock(self, authority_id: uuid.UUID) -> _TurnLock:
        with self._guard:
            return self._threads.setdefault(authority_id, _TurnLock())

    @contextlib.contextmanager
    def hold(self, authority_id: uuid.UUID) -> Iterator[_FileHandle]:
        """The authority's witness, locked against every other step of every process."""
        deadline = time.monotonic() + self.lock_timeout_s
        thread_lock = self._thread_lock(authority_id)
        if not thread_lock.acquire(timeout=self.lock_timeout_s):
            raise WitnessUnavailable("another step of this process holds the witness")
        try:
            try:
                self.directory.mkdir(parents=True, exist_ok=True)
                descriptor = os.open(self._lock_path(authority_id), os.O_RDWR | os.O_CREAT, 0o600)
            except OSError as exc:
                raise WitnessUnavailable(
                    f"the witness directory cannot be used: {exc.strerror}"
                ) from exc
            try:
                pause = _POLL_FIRST_S
                while True:
                    try:
                        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except OSError as exc:
                        if exc.errno not in (errno.EWOULDBLOCK, errno.EAGAIN):
                            raise WitnessUnavailable(
                                f"the witness cannot be locked: {exc.strerror}"
                            ) from exc
                        if time.monotonic() >= deadline:
                            raise WitnessUnavailable(
                                "another process held the witness past the lock timeout"
                            ) from exc
                        time.sleep(pause)
                        pause = min(pause * 2, _POLL_MOST_S)
                status, body = self._read(authority_id)
                yield _FileHandle(self, authority_id, status, body, self.directory_id())
            finally:
                os.close(descriptor)
        finally:
            thread_lock.release()

    def _read(self, authority_id: uuid.UUID) -> tuple[str, dict[str, Any] | None]:
        path = self.path(authority_id)
        try:
            raw = path.read_bytes()
        except FileNotFoundError:
            return "absent", None
        except OSError as exc:
            raise WitnessUnavailable(f"the witness cannot be read: {exc.strerror}") from exc
        try:
            envelope = json.loads(raw)
            record = envelope["record"]
            state = envelope["state"]
            if (
                envelope.get("profile") != ENVELOPE_PROFILE
                or state not in (_LIVE, _COPY)
                or not isinstance(record, dict)
                or record.get("profile") != RECORD_PROFILE
                or envelope.get("record_sha256")
                != hashlib.sha256(canonical_json(record)).hexdigest()
            ):
                return "unreadable", None
        except (ValueError, KeyError, TypeError):
            return "unreadable", None
        return state, record

    def _write(self, authority_id: uuid.UUID, record: Mapping[str, Any], *, state: str) -> None:
        body = dict(record)
        body["written_at"] = dt.datetime.now(dt.UTC).isoformat()
        envelope = {
            "profile": ENVELOPE_PROFILE,
            "state": state,
            "record": body,
            "record_sha256": hashlib.sha256(canonical_json(body)).hexdigest(),
        }
        path = self.path(authority_id)
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(canonical_json(envelope))
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, path)
                directory = os.open(path.parent, os.O_RDONLY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
            finally:
                temporary.unlink(missing_ok=True)
        except OSError as exc:
            raise WitnessUnavailable(f"the witness cannot be written: {exc.strerror}") from exc

    def _marker_path(self) -> Path:
        return self.directory / DIRECTORY_MARKER

    def directory_id(self) -> uuid.UUID | None:
        """The identifier this directory's marker holds, or None where it has none or it cannot be
        read: a directory that cannot name itself proves nothing."""
        try:
            marker = json.loads(self._marker_path().read_bytes())
            if marker.get("profile") != DIRECTORY_PROFILE:
                return None
            return uuid.UUID(str(marker["directory_id"]))
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            return None

    def ensure_directory_id(self) -> uuid.UUID:
        """This directory's identifier, writing its marker first where it has none. Never
        replaces a marker that is present: a directory keeps its name."""
        present = self.directory_id()
        if present is not None:
            return present
        if self._marker_path().exists():
            raise WitnessUnavailable(
                f"{DIRECTORY_MARKER} in the witness directory cannot be read; it is not replaced"
            )
        marker = {
            "profile": DIRECTORY_PROFILE,
            "directory_id": str(uuid.uuid4()),
            "created_at": dt.datetime.now(dt.UTC).isoformat(),
        }
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            temporary = self.directory / f".{DIRECTORY_MARKER}.{uuid.uuid4().hex}.tmp"
            with open(temporary, "xb") as stream:
                stream.write(canonical_json(marker))
                stream.flush()
                os.fsync(stream.fileno())
            try:
                # A link either takes the name or finds it taken: two operators at once agree.
                os.link(temporary, self._marker_path())
            except FileExistsError:
                pass
            finally:
                temporary.unlink(missing_ok=True)
            directory = os.open(self.directory, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        except OSError as exc:
            raise WitnessUnavailable(
                f"the witness directory's marker cannot be written: {exc.strerror}"
            ) from exc
        written = self.directory_id()
        if written is None:
            raise WitnessUnavailable("the witness directory's marker cannot be read back")
        return written

    def install_copy(self, authority_id: uuid.UUID, source: Path) -> None:
        """Install a retained copy of a witness as the authority's, marked a copy.

        For recovery from custody when the live witness was lost with its host: the authority
        stays suspended (``witness_copy_only``) until an operator reauthorizes it. A copy ahead of
        a restored ledger is carried by the restore's reconciliation first, and a reauthorization
        discards one that is ahead or diverged only when told to. Refuses to replace a live witness
        that is present.
        """
        envelope = json.loads(Path(source).read_bytes())
        record = envelope.get("record") if isinstance(envelope, dict) else None
        if (
            not isinstance(record, dict)
            or record.get("profile") != RECORD_PROFILE
            or record.get("authority_id") != str(authority_id)
            or envelope.get("record_sha256") != hashlib.sha256(canonical_json(record)).hexdigest()
        ):
            raise WitnessUnavailable("the copy is not a witness record of this authority")
        with self.hold(authority_id) as held:
            if held.status == _LIVE:
                raise WitnessUnavailable("a live witness is present; a copy never replaces it")
            self._write(authority_id, record, state=_COPY)


def advance_record(
    previous: Mapping[str, Any] | None, advance: Mapping[str, Any]
) -> dict[str, Any]:
    """The witness record after a step, from the record before it and the database's advance.

    ``advance`` holds the authority as it now stands, and the workspace grants and the revocation
    the step touched; one marked ``full`` holds every grant and every revocation, and replaces them.
    The record carries what the record its step was taken from held (``prior``), for as long as it
    is unconfirmed.
    """
    authority = dict(advance["authority"])
    full = bool(advance.get("full"))
    base = _taken_from(previous, authority)
    grants: dict[str, dict[str, Any]] = {}
    revoked: set[str] = set()
    if base is not None and not full:
        grants = {entry["key"]: dict(entry) for entry in base.get("grants", ())}
        revoked = set(base.get("revoked", ()))
    for entry in advance.get("grants") or ():
        grants[entry["key"]] = dict(entry)
    key = advance.get("revoked")
    if isinstance(key, str):
        revoked.add(key)
    elif isinstance(key, list):
        revoked.update(str(item) for item in key)
    record: dict[str, Any] = {
        "profile": RECORD_PROFILE,
        **authority,
        "grants": [grants[name] for name in sorted(grants)],
        "revoked": sorted(revoked),
    }
    if base is not None:
        record["prior"] = {name: base[name] for name in _PRIOR_FIELDS if name in base}
    return record


def _taken_from(
    previous: Mapping[str, Any] | None, authority: Mapping[str, Any]
) -> Mapping[str, Any] | None:
    """The record a step was taken from: the one before it, unless that one is an unconfirmed
    step at the sequence this step now takes, whose commit never happened. Then it is that
    record's own prior, where it kept one."""
    if previous is None:
        return None
    if previous.get("confirmed") is False and previous.get("sequence") == authority.get("sequence"):
        prior = previous.get("prior")
        if isinstance(prior, Mapping):
            return prior
    return previous
