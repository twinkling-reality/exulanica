"""A movement module's episodes, computed in a worker process and kept for windows cut from them.

A movement step is pure Python, and Python runs one thread at a time: computed on a request's
thread, a window holds the interpreter's lock, and every other request the server is answering
waits for it. Measured on a release server, one cold flight window of 24 flyers (about half a
second) slowed the slowest health answer beside it from at most 9 ms to 146 to 222 ms
(docs/evaluation/2026-09-25-flight-bounds-v2.json). So a server computes a module whose windows are
cut from whole episodes here instead, one :class:`EpisodeWorker` per module, each with its own
process:

- **one worker process**, started by the first read (the standard library's process pool, one
  process, spawned), computes whole episodes with the module's ``compute`` job and hands them back
  packed; a request waiting for one holds no lock. The worker ends itself when the server's process
  is gone, however that ended;
- **episodes wait here, not in the pool**: the pool is handed one episode at a time, so which
  episode goes next is decided when the worker is free. An episode a read is waiting for goes
  before one asked for ahead of need, and among either the one asked for first goes first. At most
  ``queue_limit`` episodes wait; one asked for ahead of need is not queued past it, and one a read
  needs pushes out the oldest of those, or, with none to push out, is refused;
- **an edit replaces an input**: a read names its version's edit sequence, and a later one for the
  same world version supersedes every earlier input of it. Episodes of a superseded input still
  waiting are dropped, reads waiting on them refused, its kept episodes let go, and one being
  computed when it was superseded is handed to whoever waits for it and not kept;
- **episodes are kept** by the input digest and episode, the ``limit`` most recently used; they are
  computed bytes keyed by content and grant nothing, so a request still reads its world through
  the database before any episode is cut for it;
- **the next episode is asked for ahead of need** whenever a window is served, so a page reading
  ahead of its clock waits only for its first read;
- **one deadline a read**: a read is refused with the module's unavailable refusal when the
  episodes it needs are not all done ``wait_seconds`` after it began, however many it spans; a
  worker that dies refuses the reads waiting on it the same way, and the next read starts a new
  process.

A request's own work is its window cut from the packed episodes it spans, by the module's
``window`` function. What a module supplies is an :class:`EpisodeModule`; the flight's binding is
:mod:`exulanica.world.flight_worker` and the roads' :mod:`exulanica.world.traffic_host`.
"""

from __future__ import annotations

import itertools
import multiprocessing
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from concurrent.futures import CancelledError, Executor, Future, ProcessPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass, field
from typing import Any, Final, Generic, Protocol, TypeVar

__all__ = [
    "EPISODE_LIMIT",
    "QUEUE_LIMIT",
    "WAIT_SECONDS",
    "EpisodeModule",
    "EpisodeWorker",
    "Key",
    "Line",
    "worker_pool",
]

#: Episodes kept at once. A page reads the episode its clock is in and the next one; eight hold
#: that pair for four worlds, or four inputs of one world being edited, at about 2.9 MB an episode
#: of 24 flyers (3,000 steps of ten integers of four bytes each).
EPISODE_LIMIT: Final = 8
#: Episodes waiting for the worker at once, besides the one it computes. A cold 24-flyer episode
#: took 0.46 to 1.33 s (docs/evaluation/2026-09-26-flight-worker-v3.json and the two records
#: before it), so eight waiting are at most about 11 s of the worker's time, well inside a read's
#: :data:`WAIT_SECONDS`.
QUEUE_LIMIT: Final = 8
#: The longest a read waits for the episodes it needs, all of them, before it is refused. A request
#: holds one of the server's request threads while it waits, so the wait is bounded.
WAIT_SECONDS: Final = 30.0
#: How many wire forms are kept, by input digest, so queueing an episode does not rebuild one.
_WIRE_LIMIT: Final = 16

#: A world version whose inputs follow one another as it is edited: (world id, version id).
Line = tuple[str, str]
Key = tuple[str, int]

Input = TypeVar("Input")
Packed = TypeVar("Packed")


class EpisodeModule(Protocol[Input, Packed]):
    """What one movement module's episodes need from the worker, and nothing more."""

    #: What the module moves, as its refusals name it: "flight" makes "the flight's worker".
    subject: str
    #: The steps one episode holds.
    episode_steps: int
    #: The job the worker process runs: ``compute(wire, episode) -> packed episode``. A module-level
    #: function, so the spawned process imports it by name.
    compute: Callable[[dict[str, Any], int], Packed]
    #: The refusal a read its worker could not serve receives, made from a detail sentence.
    refusal: type[Exception]

    def check(self, from_step: int, steps: int) -> None:
        """Refuse a window the module does not serve."""

    def digest(self, value: Input) -> str:
        """The input's content digest, which keys its episodes."""

    def line(self, value: Input) -> Line:
        """The world version the input belongs to."""

    def wire(self, value: Input) -> dict[str, Any]:
        """Plain data the worker process rebuilds the input from."""

    def window(
        self, value: Input, episodes: dict[int, Packed], from_step: int, steps: int
    ) -> dict[str, Any]:
        """The window of ``steps`` steps from ``from_step``, cut from the episodes it spans."""


def worker_pool(initializer: Callable[[], None]) -> Executor:
    """One spawned worker process: nothing of the server's own state is inherited by it, and
    ``initializer`` runs in it first, which is where it starts watching for the server to go."""
    return ProcessPoolExecutor(
        max_workers=1,
        mp_context=multiprocessing.get_context("spawn"),
        initializer=initializer,
    )


@dataclass(eq=False)
class _Job(Generic[Packed]):
    """One episode waiting for the worker or being computed, and who waits for it."""

    key: Key
    line: Line
    wire: dict[str, Any]
    #: Resolved when the worker answers, or when the episode is dropped or refused.
    future: Future[Packed] = field(default_factory=Future)
    #: Reads waiting for it now; none means it was asked for ahead of need.
    waiters: int = 0
    order: int = 0


class EpisodeWorker(Generic[Input, Packed]):
    """Episodes one worker computes, kept and cut into windows; safe to share between threads."""

    def __init__(
        self,
        module: EpisodeModule[Input, Packed],
        executor: Callable[[], Executor],
        *,
        limit: int = EPISODE_LIMIT,
        queue_limit: int = QUEUE_LIMIT,
        wait_seconds: float = WAIT_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._module = module
        self._make = executor
        self._limit = limit
        self._queue_limit = queue_limit
        self._wait = wait_seconds
        self._clock = clock
        self._name = f"the {module.subject}'s worker"
        self._lock = threading.RLock()
        self._executor: Executor | None = None
        self._done: OrderedDict[Key, Packed] = OrderedDict()
        self._queued: dict[Key, _Job[Packed]] = {}
        self._running: _Job[Packed] | None = None
        #: For each world version, the edit sequence and input digest of its latest input.
        self._current: dict[Line, tuple[int, str]] = {}
        #: Which world version each input digest seen belongs to.
        self._lines: dict[str, Line] = {}
        self._order = itertools.count()
        self._wires: OrderedDict[str, dict[str, Any]] = OrderedDict()

    def window(
        self, value: Input, from_step: int, steps: int, *, generation: int | None = None
    ) -> dict[str, Any]:
        """The window of ``steps`` steps from ``from_step``, cut from the episodes it spans; the
        episode after the last is asked for ahead of need.

        ``generation`` is the edit sequence of the version ``value`` was composed from: an input
        of a later one for the same world version supersedes this one, and this one supersedes
        earlier ones. Without it, no input supersedes another.
        """
        module = self._module
        module.check(from_step, steps)
        deadline = self._clock() + self._wait
        episode_steps = module.episode_steps
        first, last = from_step // episode_steps, (from_step + steps - 1) // episode_steps
        line = module.line(value)
        digest = module.digest(value)
        found: dict[int, Packed | _Job[Packed]] = {}
        try:
            with self._lock:
                self._lines[digest] = line
                self._supersede(digest, line, generation)
                for episode in range(first, last + 1):
                    found[episode] = self._need(value, digest, line, episode)
                self._ahead(value, digest, line, last + 1)
                self._dispatch()
                self._prune()
            episodes = {episode: self._wait_for(item, deadline) for episode, item in found.items()}
        finally:
            with self._lock:
                for item in found.values():
                    if isinstance(item, _Job):
                        item.waiters -= 1
        return module.window(value, episodes, from_step, steps)

    def held(self) -> list[Key]:
        """The episodes kept, least recently used first."""
        with self._lock:
            return list(self._done)

    def waiting(self) -> list[tuple[Key, int]]:
        """The episodes waiting for the worker, each with how many reads wait for it, in the order
        the worker would take them."""
        with self._lock:
            return [(job.key, job.waiters) for job in self._by_turn()]

    def ask(self, function: Callable[[], Any]) -> Any:
        """What ``function`` answers in the worker process: a diagnostic, such as which process
        computes and what it has imported."""
        future, executor = self._submit(function)
        try:
            return future.result(timeout=self._wait)
        except (BrokenProcessPool, CancelledError, FutureTimeout) as error:
            with self._lock:
                self._discard(executor)
            raise self._module.refusal(f"{self._name} did not answer: {error!r}") from None

    def close(self) -> None:
        """Stop the worker, refusing the episodes still waiting; a later read starts a new one."""
        with self._lock:
            executor, self._executor = self._executor, None
            for job in self._queued.values():
                job.future.set_exception(self._module.refusal(f"{self._name} was stopped"))
            self._queued.clear()
        if executor is not None:
            executor.shutdown(wait=True, cancel_futures=True)

    # -- inside: all called holding the lock ------------------------------------------------------

    def _supersede(self, sha256: str, line: Line, generation: int | None) -> None:
        """Make ``sha256`` its world version's current input, dropping what an older one waits for
        and letting go what it keeps; refuse a read of an input an edit has already replaced."""
        if generation is None:
            return
        current = self._current.get(line)
        if current is not None and generation < current[0]:
            raise self._module.refusal(
                "an edit has replaced the world this read was composed from; read it again"
            )
        self._current[line] = (generation, sha256)
        superseded = f"an edit has replaced this world's {self._module.subject}; read it again"
        for key, job in list(self._queued.items()):
            if job.line == line and key[0] != sha256:
                del self._queued[key]
                job.future.set_exception(self._module.refusal(superseded))
        for key in [
            key for key in self._done if key[0] != sha256 and self._lines.get(key[0]) == line
        ]:
            del self._done[key]

    def _prune(self) -> None:
        """Forget which world version an input belongs to, and a world version's current input,
        once nothing is kept, waiting or computing for them."""
        referenced = {key[0] for key in self._done} | {key[0] for key in self._queued}
        if self._running is not None:
            referenced.add(self._running.key[0])
        self._lines = {sha: line for sha, line in self._lines.items() if sha in referenced}
        lines = set(self._lines.values())
        self._current = {line: current for line, current in self._current.items() if line in lines}

    def _live(self, key: Key) -> bool:
        """Whether an episode's input is its world version's current one, or none is known."""
        line = self._lines.get(key[0])
        current = None if line is None else self._current.get(line)
        return current is None or current[1] == key[0]

    def _need(self, value: Input, digest: str, line: Line, episode: int) -> Packed | _Job[Packed]:
        """An episode a read needs: kept, or a job it now waits for, queued if it is neither."""
        key = (digest, episode)
        done = self._done.get(key)
        if done is not None:
            self._done.move_to_end(key)
            return done
        job = self._queued.get(key)
        if job is None and self._running is not None and self._running.key == key:
            job = self._running
        if job is None:
            if len(self._queued) >= self._queue_limit:
                ahead = [queued for queued in self._queued.values() if queued.waiters == 0]
                if not ahead:
                    raise self._module.refusal(
                        f"{self._name} has {len(self._queued)} episodes waiting, each needed"
                    )
                oldest = min(ahead, key=lambda queued: queued.order)
                del self._queued[oldest.key]
                oldest.future.set_exception(self._module.refusal("pushed out of the queue"))
            job = self._queued[key] = _Job(
                key, line, self._wire(value, digest), order=next(self._order)
            )
        job.waiters += 1
        return job

    def _ahead(self, value: Input, digest: str, line: Line, episode: int) -> None:
        """Ask for an episode ahead of need, unless it is kept, waiting, computing, or the queue is
        full: work ahead of need never pushes anything out."""
        key = (digest, episode)
        running = self._running is not None and self._running.key == key
        if key in self._done or key in self._queued or running:
            return
        if len(self._queued) >= self._queue_limit:
            return
        self._queued[key] = _Job(key, line, self._wire(value, digest), order=next(self._order))

    def _by_turn(self) -> list[_Job[Packed]]:
        """Waiting jobs in the order the worker takes them: needed before ahead, then oldest."""
        return sorted(self._queued.values(), key=lambda job: (job.waiters == 0, job.order))

    def _dispatch(self) -> None:
        """Hand the worker the next episode when it has none."""
        while self._running is None and self._queued:
            job = self._by_turn()[0]
            del self._queued[job.key]
            try:
                future, executor = self._submit(self._module.compute, job.wire, job.key[1])
            except self._module.refusal as error:
                job.future.set_exception(error)
                continue
            self._running = job
            future.add_done_callback(
                lambda finished, job=job, executor=executor: self._finished(job, finished, executor)
            )

    def _finished(self, job: _Job[Packed], finished: Future[Packed], executor: Executor) -> None:
        with self._lock:
            if self._running is job:
                self._running = None
            if finished.cancelled():
                job.future.set_exception(self._module.refusal(f"{self._name} was stopped"))
            elif isinstance(finished.exception(), BrokenProcessPool):
                self._discard(executor)
                job.future.set_exception(
                    self._module.refusal(f"{self._name} stopped: {finished.exception()}")
                )
            elif finished.exception() is not None:
                job.future.set_exception(finished.exception())  # type: ignore[arg-type]
            else:
                packed = finished.result()
                if self._live(job.key):
                    self._done[job.key] = packed
                    self._done.move_to_end(job.key)
                    while len(self._done) > self._limit:
                        self._done.popitem(last=False)
                job.future.set_result(packed)
            self._dispatch()

    def _wait_for(self, item: Packed | _Job[Packed], deadline: float) -> Packed:
        """A kept episode as it is, or a job's episode, waited for until the read's one deadline."""
        if not isinstance(item, _Job):
            return item
        try:
            return item.future.result(timeout=max(0.0, deadline - self._clock()))
        except FutureTimeout:
            raise self._module.refusal(
                f"{self._name} did not finish within {self._wait:g} s"
            ) from None
        except CancelledError:
            raise self._module.refusal(f"{self._name} was stopped") from None

    def _submit(
        self, function: Callable[..., Any], *arguments: Any
    ) -> tuple[Future[Any], Executor]:
        with self._lock:
            if self._executor is None:
                self._executor = self._make()
            executor = self._executor
            try:
                return executor.submit(function, *arguments), executor
            except (BrokenProcessPool, RuntimeError) as error:
                self._discard(executor)
                raise self._module.refusal(f"{self._name} is not running: {error}") from None

    def _discard(self, executor: Executor) -> None:
        """Let a broken worker go; the next read starts another."""
        if self._executor is executor:
            self._executor = None
        executor.shutdown(wait=False, cancel_futures=True)

    def _wire(self, value: Input, digest: str) -> dict[str, Any]:
        found = self._wires.get(digest)
        if found is None:
            found = self._wires[digest] = self._module.wire(value)
            while len(self._wires) > _WIRE_LIMIT:
                self._wires.popitem(last=False)
        self._wires.move_to_end(digest)
        return found
