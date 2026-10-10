"""One sample town of a proposed specification, generated in a worker process of its own.

A drafted specification (:mod:`exulanica.selection.world_drafting`) is a preset and values; what a
person needs to judge it is what such a town holds: how many people live in it, how many vehicles
drive it, which streets and which kinds of premises it has. Those follow only from generating it,
so this module generates one town from the values, for a sample identity derived from them, and
counts what the town's own records state. Nothing is stored and no world is registered: the sample
is labelled a sample, because a town made from the same values draws its own identity and so its
own streets, and its counts differ.

**Off the request's thread.** Generation is pure Python: a sample took 1.66 s at the median and
5.55 s at the slowest over every point the specification allows
(``scripts/measure_world_drafting_samples.py``), and pure
Python on a request's thread holds the interpreter's lock, which slowed the server's slowest health
answer from at most 9 ms to 146 to 222 ms beside a half-second flight window
(docs/evaluation/2026-09-25-flight-bounds-v2.json). So a sample is computed in one spawned worker
process (:func:`~exulanica.world.episode_worker.worker_pool`), which ends itself when the server's
process is gone, and a request waits for it without holding the lock:

- **a time limit per sample** (:data:`SAMPLE_SECONDS`); a sample not done by then is answered as
  ``overran``, in words and without numbers, and is kept when it finishes, so asking again for
  the same values reads it;
- **a bound on samples waiting** (:data:`SAMPLES_WAITING`): past it a request is answered ``busy``
  rather than queued behind work it will not wait for;
- **kept by what they are made from** (:data:`SAMPLES_KEPT`): the preset, the values and the
  specification's digest, so one proposal read twice generates once;
- a worker that dies answers ``unavailable``, and the next sample starts a new process; one whose
  oldest sample runs past :data:`STUCK_SECONDS` is replaced and its process stopped, so a stuck
  sample never holds the queue or the server's shutdown.

What a sample states: the tiles it covers; its people by the residents rule its society would start
with (one per place in a home its premises offer); its vehicles by the traffic's fleet rule over the
bays its roads offer, or the traffic's refusal code where the roads derive none; its streets by
kind and its premises by use, each with the catalog's own label. A specification the generator
refuses is a sample ``refused`` with the refusal's code.
"""

from __future__ import annotations

import functools
import hashlib
import json
import logging
import threading
import time
from collections import Counter, OrderedDict
from collections.abc import Callable, Mapping
from concurrent.futures import CancelledError, Executor, Future
from concurrent.futures import TimeoutError as FutureTimeout
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass
from typing import Any, Final, Literal

from exulanica.movement.flight_episodes import watch_parent
from exulanica.world.episode_worker import worker_pool

__all__ = [
    "SAMPLES_KEPT",
    "SAMPLES_WAITING",
    "SAMPLE_SECONDS",
    "STUCK_SECONDS",
    "SampleWorker",
    "TownSample",
    "close_sample_worker",
    "compute_sample",
    "sample_worker",
    "sample_world_id",
]

#: The longest a request waits for its sample: twice the slowest sample measured over every point
#: the specification allows, rounded up to a whole 5 s, the rule the model manifest derives a
#: timeout by. scripts/measure_world_drafting_samples.py over the 48 points: p50 1.66 s, p95 4.76 s,
#: slowest 5.55 s (a three-tile town of 100 m blocks, which the generator refused after trying
#: every candidate).
SAMPLE_SECONDS: Final = 15.0
#: Samples waiting for the worker besides the one it computes. At the measured median of 1.66 s a
#: sample, the fourth waiting starts about 7 s after it was asked for, inside the time limit.
SAMPLES_WAITING: Final = 4
#: Samples kept by what they are made from: a page drafting and redrafting reads the same few.
SAMPLES_KEPT: Final = 32
#: How long a sample may run before its process is taken for stuck and replaced: four times the
#: time limit, 60 s, about eleven times the slowest sample measured (5.55 s). A request stops
#: waiting at the limit; this bounds how long a process that never finishes holds the queue.
STUCK_SECONDS: Final = 4 * SAMPLE_SECONDS

_log = logging.getLogger(__name__)

SampleStatus = Literal["sampled", "refused", "overran", "busy", "unavailable"]


@dataclass(frozen=True, slots=True)
class Counted:
    """How many of one kind a sample holds, with the catalog's word for the kind."""

    key: str
    label: str
    count: int


@dataclass(frozen=True, slots=True)
class TownSample:
    """What one sample town of a specification holds, or why there is none."""

    status: SampleStatus
    tiles: int | None = None
    people: int | None = None
    vehicles: int | None = None
    #: Why the sample's roads give no vehicles: the traffic's refusal code, or None.
    vehicles_refused: str | None = None
    streets: tuple[Counted, ...] = ()
    premises: tuple[Counted, ...] = ()
    buildings: int | None = None
    #: Why no town was generated, for a ``refused`` sample: the generator's refusal code.
    refused: str | None = None


def sample_world_id(preset: str, values: Mapping[str, int | str], specification_sha256: str) -> str:
    """The identity a sample is generated for: derived from what it is made from, so one proposal
    samples one town wherever it is read."""
    made_from = json.dumps(
        {"preset": preset, "values": dict(values), "specification": specification_sha256},
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"world:sample:{hashlib.sha256(made_from.encode()).hexdigest()[:32]}"


# -- in the worker process -----------------------------------------------------------------------


def _labels(catalog_id: str, grammar_version: int) -> dict[str, str]:
    from exulanica.grammar.grammars.city.catalogs import load_city_catalogs

    for catalog in load_city_catalogs(grammar_version=grammar_version):
        if catalog.catalog_id == catalog_id:
            return {entry.key: str(dict(entry.values)["label"]) for entry in catalog.entries}
    raise LookupError(f"city grammar version {grammar_version} reads no {catalog_id} catalog")


def _counted(counts: Counter[str], labels: Mapping[str, str]) -> list[dict[str, Any]]:
    return [
        {"key": key, "label": labels[key], "count": counts[key]}
        for key in sorted(counts, key=lambda key: (-counts[key], key))
    ]


def compute_sample(preset: str, values: dict[str, int | str], world_id: str) -> dict[str, Any]:
    """The worker's job: generate the town and count what its records state, as plain data."""
    from exulanica.grammar.errors import InvalidParameterError, InvalidRecordError
    from exulanica.grammar.grammars.city.premises import PremisesRecord
    from exulanica.grammar.grammars.city.streets import StreetSegmentRecord
    from exulanica.traffic.errors import UnsupportedNetworkError
    from exulanica.world.composers import GeneratedWorldRefused
    from exulanica.world.society_living import town_routine_of
    from exulanica.world.society_walking_surfaces import walking_surfaces_place
    from exulanica.world.specification_source import composed_town
    from exulanica.world.traffic_episodes import TrafficRefused, prepared, traffic_input
    from exulanica.world.world_recipes import SpecificationRefused, UnknownWorldRecipe

    try:
        composed = composed_town(preset, values, world_id)
    except (
        GeneratedWorldRefused,
        SpecificationRefused,
        UnknownWorldRecipe,
        InvalidParameterError,
        InvalidRecordError,
    ) as refused:
        return {"status": "refused", "refused": getattr(refused, "code", type(refused).__name__)}
    records = composed.records
    grammar_version = int(composed.receipt["grammar"]["grammar_version"])
    # Under the routine the town was made under, which its people are made under too.
    place = walking_surfaces_place(
        f"generated:{world_id}", records, town_routine_of(composed.receipt)
    )
    streets: dict[str, str] = {}
    uses: Counter[str] = Counter()
    buildings: set[str] = set()
    for record in records:
        if isinstance(record, StreetSegmentRecord):
            streets.setdefault(record.street_identity, record.hierarchy)
        elif isinstance(record, PremisesRecord):
            uses[record.use_class] += 1
            buildings.add(record.building_identity)
    sample: dict[str, Any] = {
        "status": "sampled",
        "tiles": len(composed.receipt["tiles"]),
        # The residents rule the town's society starts with: one person for each place in a home
        # that is lived in.
        "people": sum(d.get("resident_capacity", 0) for d in place["destinations"]),
        "streets": _counted(
            Counter(streets.values()), _labels("street-hierarchy", grammar_version)
        ),
        "premises": _counted(uses, _labels("use-class", grammar_version)),
        "buildings": len(buildings),
    }
    try:
        ready = prepared(
            traffic_input(
                world_id=world_id,
                version_id=composed.receipt_sha256,
                city_identity=composed.receipt["subject_identity"],
                grammar_version=grammar_version,
                records=records,
            )
        )
    except TrafficRefused as refused:
        sample["vehicles_refused"] = refused.code
    except UnsupportedNetworkError:
        # The code the traffic route answers a network its profile cannot simulate with.
        sample["vehicles_refused"] = "roads_unavailable"
    else:
        sample["vehicles"] = sum(ready.fleet.values())
    return sample


# -- in the server -------------------------------------------------------------------------------


def _sample(document: Mapping[str, Any]) -> TownSample:
    return TownSample(
        status=document["status"],
        tiles=document.get("tiles"),
        people=document.get("people"),
        vehicles=document.get("vehicles"),
        vehicles_refused=document.get("vehicles_refused"),
        streets=tuple(Counted(**row) for row in document.get("streets", ())),
        premises=tuple(Counted(**row) for row in document.get("premises", ())),
        buildings=document.get("buildings"),
        refused=document.get("refused"),
    )


def sample_process_pool() -> Executor:
    """The samples' own worker process, apart from the flight's and the traffic's."""
    return worker_pool(watch_parent)


@dataclass(frozen=True, slots=True)
class _Running:
    """A sample the worker is computing: its future, the pool it was handed to, and when."""

    future: Future[dict[str, Any]]
    executor: Executor
    started: float


def _terminate(executor: Executor) -> None:
    """Let a pool go without waiting on it, and stop any process it still runs.

    ``shutdown(wait=False)`` cancels what waits and returns, but a process computing a stuck sample
    would run on; the standard library states no public way to stop a pool's processes before
    Python 3.14 (``terminate_workers``), so each process the pool holds is terminated here.
    """
    # Read before shutdown, which forgets them.
    processes = list((getattr(executor, "_processes", None) or {}).values())
    executor.shutdown(wait=False, cancel_futures=True)
    for process in processes:
        if process.is_alive():
            process.terminate()


class SampleWorker:
    """Samples one worker computes, bounded and kept; safe to share between threads."""

    def __init__(
        self,
        executor: Callable[[], Executor] = sample_process_pool,
        *,
        job: Callable[[str, dict[str, int | str], str], dict[str, Any]] = compute_sample,
        seconds: float = SAMPLE_SECONDS,
        waiting: int = SAMPLES_WAITING,
        kept: int = SAMPLES_KEPT,
        stuck_seconds: float = STUCK_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._make = executor
        self._job = job
        self._seconds = seconds
        self._waiting = waiting
        self._kept = kept
        self._stuck = stuck_seconds
        self._clock = clock
        # Re-entrant: a future already done runs its callback in the thread that adds it.
        self._lock = threading.RLock()
        self._executor: Executor | None = None
        self._done: OrderedDict[str, TownSample] = OrderedDict()
        self._running: dict[str, _Running] = {}

    def sample(
        self, preset: str, values: Mapping[str, int | str], specification_sha256: str
    ) -> TownSample:
        """The sample town of ``preset`` with ``values``, or the status saying why there is none."""
        world_id = sample_world_id(preset, values, specification_sha256)
        with self._lock:
            found = self._done.get(world_id)
            if found is not None:
                self._done.move_to_end(world_id)
                return found
            running = self._running.get(world_id)
            if running is None:
                self._let_stuck_go()
                if len(self._running) > self._waiting:
                    return TownSample(status="busy")
                executor = self._executor
                try:
                    if executor is None:
                        executor = self._executor = self._make()
                    future = executor.submit(self._job, preset, dict(values), world_id)
                except (BrokenProcessPool, RuntimeError):
                    if executor is not None:
                        self._discard(executor)
                    return TownSample(status="unavailable")
                running = self._running[world_id] = _Running(future, executor, self._clock())
                future.add_done_callback(functools.partial(self._finished, world_id))
        try:
            return _sample(running.future.result(timeout=self._seconds))
        except FutureTimeout:
            return TownSample(status="overran")
        except (BrokenProcessPool, CancelledError):
            self._discard(running.executor)
            return TownSample(status="unavailable")
        except Exception:
            # A defect in the job, not a refusal: said at ERROR, and the person reads that no
            # sample could be made rather than a failed request.
            _log.exception("a specification sample failed")
            return TownSample(status="unavailable")

    def _let_stuck_go(self) -> None:
        """Replace the pool once its oldest sample has run past :data:`STUCK_SECONDS`: a stuck
        process would otherwise hold the queue full, and every later sample would be busy."""
        if not self._running:
            return
        oldest = min(self._running.values(), key=lambda running: running.started)
        if self._clock() - oldest.started > self._stuck:
            _log.error("a specification sample ran past %s s; its worker is replaced", self._stuck)
            self._discard(oldest.executor)

    def _discard(self, executor: Executor) -> None:
        """Let a broken or stuck pool go, if it is still this worker's, and forget what it ran;
        the next sample starts another."""
        with self._lock:
            if self._executor is executor:
                self._executor = None
            for world_id in [
                key for key, running in self._running.items() if running.executor is executor
            ]:
                del self._running[world_id]
        _terminate(executor)

    def _finished(self, world_id: str, future: Future[dict[str, Any]]) -> None:
        with self._lock:
            running = self._running.get(world_id)
            if running is not None and running.future is future:
                del self._running[world_id]
            if future.cancelled() or future.exception() is not None:
                return
            self._done[world_id] = _sample(future.result())
            while len(self._done) > self._kept:
                self._done.popitem(last=False)

    def close(self) -> None:
        """Stop the worker without waiting on a stuck sample; the server's lifespan calls this."""
        with self._lock:
            executor, self._executor = self._executor, None
            self._running.clear()
        if executor is not None:
            _terminate(executor)


#: This server's samples and the worker process computing them, started at the first sample.
_worker = SampleWorker()


def sample_worker() -> SampleWorker:
    """This server's sample worker."""
    return _worker


def close_sample_worker() -> None:
    """Stop the worker process; the server's lifespan calls this as it ends."""
    _worker.close()
