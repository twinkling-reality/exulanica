"""Everything generated from a world kind, made in a worker process of its own and bounded.

Stage B of a kind's checks (:func:`~exulanica.world.kinds.samples.check_samples`) builds up to 48
sample worlds, making a world of a kind (:func:`~exulanica.world.composers.site_plan.compose_kind`)
tries up to four candidates, and reading a site world's drawing, or the place its society walks
(:func:`~exulanica.world.composers.site_plan.society_place`), generates its records again from its
receipt (:func:`~exulanica.world.composers.site_plan.records`). All are pure Python, and pure
Python on a request's thread holds the interpreter's lock from every other request. So each runs in
one spawned worker process (:func:`~exulanica.world.episode_worker.worker_pool`), as a town's
sample does (:mod:`exulanica.world.specification_samples`), and no site is generated on a request's
thread. A request waits for its job without holding the lock, within these bounds:

- **a time limit per job** (:data:`CHECK_SECONDS`, :data:`COMPOSE_SECONDS`,
  :data:`DRAWING_SECONDS`): a job not done by then is answered ``overran``;
- **one request waits for a job**: asking for a job already running is answered ``overran`` at
  once, rather than holding another thread, admission place and connection for it;
- **a bound on jobs waiting** (:data:`JOBS_WAITING`) and **on one workspace's jobs**
  (:data:`WORKSPACE_JOBS`, a job counting until it finishes, whoever stopped waiting for it): past
  either a request is answered ``busy`` rather than queued;
- **finished checks, drawings and places are kept** by their workspace and what they are made
  from (:data:`CHECKS_KEPT`, :data:`DRAWINGS_KEPT`, :data:`PLACES_KEPT`; :func:`check_key`,
  :func:`drawing_key`, :func:`place_key`), so asking again after ``overran`` reads the finished
  work and no workspace reads or waits on another's; a composed world is never kept, since each is
  made for a fresh identity, but its drawing and its society's place are, made with it. A kept
  place is handed out as a copy of its own, so no request changes what another reads;
- a worker that dies answers ``unavailable``, and the next job starts a new process; at every
  request, one whose oldest job runs past :data:`STUCK_SECONDS` is replaced and its process stopped.

Nothing is handed to the pool, or taken from it, while this module's own lock is held: the pool
runs its callbacks under a lock of its own, and they take this one.

What a job answers is plain data: ``{"status": "done", ...}`` with the report, the composed world or
the drawing, or ``{"status": "refused", ...}`` with the refusal's code and words.
"""

from __future__ import annotations

import copy
import functools
import json
import logging
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Mapping
from concurrent.futures import CancelledError, Executor, Future
from concurrent.futures import TimeoutError as FutureTimeout
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass
from typing import Any, Final, Literal

from exulanica.world.specification_samples import sample_process_pool
from exulanica.world.terrain_authoring import TERRAIN_COMPOSER_VERSIONS

__all__ = [
    "CHECKS_KEPT",
    "CHECK_SECONDS",
    "COMPOSE_SECONDS",
    "DRAWINGS_KEPT",
    "DRAWING_SECONDS",
    "JOBS_WAITING",
    "PLACES_KEPT",
    "PLACE_SECONDS",
    "STUCK_SECONDS",
    "WORKSPACE_JOBS",
    "JobOutcome",
    "Kept",
    "KindWorkWaiting",
    "KindWorker",
    "WorkerComposer",
    "check_job",
    "check_key",
    "close_kind_worker",
    "compose_job",
    "drawing_job",
    "drawing_key",
    "kind_worker",
    "place_job",
    "place_key",
    "site_ground_place_id",
]

#: The longest a request waits for a kind's sample checks. Measured 2026-10-06 on the development
#: machine at a load of about 16 to 23: one sample world of a heavy kind (twelve zones, 480
#: fixtures, about 930 walking places, near the 962 its graph may hold) is laid out, checked and
#: walked in about 0.09 s, with its layout within the bounds catalog's ``layout_trials``. A check
#: builds at most 48 samples of up to four candidates, 192 such worlds, about 17 s, and
#: ``check_layout_trials`` bounds the layouts of the whole check. The limit is more than twice that,
#: rounded up to a whole 5 s, the rule the town's samples derive theirs by.
CHECK_SECONDS: Final = 40.0
#: The longest a request waits for one identity's world: up to four candidates of one sample's
#: work; the town's sample limit, 15 s, holds it many times over.
COMPOSE_SECONDS: Final = 15.0
#: The longest a request waits for a site world's drawing: its one kept candidate generated again,
#: within the layout budget it was made under.
DRAWING_SECONDS: Final = 15.0
#: The longest a request waits for the place a site world's society walks: its one kept candidate
#: generated again, as for its drawing, and its walking graph built (about 0.03 s near its 962
#: places, measured 2026-10-06).
PLACE_SECONDS: Final = 15.0
#: Jobs waiting for the worker besides the one it computes.
JOBS_WAITING: Final = 4
#: Jobs one workspace may have waiting or computing: a person's own work is one job at a time, and
#: two lets a world's drawing be read while another world is being made.
WORKSPACE_JOBS: Final = 2
#: Finished checks kept by the kind document's digest: a creator sending one kind twice reads it
#: once.
CHECKS_KEPT: Final = 32
#: Finished drawings kept by their receipt's digest: the site worlds being looked at.
DRAWINGS_KEPT: Final = 16
#: Finished places kept by their receipt's digest and place: the site worlds people live in.
PLACES_KEPT: Final = 16
#: How long a job may run before its process is taken for stuck and replaced: four times the
#: longest limit. A request stops waiting at its limit; this bounds how long a process that never
#: finishes holds the queue.
STUCK_SECONDS: Final = 4 * CHECK_SECONDS

_log = logging.getLogger(__name__)

JobStatus = Literal["done", "overran", "busy", "unavailable"]


class Kept:
    """Finished jobs kept by what they were made from, the least recently read dropped past
    ``size``; safe to share between threads. With ``copies``, each read hands out a copy of its
    own, for answers a reader goes on to build from."""

    def __init__(self, size: int, *, copies: bool = False) -> None:
        self._size = size
        self._copies = copies
        self._lock = threading.Lock()
        self._items: OrderedDict[str, dict[str, Any]] = OrderedDict()

    def get(self, key: str) -> dict[str, Any] | None:
        with self._lock:
            found = self._items.get(key)
            if found is not None:
                self._items.move_to_end(key)
        if found is not None and self._copies:
            return copy.deepcopy(found)
        return found

    def put(self, key: str, value: dict[str, Any]) -> None:
        with self._lock:
            self._items[key] = value
            self._items.move_to_end(key)
            while len(self._items) > self._size:
                self._items.popitem(last=False)

    def forget(self, prefixes: tuple[str, ...]) -> None:
        """Remove retained answers under exact namespaces, without retaining their digests."""
        with self._lock:
            for key in list(self._items):
                if key.startswith(prefixes):
                    del self._items[key]


@dataclass(frozen=True, slots=True)
class JobOutcome:
    """A job's answer: ``done`` with what the job returned, or why there is none (``busy`` says
    ``workspace`` when it is this workspace's own bound)."""

    status: JobStatus
    value: dict[str, Any] | None = None
    reason: str = ""


class KindWorkWaiting(RuntimeError):
    """A kind job the worker did not answer in time, or could not take: ``overran``, ``busy`` or
    ``unavailable``, with words a person reads and how many seconds to wait before asking again."""

    def __init__(self, status: str, *, kept: bool = True, reason: str = "") -> None:
        if status == "overran":
            words = (
                "This takes longer than a request waits. Ask again shortly: the finished work is "
                "kept and read."
                if kept
                else "Making this world takes longer than a request waits. Ask again shortly."
            )
            retry = 2
        elif status == "busy":
            words = (
                "This workspace is already building worlds of its kinds. Ask again when they are "
                "done."
                if reason == "workspace"
                else "The server is building other worlds of kinds. Ask again shortly."
            )
            retry = 2
        else:
            status = "unavailable"
            words = "Worlds of kinds could not be built here just now."
            retry = 5
        super().__init__(words)
        self.status = status
        self.code = f"kind_work_{status}"
        self.retry_seconds = retry


def check_key(workspace: str, document_sha256: str) -> str:
    """Where a kind's finished check is kept: by its workspace and its document."""
    return f"check:{workspace}:{document_sha256}"


def drawing_key(workspace: str, receipt_sha256: str) -> str:
    """Where a site world's drawing is kept: by its workspace and its receipt."""
    return f"drawing:{workspace}:{receipt_sha256}"


def place_key(workspace: str, receipt_sha256: str, place_id: str) -> str:
    """Where the place a site world's society walks is kept: by its workspace, its receipt and
    its place."""
    return f"place:{workspace}:{receipt_sha256}:{place_id}"


# -- in the worker process -----------------------------------------------------------------------

#: The records of the site worlds this process made or read last, by workspace and receipt
#: digest: the drawing read just after a world is made finds the records its making generated.
_RECORDS_KEPT: Final = 8
_records: OrderedDict[str, tuple[object, ...]] = OrderedDict()
_records_lock = threading.Lock()


def _keep_records(workspace: str, receipt_sha256: str, records: tuple[object, ...]) -> None:
    key = f"{workspace}:{receipt_sha256}"
    with _records_lock:
        _records[key] = records
        _records.move_to_end(key)
        while len(_records) > _RECORDS_KEPT:
            _records.popitem(last=False)


def _records_of(workspace: str, receipt: Mapping[str, Any], receipt_sha256: str) -> Any:
    """The records a receipt generates again, or the ones this process kept for it; a refusal's
    words when its receipt no longer reads."""
    from exulanica.world.composers.site_plan import records
    from exulanica.world.errors import InvalidStructuralData

    with _records_lock:
        found = _records.get(f"{workspace}:{receipt_sha256}")
    if found is None:
        try:
            found = tuple(records(receipt))
        except InvalidStructuralData as exc:
            return str(exc)
        _keep_records(workspace, receipt_sha256, found)
    return found


def _drawn(
    world_id: str, receipt: Mapping[str, Any], receipt_sha256: str, records: tuple[object, ...]
) -> dict[str, Any]:
    """The drawing as the bytes a response carries (written as the API writes JSON, here rather
    than on the request's thread) and its digest."""
    from exulanica.world.site_drawing import site_drawing, site_drawing_sha256

    drawing = site_drawing(
        world_id=world_id, receipt=receipt, receipt_sha256=receipt_sha256, records=records
    )
    body = json.dumps(
        drawing, ensure_ascii=False, allow_nan=False, indent=None, separators=(",", ":")
    ).encode("utf-8")
    return {"body": body, "sha256": site_drawing_sha256(drawing)}


def site_ground_place_id() -> str:
    """The place a site world's society walks: its one region's, as every saved world's ground
    names its region's place."""
    from exulanica.world.composers.site_plan import REGION_ID
    from exulanica.world.society_authored_ground import ground_place_id

    return ground_place_id(REGION_ID)


def _placed(
    place_id: str, receipt: Mapping[str, Any], records: tuple[object, ...]
) -> dict[str, Any]:
    """The place a site world's society walks, made from its records within the walking graph's
    budget, or why it cannot be, by name. With the place goes ``blocked``, the site's blocked
    boxes as plain figures: what a society of things keeps a placed thing's standing places clear
    of, which only the records state and the place does not carry."""
    from exulanica.grammar.errors import CatalogError
    from exulanica.world.composers.site_plan import society_place
    from exulanica.world.errors import InvalidStructuralData
    from exulanica.world.society_site_place import GraphOverBudget, site_blocked_boxes

    try:
        if receipt["composer"]["version"] in TERRAIN_COMPOSER_VERSIONS:
            from exulanica.world.composers.site_plan import receipt_terrain

            receipt_terrain(receipt)
            return {
                "status": "refused",
                "code": "terrain_society_projection_unavailable",
                "detail": "This terrain has no society projection.",
            }
        return {
            "status": "done",
            "place": society_place(place_id, receipt, records),
            "blocked": site_blocked_boxes(records),
        }
    except GraphOverBudget as exc:
        return {
            "status": "refused",
            "code": "kind_graph_over_budget",
            "detail": f"kind_graph_over_budget: {exc}",
        }
    except (CatalogError, InvalidStructuralData, ValueError) as exc:
        return {"status": "refused", "code": "kind_place_refused", "detail": str(exc)}


def check_job(document: dict[str, Any]) -> dict[str, Any]:
    """Read the kind and build its sample worlds: the report, or the refusal by name."""
    from exulanica.world.kinds.document import KindRefused, read_kind
    from exulanica.world.kinds.samples import check_samples

    try:
        return {"status": "done", "report": check_samples(read_kind(document))}
    except KindRefused as refused:
        return {
            "status": "refused",
            "code": refused.code,
            "detail": refused.detail,
            "where": refused.where,
            "report": getattr(refused, "report", None),
        }


def compose_job(
    workspace: str,
    document: dict[str, Any],
    values: dict[str, int],
    world_id: str,
    support: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compose the world the kind makes with ``values`` for ``world_id`` and draw it, with the
    place its society walks (the one its checks built), or say why not."""
    from exulanica.world.composers.site_plan import compose_kind
    from exulanica.world.kinds.document import read_kind
    from exulanica.world.kinds.samples import SiteRefused
    from exulanica.world.society_site_place import site_blocked_boxes
    from exulanica.world.support_surfaces import SupportRefused

    place_id = site_ground_place_id()
    try:
        composed = compose_kind(
            read_kind(document), values, world_id, place_id=place_id, support=support
        )
    except SupportRefused as refused:
        return {
            "status": "support_refused",
            "code": refused.code,
            "detail": refused.detail,
            "where": refused.where,
        }
    except SiteRefused as refused:
        return {"status": "refused", "code": refused.code, "refusals": list(refused.refusals)}
    records = tuple(composed.records)
    _keep_records(workspace, composed.receipt_sha256, records)
    return {
        "status": "done",
        "composed": composed,
        **_drawn(world_id, composed.receipt, composed.receipt_sha256, records),
        "place_id": place_id,
        # Kept as the place job keeps it: the place, and the site's blocked boxes beside it.
        "placed": {
            "status": "done",
            "place": composed.place,
            "blocked": site_blocked_boxes(records),
        },
    }


def compose_terrain_job(workspace: str, authoring: dict, world_id: str) -> dict[str, Any]:
    """Admit and draw retained terrain in the existing bounded process worker."""
    from exulanica.world.composers.site_plan import compose_terrain
    from exulanica.world.terrain_authoring import TerrainAuthoringRefused

    try:
        composed = compose_terrain(authoring, world_id)
    except TerrainAuthoringRefused as exc:
        return {"status": "terrain_refused", "code": exc.code, "detail": exc.detail}
    records = tuple(composed.records)
    _keep_records(workspace, composed.receipt_sha256, records)
    place_id = site_ground_place_id()
    return {
        "status": "done",
        "composed": composed,
        **_drawn(world_id, composed.receipt, composed.receipt_sha256, records),
        "place_id": place_id,
        "placed": _placed(place_id, composed.receipt, records),
    }


def drawing_job(
    workspace: str, world_id: str, receipt: dict[str, Any], receipt_sha256: str
) -> dict[str, Any]:
    """A site world's drawing, from the records its receipt generates again (or the ones its making
    left here), or the reason its receipt no longer reads."""
    found = _records_of(workspace, receipt, receipt_sha256)
    if isinstance(found, str):
        return {"status": "refused", "detail": found}
    return {"status": "done", **_drawn(world_id, receipt, receipt_sha256, found)}


def place_job(
    workspace: str, receipt: dict[str, Any], receipt_sha256: str, place_id: str
) -> dict[str, Any]:
    """The place a site world's society walks, from the records its receipt generates again (or
    the ones its making left here), or the reason it cannot be made."""
    found = _records_of(workspace, receipt, receipt_sha256)
    if isinstance(found, str):
        return {"status": "refused", "code": "kind_place_refused", "detail": found}
    return _placed(place_id, receipt, found)


# -- in the server ------------------------------------------------------------------------------


class _Running:
    """A job handed to the pool: the pool, when, whose, where it is kept, and its future once the
    pool has taken it."""

    __slots__ = ("executor", "future", "invalidated", "kept", "started", "workspace")

    def __init__(
        self, executor: Executor, started: float, workspace: str, kept: Kept | None
    ) -> None:
        self.executor = executor
        self.started = started
        self.workspace = workspace
        self.kept = kept
        self.invalidated = False
        self.future: Future[dict[str, Any]] | None = None


def _terminate(executor: Executor) -> None:
    """Let a pool go without waiting on it, and stop any process it still runs (as the town's
    samples do: no public way to stop a pool's processes before Python 3.14)."""
    processes = list((getattr(executor, "_processes", None) or {}).values())
    executor.shutdown(wait=False, cancel_futures=True)
    for process in processes:
        if process.is_alive():
            process.terminate()


class KindWorker:
    """Kind jobs one worker computes, bounded and kept; safe to share between threads."""

    def __init__(
        self,
        executor: Callable[[], Executor] = sample_process_pool,
        *,
        waiting: int = JOBS_WAITING,
        per_workspace: int = WORKSPACE_JOBS,
        stuck_seconds: float = STUCK_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._make = executor
        self._waiting = waiting
        self._per_workspace = per_workspace
        self._stuck = stuck_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._executor: Executor | None = None
        self._running: dict[str, _Running] = {}
        self._closed = False
        self._epoch = 0
        #: Finished checks, by their workspace and the kind document's digest.
        self.checks = Kept(CHECKS_KEPT)
        #: Finished drawings, by their workspace and receipt's digest.
        self.drawings = Kept(DRAWINGS_KEPT)
        #: Finished places, by their workspace, receipt's digest and place, each read a copy.
        self.places = Kept(PLACES_KEPT, copies=True)

    @property
    def epoch(self) -> int:
        with self._lock:
            return self._epoch

    def forget_receipts(self, workspace: str, digests: frozenset[str]) -> None:
        """Evict erased worlds' parent answers and discard the owned child holding documents.

        This worker uses one shared child, so its other in-flight jobs become unavailable and
        can retry from durable inputs. Other worlds' finished parent answers stay available.
        Late results cannot refill caches; no removed content digest is retained by this method.
        Other API processes still require their own invalidation.
        """
        if not digests:
            return
        with self._lock:
            self._epoch += 1
            self.drawings.forget(tuple(drawing_key(workspace, digest) for digest in digests))
            self.checks.forget((f"terrain-coverage:v1:{workspace}:",))
            self.places.forget(tuple(f"place:{workspace}:{digest}:" for digest in digests))
            executor, self._executor = self._executor, None
            for running in self._running.values():
                running.invalidated = True
            self._running.clear()
        if executor is not None:
            _terminate(executor)

    def forget_kind(self, workspace: str, digest: str) -> None:
        """Discard a kept kind's checks and owned child, invalidating late completions."""
        with self._lock:
            self._epoch += 1
            self.checks.forget((check_key(workspace, digest),))
            executor, self._executor = self._executor, None
            for running in self._running.values():
                running.invalidated = True
            self._running.clear()
        if executor is not None:
            _terminate(executor)

    def keep_composed(
        self,
        epoch: int,
        drawn: tuple[str, dict[str, Any]] | None,
        placed: tuple[str, dict[str, Any]] | None,
    ) -> None:
        """Publish a completed composition only while its worker generation is still current."""
        with self._lock:
            if self._closed or epoch != self._epoch:
                return
            if drawn is not None:
                self.drawings.put(*drawn)
            if placed is not None:
                self.places.put(*placed)

    def run(
        self,
        key: str,
        seconds: float,
        job: Callable[..., dict[str, Any]],
        *args: Any,
        workspace: str,
        kept: Kept | None = None,
    ) -> JobOutcome:
        """``job(*args)`` in the worker for ``workspace``, waited for at most ``seconds``; kept in
        ``kept`` under ``key`` when it finishes, if given."""
        self._let_stuck_go()
        with self._lock:
            if self._closed:
                # Closed with its server: a job still asking (a draft's thread) starts no process.
                return JobOutcome("unavailable", reason="closed")
            found = None if kept is None else kept.get(key)
            if found is not None:
                return JobOutcome("done", found)
            if key in self._running:
                return JobOutcome("overran")
            if len(self._running) > self._waiting:
                return JobOutcome("busy")
            mine = sum(1 for running in self._running.values() if running.workspace == workspace)
            if mine >= self._per_workspace:
                return JobOutcome("busy", reason="workspace")
            executor = self._executor
            if executor is None:
                executor = self._executor = self._make()
            running = self._running[key] = _Running(executor, self._clock(), workspace, kept)
        try:
            future = executor.submit(job, *args)
        except Exception as failed:
            # A pool that cannot take the job (broken, shut down, or unable to start its process)
            # leaves no job behind, counted against the workspace and the queue, and is let go.
            with self._lock:
                if self._running.get(key) is running:
                    del self._running[key]
            if not isinstance(failed, BrokenProcessPool | RuntimeError):
                _log.exception("the kind worker could not take a job")
            self._discard(executor)
            return JobOutcome("unavailable")
        running.future = future
        # Added once the future is recorded: a future already done runs it at once, here.
        future.add_done_callback(functools.partial(self._finished, key, running))
        try:
            value = future.result(timeout=seconds)
            with self._lock:
                if running.invalidated:
                    return JobOutcome("unavailable")
            return JobOutcome("done", value)
        except FutureTimeout:
            return JobOutcome("overran")
        except (BrokenProcessPool, CancelledError):
            self._discard(executor)
            return JobOutcome("unavailable")
        except Exception:
            # A defect in the job, not a refusal: said at ERROR, answered as unavailable.
            _log.exception("a world kind job failed")
            return JobOutcome("unavailable")

    def _let_stuck_go(self) -> None:
        with self._lock:
            if not self._running:
                return
            oldest = min(self._running.values(), key=lambda running: running.started)
            if self._clock() - oldest.started <= self._stuck:
                return
            executor = oldest.executor
        _log.error("a world kind job ran past %s s; its worker is replaced", self._stuck)
        self._discard(executor)

    def _discard(self, executor: Executor) -> None:
        with self._lock:
            if self._executor is executor:
                self._executor = None
            for key in [k for k, running in self._running.items() if running.executor is executor]:
                self._running[key].invalidated = True
                del self._running[key]
        _terminate(executor)

    def _finished(self, key: str, running: _Running, future: Future[dict[str, Any]]) -> None:
        with self._lock:
            if self._running.get(key) is running:
                # Publish and retire under one lock. An obsolete pool's late callback may
                # neither restore discarded content nor overwrite a replacement job's answer.
                if (
                    not future.cancelled()
                    and future.exception() is None
                    and running.kept is not None
                ):
                    running.kept.put(key, future.result())
                del self._running[key]

    def close(self) -> None:
        """Stop the worker without waiting on a stuck job, for good: a later job is answered
        ``unavailable`` and starts no process. The server's lifespan calls this."""
        with self._lock:
            self._closed = True
            executor, self._executor = self._executor, None
            for running in self._running.values():
                running.invalidated = True
            self._running.clear()
        if executor is not None:
            _terminate(executor)


#: This server's kind jobs and the worker process computing them, started at the first job.
_worker = KindWorker()


def kind_worker() -> KindWorker:
    """This server's kind worker."""
    return _worker


def close_kind_worker() -> None:
    """Stop the worker process; the server's lifespan calls this as it ends. The worker is closed
    for good and a fresh one, which starts nothing until its first job, takes its place, so a
    caller that took the closed worker earlier (a draft still running) starts no process, and a
    server started later in the same process (a test's) has a worker."""
    global _worker
    closed, _worker = _worker, KindWorker()
    closed.close()


class WorkerComposer:
    """Composes one identity's world of a kind in the kind worker for one workspace, and keeps the
    drawing and the society's place of the last world it made, which is the world saved when the
    making succeeds. What makes a world of a kind hands this to the saved entries, so no
    generation runs on a request's thread or a draft's, and then keeps :attr:`drawn` and
    :attr:`placed` with :meth:`keep`."""

    def __init__(self, workspace: Any, *, support: Mapping[str, Any] | None = None) -> None:
        self.workspace = str(workspace)
        self._worker = kind_worker()
        self._epoch = self._worker.epoch
        self._support = None if support is None else copy.deepcopy(dict(support))
        self._support_key = ""
        if self._support is not None:
            from exulanica.canonical import sha256_of_canonical
            from exulanica.world.support_surfaces import SupportRefused

            try:
                self._support_key = f":support:{sha256_of_canonical(self._support).hex()}"
            except (TypeError, ValueError) as exc:
                raise SupportRefused("support", "is canonical integer JSON") from exc
        #: The last world's drawing and its society's place, each by where the worker keeps it.
        self.drawn: tuple[str, dict[str, Any]] | None = None
        self.placed: tuple[str, dict[str, Any]] | None = None

    def __call__(self, kind: Any, values: Mapping[str, int], world_id: str) -> Any:
        from exulanica.world.kinds.samples import SiteRefused
        from exulanica.world.support_surfaces import SupportRefused

        outcome = self._worker.run(
            f"compose:{self.workspace}:{kind.sha256}:{world_id}:"
            f"{json.dumps(dict(values), sort_keys=True)}" + self._support_key,
            COMPOSE_SECONDS,
            compose_job,
            self.workspace,
            dict(kind.document),
            dict(values),
            world_id,
            self._support,
            workspace=self.workspace,
        )
        if outcome.status != "done" or outcome.value is None:
            raise KindWorkWaiting(outcome.status, kept=False, reason=outcome.reason)
        answer = outcome.value
        if answer["status"] == "support_refused":
            raise SupportRefused(answer["where"], answer["detail"])
        if answer["status"] == "refused":
            raise SiteRefused(answer["code"], answer["refusals"])
        composed = answer["composed"]
        self.drawn = (
            drawing_key(self.workspace, composed.receipt_sha256),
            {"status": "done", "body": answer["body"], "sha256": answer["sha256"]},
        )
        self.placed = (
            place_key(self.workspace, composed.receipt_sha256, answer["place_id"]),
            answer["placed"],
        )
        return composed

    def keep(self) -> None:
        """Keep the made world's drawing and its society's place where the worker reads them:
        the page reads the drawing next, and bringing people in reads the place."""
        self._worker.keep_composed(self._epoch, self.drawn, self.placed)


class TerrainWorkerComposer:
    """Compose explicit terrain using the existing workspace cache and erasure epoch."""

    def __init__(self, workspace: Any) -> None:
        self.workspace = str(workspace)
        self._worker = kind_worker()
        self._epoch = self._worker.epoch
        self.drawn: tuple[str, dict[str, Any]] | None = None
        self.placed: tuple[str, dict[str, Any]] | None = None

    def __call__(self, authoring: dict, world_id: str) -> Any:
        from exulanica.canonical import sha256_of_canonical
        from exulanica.world.terrain_authoring import TerrainAuthoringRefused

        try:
            source_sha = sha256_of_canonical(authoring).hex()
        except (TypeError, ValueError) as exc:
            raise TerrainAuthoringRefused("Terrain source must be canonical integer JSON") from exc
        outcome = self._worker.run(
            f"compose-terrain:{self.workspace}:{source_sha}:{world_id}",
            COMPOSE_SECONDS,
            compose_terrain_job,
            self.workspace,
            copy.deepcopy(authoring),
            world_id,
            workspace=self.workspace,
        )
        if outcome.status != "done" or outcome.value is None:
            raise KindWorkWaiting(outcome.status, kept=False, reason=outcome.reason)
        answer = outcome.value
        if answer["status"] == "terrain_refused":
            raise TerrainAuthoringRefused(answer["detail"])
        composed = answer["composed"]
        self.drawn = (
            drawing_key(self.workspace, composed.receipt_sha256),
            {"status": "done", "body": answer["body"], "sha256": answer["sha256"]},
        )
        self.placed = (
            place_key(self.workspace, composed.receipt_sha256, answer["place_id"]),
            answer["placed"],
        )
        return composed

    def keep(self) -> None:
        """Retain results only while their workspace erasure epoch still matches."""
        self._worker.keep_composed(self._epoch, self.drawn, self.placed)


def terrain_dressing_coverage_job(document: dict, components: dict[str, bytes]) -> dict[str, Any]:
    """Pure bounded decoding and exact coverage; it grants no current source authority."""
    from exulanica.world.asset_preparation import decode_texture
    from exulanica.world.terrain_dressing import compile_terrain_dressing, read_terrain_dressing

    try:
        coverage = compile_terrain_dressing(
            read_terrain_dressing(document), components, decode_image=decode_texture
        )
    except ValueError as exc:
        return {"status": "refused", "detail": str(exc)}
    return {"status": "done", "coverage": coverage}


class TerrainDressingWorkerCompiler:
    """Cache pure coverage in existing bounded kind checks, scoped to a workspace and source."""

    def __init__(self, workspace: Any) -> None:
        self.workspace = str(workspace)
        self.worker = kind_worker()

    def __call__(self, dressing: Any, components: dict[str, bytes]) -> Any:
        from exulanica.world.terrain_authoring import TerrainAuthoringRefused

        outcome = self.worker.run(
            f"terrain-coverage:v1:{self.workspace}:{dressing.sha256}",
            DRAWING_SECONDS,
            terrain_dressing_coverage_job,
            dressing.document(),
            components,
            workspace=self.workspace,
            kept=self.worker.checks,
        )
        if outcome.status != "done" or outcome.value is None:
            raise KindWorkWaiting(outcome.status, kept=True, reason=outcome.reason)
        if outcome.value["status"] != "done":
            raise TerrainAuthoringRefused(outcome.value["detail"])
        return outcome.value["coverage"]
