"""Serve the generation queue from one warm session: models loaded once, batches taken in order.

The session is a Serverless AI job started from a staged session record
(:func:`exulanica_appearance.assets.queue.read_session`): its route, the sha256 of the code archive
it runs (``job.sh`` has already held the archive to that digest), its idle stop and its hard stop.
It loads the route's backend once and then, every poll:

1. ends if ``session/<id>/stop`` exists, or no entry has been ready for its idle stop;
2. takes the oldest ready entry nobody has claimed (by ``queued_at``, then its id) that names this
   session and whose ``not_after`` has not passed, unless its job's own stop would carry the
   session past its hard stop, in which case the entry waits; an entry for another session, past its
   ``not_after``, withdrawn (``withdrawn/<entry>.json``), whose ``ready.json`` does not read, or in a
   directory not named as an entry, is never claimed or run (none of these can be shown to be this
   session's to take);
3. writes ``claimed/<entry>.json``, reads the entry strictly, runs every item through the same
   runner a single job uses, publishes the outputs, and writes ``done/<entry>.json`` with each
   request's milliseconds and the receipts it published, so each request is charged what its
   items took. An entry the reader refuses is never run: its done marker states the refusal.

A heartbeat thread writes ``session/<id>/beat-<UTC stamp>.json`` every 30 seconds (a new file each
time, since the mount refuses renames and a file is written once) with the state, the job in hand
and the batches served. The hard stop is also enforced outside this loop, by ``timeout`` in
``job.sh``, and the service's own timeout is the backstop.

The product relies on one order: the session writes its last heartbeat, ``ended: <reason>``, only
after the loop has ended, so after every claim and done marker it will ever write, and each file
on the mount is written whole and closed before the next is begun. A worker that reads an ended
heartbeat and then finds no claim for an entry knows no claim will come.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from exulanica_pieces.budgets import read_budgets
from exulanica_pieces.canonical import Refused, canonical_bytes, parse_canonical, sha256_hex
from exulanica_pieces.records import read_job

from exulanica_appearance.assets.job import Backend, run_job
from exulanica_appearance.assets.queue import (
    BEAT_PROFILE,
    build_claim,
    build_done,
    instant,
    is_entry_id,
    read_entry,
    read_ready,
    read_session,
)

__all__ = ["Clock", "serve"]

BEAT_SECONDS: Final = 30
POLL_SECONDS: Final = 2


@dataclass
class Clock:
    """The session's time: a monotonic clock for its stops, the wall clock for its records, and a
    sleep; tests pass their own."""

    monotonic: Callable[[], float] = time.monotonic
    now: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))
    sleep: Callable[[float], None] = time.sleep


def _write_new(path: Path, data: bytes) -> None:
    """A plain write of a new file, as the mount allows: no rename, no mode, no times."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "xb") as handle:
        handle.write(data)


@dataclass
class _State:
    state: str = "loading"
    job: str | None = None
    served: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)


def _beat(root: Path, session: str, state: _State, started_at: str, clock: Clock) -> None:
    with state.lock:
        document = {
            "at": instant(clock.now()),
            "job_sha256": state.job,
            "profile": BEAT_PROFILE,
            "served": state.served,
            "session_sha256": session,
            "started_at": started_at,
            "state": state.state,
        }
    stamp = document["at"].replace(":", "").replace("-", "")
    path = root / "session" / session / f"beat-{stamp}.json"
    if not path.exists():
        _write_new(path, canonical_bytes(document))


@dataclass(frozen=True, slots=True)
class _Ready:
    queued_at: str
    entry_id: str
    job_sha256: str
    not_after: str


def _ready(root: Path, session_sha256: str) -> list[_Ready]:
    """This session's unclaimed, unwithdrawn entries, oldest first (by queued_at, then id). A
    directory not named as an entry, or whose ready.json does not read, is passed over: nothing in it
    shows it is this session's to take, so claiming it could take another session's entry."""
    queue = root / "queue"
    found = []
    for directory in sorted(queue.iterdir()) if queue.is_dir() else ():
        if not is_entry_id(directory.name) or not (directory / "ready.json").exists():
            continue
        if (root / "claimed" / f"{directory.name}.json").exists():
            continue
        if (root / "withdrawn" / f"{directory.name}.json").exists():
            continue
        try:
            ready = read_ready(directory)
        except Refused:
            continue
        if ready["session_sha256"] != session_sha256:
            continue
        found.append(
            _Ready(ready["queued_at"], directory.name, ready["job_sha256"], ready["not_after"])
        )
    return sorted(found, key=lambda entry: (entry.queued_at, entry.entry_id))


def serve(
    *,
    root: Path,
    session_raw: bytes,
    code_sha256: str,
    components_sha256: str,
    backend: Backend,
    repository: Path,
    work: Path,
    publish: Callable[[], None],
    clock: Clock | None = None,
    poll_seconds: float = POLL_SECONDS,
    beat_seconds: float = BEAT_SECONDS,
) -> dict[str, Any]:
    """Serve the queue under ``root`` until a stop; returns why it ended and what it served.

    ``code_sha256`` is the digest ``job.sh`` checked the running archive against; a session
    record naming another is refused before anything is served. ``components_sha256`` is the digest
    of the pinned models the backend loaded; an entry whose job names others is refused. ``work`` is the machine's own
    disk, where outputs are written before ``publish`` copies them to ``root/out``."""
    clock = clock or Clock()
    session = read_session(session_raw)
    session_sha256 = sha256_hex(session_raw)
    if session["code_sha256"] != code_sha256:
        raise Refused("the session record names another code archive than the one running")
    if backend.route != session["route"]:
        raise Refused(
            f"the session serves route {session['route']}; the backend is {backend.route}"
        )
    budgets = read_budgets(repository)
    started = clock.monotonic()
    started_at = instant(clock.now())
    state = _State(state="idle")
    stopped = threading.Event()

    def beats() -> None:
        while not stopped.wait(beat_seconds):
            _beat(root, session_sha256, state, started_at, clock)

    _beat(root, session_sha256, state, started_at, clock)
    beater = threading.Thread(target=beats, name="heartbeat", daemon=True)
    beater.start()
    last_work = started
    served: list[dict[str, Any]] = []
    reason = "idle"
    try:
        while True:
            if (root / "session" / session_sha256 / "stop").exists():
                reason = "stop"
                break
            elapsed = clock.monotonic() - started
            now = instant(clock.now())
            chosen = None
            for entry in _ready(root, session_sha256):
                if now > entry.not_after:
                    continue
                stop = _job_stop(root / "queue" / entry.entry_id)
                if stop is None or elapsed + stop <= session["stop_seconds"]:
                    chosen = entry
                    break
            if chosen is None:
                if clock.monotonic() - last_work >= session["idle_seconds"]:
                    reason = "idle"
                    break
                if elapsed >= session["stop_seconds"]:
                    reason = "hard_stop"
                    break
                clock.sleep(poll_seconds)
                continue
            # A withdrawal written after the listing still stops the claim.
            if (root / "withdrawn" / f"{chosen.entry_id}.json").exists():
                continue
            with state.lock:
                state.state, state.job = "working", chosen.job_sha256
            served.append(
                _serve_one(
                    root=root,
                    entry=chosen,
                    session=session,
                    session_sha256=session_sha256,
                    components_sha256=components_sha256,
                    backend=backend,
                    repository=repository,
                    work=work,
                    publish=publish,
                    budgets=budgets,
                    clock=clock,
                )
            )
            with state.lock:
                state.state, state.job, state.served = "idle", None, len(served)
            last_work = clock.monotonic()
    finally:
        stopped.set()
        beater.join(timeout=5)
        with state.lock:
            state.state, state.job = f"ended: {reason}", None
        _beat(root, session_sha256, state, started_at, clock)
    return {"reason": reason, "served": served, "session_sha256": session_sha256}


def _job_stop(directory: Path) -> int | None:
    """The stop a ready entry's job states, or None when it does not read (refused when taken)."""
    try:
        return int(read_job((directory / "job.json").read_bytes())["stop"]["stop_at_seconds"])
    except (Refused, OSError, KeyError, ValueError):
        return None


def _serve_one(
    *,
    root: Path,
    entry: _Ready,
    session: dict[str, Any],
    session_sha256: str,
    components_sha256: str,
    backend: Backend,
    repository: Path,
    work: Path,
    publish: Callable[[], None],
    budgets: Any,
    clock: Clock,
) -> dict[str, Any]:
    claimed = clock.now()
    claimed_at = instant(claimed)
    job_sha256 = entry.job_sha256
    _write_new(
        root / "claimed" / f"{entry.entry_id}.json",
        build_claim(
            entry_id=entry.entry_id,
            job_sha256=job_sha256,
            session_sha256=session_sha256,
            at=claimed,
        ),
    )
    marker = {
        "entry_id": entry.entry_id,
        "job_sha256": job_sha256,
        "session_sha256": session_sha256,
        "claimed_at": claimed_at,
    }
    try:
        job_raw, requests = read_entry(
            root / "queue" / entry.entry_id,
            route=session["route"],
            code_sha256=session["code_sha256"],
            components_sha256=components_sha256,
            budgets=budgets,
        )
    except Refused as refusal:
        raw = build_done(**marker, ended_at=instant(clock.now()), refused=str(refusal))
    else:
        results = run_job(
            job_raw=job_raw,
            requests=requests,
            backend=backend,
            repository=repository,
            out=work,
            clock=clock.monotonic,
        )
        publish()
        milliseconds: dict[str, int] = {}
        for item in results["items"]:
            key = item["request_sha256"]
            milliseconds[key] = milliseconds.get(key, 0) + item["milliseconds"]
        raw = build_done(
            **marker,
            ended_at=instant(clock.now()),
            ran={
                "items": {
                    "made": sum("piece" in item for item in results["items"]),
                    "total": len(results["items"]),
                    "within": sum(bool(item.get("within")) for item in results["items"]),
                },
                "receipts": [item["receipt"] for item in results["items"] if "receipt" in item],
                "request_milliseconds": milliseconds,
                "results_ended_at": results["ended_at"],
            },
        )
    _write_new(root / "done" / f"{entry.entry_id}.json", raw)
    return parse_canonical(raw, "done")
