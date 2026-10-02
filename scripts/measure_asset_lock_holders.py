#!/usr/bin/env python3
"""Which holder of migration 0041's global asset read lock each refused guarded write met.

    .exulanica/bin/quiet-slot .venv/bin/python scripts/measure_asset_lock_holders.py \
        --workload scripts/runtime_capacity_workload.json --phases sharing \
        --ports 19440,19441,19442 --out RECORD.json

**The load is R1's, run by R1's harness.** ``scripts/measure_runtime_capacity.py`` is imported as a
library; its stack (a private PostgreSQL 18 with fsync on, the API as the image starts it, the
dedicated derivative worker with a scripted vision model) runs the workload's phases ``--phases``
names, in order, ``sharing`` by default: eight workspaces at the supported load beside eight towns
played at four times speed, each town's traffic read every five seconds. A ``mixed`` phase (the
supported load) and a sharing phase whose towns the playback worker's own process plays
(``"playback": "process"``) run the same way. The workload file is read as it is; only its ports
are replaced by ``--ports``, and the record states both. Each phase is sampled and joined on its
own, from the refusals the server logged while that phase ran.

**What this adds is observation, and no product change:**

* every process names itself to PostgreSQL through ``PGAPPNAME`` (``exulanica-api``,
  ``exulanica-derivative-worker``), which the product leaves unset;
* the private server writes each error with its millisecond time (UTC), process, application and
  SQLSTATE (``log_line_prefix``), so each write the barrier refused (40001, ``asset delivery in
  progress; retry mutation``, raised by ``tg_asset_read_mutation``) is in its log, with the
  statement that met it, and the log is kept before the server is removed;
* a sampler on a connection of its own reads ``pg_locks`` and ``pg_stat_activity`` for the
  barrier's key every ``--interval-ms`` (5 by default): each granted exclusive holder, each queued
  exclusive request and each shared holder, with its process, application, transaction start,
  state, wait and current statement. Its own cost is one more backend asking that many times a
  second, and the record states the interval it achieved.

**The join.** A refusal at server time ``t`` is attributed to the exclusive holder the samples on
either side of ``t`` name: ``covered`` when the last sample before and the first after name the
same transaction, ``adjacent`` when only one does; else to a queued exclusive request in those
samples (``queued``); else ``unseen``. A holding transaction is classed by its application and by
the statements sampled while it held the lock (see :func:`holder_class`). Each class's holds are
the spans between the first and last samples that saw them, so a hold shorter than the interval
can be missed or read short.

Timing belongs inside ``.exulanica/bin/quiet-slot`` in a window root declares; outside one a run is
design evidence only. Like the harness, a run refuses to start under the 70 percent idle gate.
"""

from __future__ import annotations

import argparse
import asyncio
import bisect
import datetime as dt
import hashlib
import json
import re
import shutil
import sys
import tempfile
import threading
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

ROOT = Path.cwd()
sys.path.insert(0, str(ROOT / "scripts"))

import measure_runtime_capacity as harness  # noqa: E402
import test_postgres  # noqa: E402

PROFILE: Final = "exulanica.asset-lock-holders/v1"
#: Migration 0041's barrier: ``pg_advisory_xact_lock(119622341)`` exclusive in ``asset_read_lock``,
#: ``pg_try_advisory_xact_lock_shared`` in every guarded table's trigger. A bigint key under 2^32
#: is listed by ``pg_locks`` with ``classid`` 0, ``objid`` the key and ``objsubid`` 1.
BARRIER_KEY: Final = 119622341
#: The message the barrier's trigger refuses a guarded write with (migration 0041).
REFUSAL_MESSAGE: Final = "asset delivery in progress; retry mutation"
API_APPLICATION: Final = "exulanica-api"
WORKER_APPLICATION: Final = "exulanica-derivative-worker"
PLAYBACK_APPLICATION: Final = "exulanica-playback-worker"
#: Every error line the server writes: time (UTC, milliseconds), process, application, SQLSTATE.
LOG_LINE_PREFIX: Final = "%m,%p,%a,%e,"
_LOG_LINE: Final = re.compile(
    r"^(?P<at>\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d{3}) UTC,(?P<pid>\d+),(?P<application>[^,]*),"
    r"(?P<sqlstate>[0-9A-Z]{5}),(?P<level>[A-Z]+):\s+(?P<text>.*)$"
)
_WRITTEN_TABLE: Final = re.compile(
    r"\b(?:insert\s+into|update|delete\s+from)\s+(?:only\s+)?\"?([a-z_][a-z0-9_]*)", re.IGNORECASE
)
#: One row a sample, holding every lock and request on the barrier's key as
#: [pid, mode, granted, application, transaction start, state, wait type, wait, statement].
_SAMPLE: Final = """
select clock_timestamp() as at, coalesce(json_agg(json_build_array(
         l.pid, l.mode, l.granted, a.application_name, a.xact_start, a.state, a.wait_event_type,
         a.wait_event, left(a.query, 200))), '[]'::json) as locks
  from pg_locks l join pg_stat_activity a on a.pid = l.pid
 where l.locktype = 'advisory' and l.classid = 0 and l.objid = %s and l.objsubid = 1
"""


# -- names, without changing the product ----------------------------------------------------------


def name_the_processes() -> None:
    """Give the API and the derivative worker their own ``PGAPPNAME`` through the harness's
    environment, so the server's log and ``pg_stat_activity`` say which process a backend serves."""
    environment = harness.Stack.environment
    start_worker = harness.Stack.start_worker

    def named_environment(self: harness.Stack, **extra: str) -> dict[str, str]:
        env = environment(self, **extra)
        env["PGAPPNAME"] = getattr(self, "_application", API_APPLICATION)
        return env

    def named_worker(self: harness.Stack, name: str = "capacity-worker") -> Any:
        self._application = WORKER_APPLICATION  # type: ignore[attr-defined]
        try:
            return start_worker(self, name)
        finally:
            self._application = API_APPLICATION  # type: ignore[attr-defined]

    harness.Stack.environment = named_environment  # type: ignore[method-assign]
    harness.Stack.start_worker = named_worker  # type: ignore[method-assign]
    start_playback = getattr(harness.Stack, "start_playback", None)
    if start_playback is not None:

        def named_playback(self: harness.Stack, **extra: str) -> Any:
            self._application = PLAYBACK_APPLICATION  # type: ignore[attr-defined]
            try:
                return start_playback(self, **extra)
            finally:
                self._application = API_APPLICATION  # type: ignore[attr-defined]

        harness.Stack.start_playback = named_playback  # type: ignore[attr-defined]
    test_postgres.SETTINGS.update(
        {
            "log_line_prefix": LOG_LINE_PREFIX,
            "log_timezone": "UTC",
            "log_min_error_statement": "error",
        }
    )


# -- the sampler ----------------------------------------------------------------------------------


@dataclass
class Sample:
    at: dt.datetime
    rows: list[list[Any]]


@dataclass
class LockSampler:
    """Reads the barrier's holders and requests every ``interval`` seconds on its own connection."""

    url: str
    interval: float
    samples: list[Sample] = field(default_factory=list)
    query_ms: list[float] = field(default_factory=list)
    _stop: threading.Event = field(default_factory=threading.Event)
    _thread: threading.Thread | None = None

    def __enter__(self) -> LockSampler:
        self._thread = threading.Thread(target=self._run, name="lock-sampler", daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(30)

    def _run(self) -> None:
        import psycopg

        with psycopg.connect(self.url, autocommit=True) as connection:
            while not self._stop.is_set():
                started = time.monotonic()
                at, locks = connection.execute(_SAMPLE, (BARRIER_KEY,)).fetchone()
                self.query_ms.append((time.monotonic() - started) * 1000)
                self.samples.append(Sample(at, locks))
                self._stop.wait(max(0.0, self.interval - (time.monotonic() - started)))


# -- the server's log -----------------------------------------------------------------------------


@dataclass(frozen=True)
class Refusal:
    at: dt.datetime
    pid: int
    application: str
    statement: str | None


def refusals_in(log: str) -> list[Refusal]:
    """Every write the barrier refused, from the server's log, with the statement that met it."""
    found: list[Refusal] = []
    pending: dict[int, int] = {}
    for line in log.splitlines():
        matched = _LOG_LINE.match(line)
        if matched is None:
            continue
        pid = int(matched["pid"])
        if matched["level"] == "ERROR" and matched["text"] == REFUSAL_MESSAGE:
            at = dt.datetime.strptime(matched["at"], "%Y-%m-%d %H:%M:%S.%f").replace(tzinfo=dt.UTC)
            pending[pid] = len(found)
            found.append(Refusal(at, pid, matched["application"], None))
        elif matched["level"] == "STATEMENT" and pid in pending:
            index = pending.pop(pid)
            found[index] = Refusal(
                found[index].at, pid, found[index].application, matched["text"].strip()
            )
    return found


def written_table(statement: str | None) -> str:
    if statement is None:
        return "unknown"
    matched = _WRITTEN_TABLE.search(statement)
    return matched[1].lower() if matched else "unknown"


# -- the join -------------------------------------------------------------------------------------


#: A transaction, as the samples name it: its backend and its start, as the server wrote it.
Transaction = tuple[int, str | None]


#: Tables only a society's work reads or writes while it holds the lock: its rows, its inputs, the
#: version and snapshot it is composed over, its control and clock, the reviewed assets it places.
_SOCIETY_TABLES: Final = (
    "world_society",
    "world_clock",
    "world_alternate_version",
    "world_structure_snapshot",
    "world_reviewed_asset",
    "world_crossing_occupancy",
)


def holder_class(application: str, statements: set[str]) -> str:
    """What a transaction that held the barrier exclusively was, by its process and statements.

    Society work is a playback round, or a request that creates, reads or advances a society; in
    the playback worker's own process it is only rounds. A hold whose sampled statements name none
    of the tables below is classed by its process alone.
    """
    text = " ".join(statements).lower()
    society = any(table in text for table in _SOCIETY_TABLES)
    if application == WORKER_APPLICATION:
        return "derivative worker final check"
    if application == PLAYBACK_APPLICATION:
        return "society work (playback process)" if society else "playback process other"
    if application != API_APPLICATION:
        return f"other process ({application or 'unnamed'})"
    if society:
        return "society work (api process)"
    if "baked_tile" in text:
        return "baked tile traffic"
    if "workspace_preparation" in text:
        return "prepared bytes"
    return "api other"


def join(samples: list[Sample], refusals: list[Refusal]) -> dict[str, Any]:
    """Attribute each refusal to a holder, and describe the holders and how long they held."""
    holders: dict[Transaction, dict[str, Any]] = {}
    held_samples = queued_samples = 0
    for sample in samples:
        held = queued = False
        for (
            pid,
            mode,
            granted,
            application,
            xact_start,
            _state,
            _wtype,
            _wait,
            query,
        ) in sample.rows:
            if mode != "ExclusiveLock":
                continue
            if not granted:
                queued = True
                continue
            held = True
            entry = holders.setdefault(
                (pid, xact_start),
                {"application": application or "", "first": sample.at, "statements": set()},
            )
            entry["last"] = sample.at
            if query:
                entry["statements"].add(query)
        held_samples += held
        queued_samples += queued
    for entry in holders.values():
        entry["class"] = holder_class(entry["application"], entry["statements"])

    times = [sample.at for sample in samples]

    def exclusive(sample: Sample, granted: bool) -> set[Transaction]:
        return {
            (row[0], row[4])
            for row in sample.rows
            if row[1] == "ExclusiveLock" and row[2] is granted
        }

    rows: list[dict[str, Any]] = []
    for refusal in refusals:
        index = bisect.bisect_right(times, refusal.at)
        before = samples[index - 1] if index > 0 else None
        after = samples[index] if index < len(samples) else None
        held_before = exclusive(before, True) if before else set()
        held_after = exclusive(after, True) if after else set()
        attribution, holder = "unseen", None
        if held_before & held_after:
            attribution, holder = "covered", sorted(held_before & held_after, key=str)[0]
        elif held_before or held_after:
            attribution, holder = "adjacent", sorted(held_before | held_after, key=str)[0]
        elif (before and exclusive(before, False)) or (after and exclusive(after, False)):
            attribution = "queued"
            queued = (exclusive(before, False) if before else set()) | (
                exclusive(after, False) if after else set()
            )
            holder = sorted(queued, key=str)[0]
        holder_entry = holders.get(holder) if holder is not None else None
        rows.append(
            {
                "at": refusal.at.isoformat(timespec="milliseconds"),
                "refused_application": refusal.application,
                "refused_table": written_table(refusal.statement),
                "attribution": attribution,
                "holder_class": (
                    holder_entry["class"]
                    if holder_entry is not None
                    else ("queued exclusive request" if attribution == "queued" else "unseen")
                ),
                "holder_pid": None if holder is None else holder[0],
                "sample_gap_ms": (
                    None
                    if before is None or after is None
                    else round((after.at - before.at).total_seconds() * 1000, 2)
                ),
            }
        )

    by_class: dict[str, list[float]] = defaultdict(list)
    for entry in holders.values():
        by_class[entry["class"]].append((entry["last"] - entry["first"]).total_seconds() * 1000)
    total = max(1, len(samples))
    return {
        "barrier": {
            "key": BARRIER_KEY,
            "samples_with_exclusive_held": held_samples,
            "samples_with_exclusive_queued": queued_samples,
            "share_held": round(held_samples / total, 4),
            "share_queued": round(queued_samples / total, 4),
        },
        "holders": {
            name: {"transactions": len(spans), "seen_span_ms": harness.spread(spans)}
            for name, spans in sorted(by_class.items())
        },
        "refusals": {
            "count": len(rows),
            "by_holder_class": dict(sorted(Counter(r["holder_class"] for r in rows).items())),
            "by_attribution": dict(sorted(Counter(r["attribution"] for r in rows).items())),
            "by_refused_table": dict(sorted(Counter(r["refused_table"] for r in rows).items())),
            "by_refused_application": dict(
                sorted(Counter(r["refused_application"] for r in rows).items())
            ),
            "each": rows,
        },
    }


# -- the run --------------------------------------------------------------------------------------


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def announce(path: Path, text: str) -> None:
    """One line in a coordination file, stamped with the local time it was written."""
    stamp = dt.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    with path.open("a") as handle:
        handle.write(f"{stamp} SEAM {text}\n")


def _phase_window(samples: list[Sample], refusals: list[Refusal]) -> list[Refusal]:
    """The refusals the server logged while a phase's sampler ran."""
    if not samples:
        return []
    first, last = samples[0].at, samples[-1].at
    return [refusal for refusal in refusals if first <= refusal.at <= last]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="measure_asset_lock_holders.py")
    parser.add_argument(
        "--workload", type=Path, default=ROOT / "scripts/runtime_capacity_workload.json"
    )
    parser.add_argument(
        "--phases", default="sharing", help="the workload's mixed or sharing phases, in order"
    )
    parser.add_argument("--ports", required=True, help="api,proxy,database, e.g. 19440,19441,19442")
    parser.add_argument("--interval-ms", type=float, default=5.0)
    parser.add_argument("--idle-gate", type=float, default=70.0)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--announce", type=Path, help="a coordination file the run's start and end are appended to"
    )
    args = parser.parse_args(argv)

    workload = json.loads(args.workload.read_text())
    if workload.get("profile") != harness.WORKLOAD_PROFILE:
        raise SystemExit(f"{args.workload} is not a {harness.WORKLOAD_PROFILE} file")
    phases = [name.strip() for name in args.phases.split(",") if name.strip()]
    for name in phases:
        spec = workload["phases"].get(name)
        if spec is None or spec.get("kind") not in ("mixed", "sharing") or spec.get("saturation"):
            raise SystemExit(f"the workload names no unsaturated mixed or sharing phase {name!r}")
    api, proxy, database = (int(port) for port in args.ports.split(","))
    file_ports = dict(workload["ports"])
    workload["ports"] = {"api": api, "proxy": proxy, "database": database}

    record: dict[str, Any] = {
        "profile": PROFILE,
        "started_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "tree": harness._assert_tree(),
        "instrument_sha256": _sha256(Path(__file__).resolve()),
        "harness_sha256": _sha256(ROOT / "scripts/measure_runtime_capacity.py"),
        "machine": harness._machine(),
        "workload_sha256": _sha256(args.workload),
        "workload_ports_in_file": file_ports,
        "ports_used": workload["ports"],
        "phases_requested": phases,
        "phase_specs": {name: workload["phases"][name] for name in phases},
        "sampler_interval_ms_target": args.interval_ms,
        "notes": [
            "Measured on one machine with every process local; latency excludes any network.",
            "The derivative worker's vision model is scripted (fixed sleep, fixed answer).",
            "PostgreSQL runs with fsync on, max_connections 100 and shared_buffers 128MB.",
            "Observation added: PGAPPNAME per process, the server's error log with "
            f"log_line_prefix {LOG_LINE_PREFIX!r}, and a pg_locks sampler on its own connection.",
        ],
    }
    record["idle_before_percent"] = harness.idle_share()
    record["load_before"] = harness.load_average()
    record["busiest_before"] = harness.other_heavy_processes()
    if (record["idle_before_percent"] or 0) < args.idle_gate:
        record["refused"] = (
            f"idle {record['idle_before_percent']}% is under the {args.idle_gate}% gate"
        )
        args.out.write_text(json.dumps(record, indent=1, sort_keys=True, default=str) + "\n")
        print(record["refused"], flush=True)
        return 3

    name_the_processes()
    run_dir = Path(tempfile.mkdtemp(prefix="asset-lock-holders-"))
    record["run_dir"] = str(run_dir)
    log_copy = args.out.with_suffix(".server.log.txt")
    if args.announce:
        announce(
            args.announce,
            f"LOCK HOLDERS RUN START, phases {','.join(phases)}, load {record['load_before']}",
        )
    measured: dict[str, tuple[dict[str, Any], LockSampler]] = {}
    try:
        with harness.stack(workload, run_dir) as built:
            for name in phases:
                spec = workload["phases"][name]
                print(f"phase {name} at {dt.datetime.now().strftime('%H:%M:%S')}", flush=True)
                with LockSampler(built.owner_url, args.interval_ms / 1000) as sampler:
                    started = time.monotonic()
                    if spec["kind"] == "sharing":
                        result = asyncio.run(harness.phase_sharing(built, spec, name))
                    else:
                        result = asyncio.run(harness.phase_mixed(built, spec, name))
                    result["wall_seconds"] = round(time.monotonic() - started, 1)
                    result["load_after"] = harness.load_average()
                measured[name] = (result, sampler)
            shutil.copyfile(built.server.log, log_copy)
        refusals = refusals_in(log_copy.read_text(errors="replace"))
        record["server_log"] = {"path": log_copy.name, "sha256": _sha256(log_copy)}
        record["refusals_logged"] = len(refusals)
        record["phases"] = {}
        for name, (result, sampler) in measured.items():
            intervals = [
                (later.at - earlier.at).total_seconds() * 1000
                for earlier, later in zip(sampler.samples, sampler.samples[1:], strict=False)
            ]
            record["phases"][name] = {
                "result": result,
                "sampler": {
                    "samples": len(sampler.samples),
                    "interval_ms": harness.spread(intervals),
                    "query_ms": harness.spread(sampler.query_ms),
                },
                **join(sampler.samples, _phase_window(sampler.samples, refusals)),
            }
        # The processes' own logs are kept beside the record; the run's directory, which holds
        # only this run's synthetic photographs and its private store, is then removed.
        record["process_logs"] = {}
        for name in ("api.log", "capacity-worker.log", "playback-worker.log"):
            if not (run_dir / name).exists():
                continue
            kept = args.out.with_suffix(f".{name.removesuffix('.log')}.log.txt")
            shutil.copyfile(run_dir / name, kept)
            record["process_logs"][name] = {"path": kept.name, "sha256": _sha256(kept)}
        shutil.rmtree(run_dir)
        record["run_dir_removed"] = True
    finally:
        record["idle_after_percent"] = harness.idle_share()
        record["load_after"] = harness.load_average()
        record["finished_at"] = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
        args.out.write_text(json.dumps(record, indent=1, sort_keys=True, default=str) + "\n")
        if args.announce:
            announce(
                args.announce,
                f"LOCK HOLDERS RUN END, load {record['load_after']}, record {args.out.name}",
            )
        print(f"wrote {args.out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
