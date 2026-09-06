"""The worker that finishes an upload: rendition, vision, depth, scenes, proposals.

**It does not import the API and it must not start.** ``exulanica.ingest`` sits under
``exulanica.api`` in the layers contract, so a worker reaching for
``exulanica.api.authorisation`` to find out which workspaces exist inverts the layering, and
``uv run lint-imports`` says so. It takes the workspaces as a value instead. The application
knows them because they came from its token directory, and passing them down is one argument
rather than a dependency.

**What runs here and what does not.** The vision stage is a model call and belongs nowhere near
a request thread. The intake stage is a hash, an EXIF read, an orientation transform and a few
rows, and it has already happened by the time a job is claimed: see
:mod:`exulanica.ingest.derivative_queue` for why the split is where it is. So this drains capture
ids, computes derivatives from bytes already in the content-addressed store, and closes the
batch that was watching.

**The batch is closed here rather than by the request**, because a batch's terminal event is what
tells a client to stop listening and it has to come after all the work. A request that closed the
batch it opened would emit "finished" while the vision stage had not started.

**Scene grouping and match proposals run at the end of a job**, through
:func:`exulanica.ingest.continuity.run_continuity`, which is the same call
``exulanica-ingest`` makes at the end of a directory. Inside the batch, so
continuity search appears in the formation stream
as the stage it is: left out, a watched upload would stop after entity indexing and finish with
no account of the gap.

**A claim is a lease this worker keeps saying it still holds.** An independent connection renews
it while a rendition, model call, depth forward or continuity pass is running, and stage
boundaries check the same token. When either path says the lease has been taken, this worker does
nothing further to that job: it does not finish it and it does not close its batch, because the
worker that took the lease owns both. Measured without that check, with two real processes: two
terminal events for one batch 4.5 seconds apart, `succeeded` then `failed`, the second
contradicting the first.

**One delivery thread plus one lease thread, and both say what they did.** Delivery remains a
synchronous worker over a synchronous driver, polling the measured tenant-and-kind queue index.
PostgreSQL is the job system: bounded exponential retries, expired-lease reclaim and terminal
exhaustion stay in the same transactions as the job row and durable delivery ledger. A separate
broker would add a second source of truth without evidence that this queue misses its contract.
"""

from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Final

import psycopg

from exulanica.consent.regions import PersonDetector
from exulanica.db.session import Database
from exulanica.ingest import derivative_queue
from exulanica.ingest.batch import IntakeBatch
from exulanica.ingest.continuity import run_continuity
from exulanica.ingest.ledger import Ledger
from exulanica.ingest.pipeline import PhotoIngestPipeline
from exulanica.ingest.repository import IngestRepository
from exulanica.ingest.vision import VisionModel
from exulanica.reconstruction import DepthModel
from exulanica.store.base import ContentAddressedStore

__all__ = ["MINIMUM_LEASE_SECONDS", "DerivativeWorker", "JobOutcome", "lease_seconds_for"]

#: How often an idle worker asks again. Slow enough that an idle instance costs one cheap
#: indexed query per workspace every two seconds, fast enough that an upload's remaining stages
#: begin while the person who uploaded it is still watching.
_POLL_SECONDS: Final = 2.0

#: The lease when there is no model call in the gap between two beats, and the floor under every
#: computed one. It is a stated floor rather than an accident: an instance with no
#: ``NEBIUS_API_KEY`` runs a worker with ``vision=None``, which ``Services.warnings`` describes as
#: an ordinary configuration, and the model budget that sizes every other lease does not exist
#: there.
#:
#: Measured on this machine against a 200-photograph corpus with no vision model and no depth
#: model, which is exactly that deployment: the largest single capture gap was 0.059 seconds, and
#: the last gap, which also carries ``run_continuity`` over the whole corpus, was 0.033 seconds.
#: Sixty seconds is three orders of magnitude above the thing it bounds, and it is what recovery
#: costs when there is nothing slow to wait for.
MINIMUM_LEASE_SECONDS: Final = 60.0


def lease_seconds_for(vision_budget_seconds: float | None) -> float:
    """How long a claimant may be silent, given the model budget in one gap between beats.

    ``None`` means there is no vision model, which is a configuration rather than a fault, and
    the answer is :data:`MINIMUM_LEASE_SECONDS`.

    Otherwise the budget is doubled. The gap a lease has to cover is a rendition decode, a vision
    walk, a depth forward and, in the last gap, ``run_continuity``, and exactly one of those has a
    timeout. The second half is therefore an allowance for the local work rather than a bound on
    it, which is why the claim token exists: a lease that turns out to be too short costs one
    duplicated vision call, not two terminal events. The number falls the day the worker's client
    is given a measured timeout, because it is computed from that client rather than typed.
    """
    if vision_budget_seconds is None:
        return MINIMUM_LEASE_SECONDS
    return max(MINIMUM_LEASE_SECONDS, 2.0 * vision_budget_seconds)


class _LeaseLost(Exception):
    """A beat said this worker no longer holds the job. Not an error: an ordinary outcome.

    Private, and it never leaves this module. It exists so the beat can be one line inside the
    capture loop rather than a return value every caller has to remember to test, and it is
    caught before the general handler so that a lost lease is never recorded as a job failure on
    a row this worker no longer owns.
    """


@dataclass
class JobOutcome:
    """What one claimed job did, for a caller that drains synchronously and wants to know."""

    job_id: uuid.UUID
    batch_id: uuid.UUID | None
    succeeded: int = 0
    failed: int = 0
    cancelled: int = 0
    missing: int = 0
    unavailable: int = 0
    retryable_failures: int = 0
    model_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    usd_estimate: Decimal = Decimal("0")
    errors: list[str] = field(default_factory=list)
    #: This worker's lease was taken while it held the job, so another worker owns the job and
    #: the batch. A separate fact from ``failed``: nothing about the work went wrong here, and
    #: the counts above describe captures this worker computed that another worker may compute
    #: again.
    lease_lost: bool = False
    #: This job was ended by :func:`~orimera.ingest.derivative_queue.abandon` rather than run: it
    #: had used every claim it is allowed. A third fact again, and the one that says a batch was
    #: closed by a worker that never processed a single one of its captures.
    abandoned: bool = False
    retry_scheduled: bool = False
    retry_exhausted: bool = False

    @property
    def captures(self) -> int:
        return self.succeeded + self.failed + self.cancelled + self.missing + self.unavailable

    @property
    def completed(self) -> int:
        """Captures with a terminal result in this attempt; retryable failures remain pending."""
        return self.captures - self.retryable_failures

    @property
    def cost(self) -> dict[str, int | str]:
        return {
            "model_calls": self.model_calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "usd_estimate": str(self.usd_estimate),
        }


class _LeaseKeeper:
    """Renew one claim on an independent connection while a slow stage is running."""

    def __init__(
        self,
        database: Database,
        workspace_id: uuid.UUID,
        claimed: derivative_queue.QueuedDerivatives,
        *,
        worker: str,
        lease_seconds: float,
        interval_seconds: float,
    ) -> None:
        self._database = database
        self._workspace_id = workspace_id
        self._claimed = claimed
        self._worker = worker
        self._lease_seconds = lease_seconds
        self._interval_seconds = interval_seconds
        self._stop = threading.Event()
        self.lost = threading.Event()
        self.last_error: str | None = None
        self._thread = threading.Thread(
            target=self._run,
            name=f"{worker}-lease-{str(claimed.job_id)[:8]}",
            daemon=True,
        )

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=max(1.0, self._interval_seconds + 1.0))

    def _run(self) -> None:
        while not self._stop.wait(self._interval_seconds):
            try:
                with self._database.session(self._workspace_id) as connection:
                    held = derivative_queue.heartbeat(
                        connection,
                        self._workspace_id,
                        job_id=self._claimed.job_id,
                        claim_token=self._claimed.claim_token,
                        lease_seconds=self._lease_seconds,
                        worker=self._worker,
                    )
                self.last_error = None
            except Exception as exc:
                # A database blink is not proof the lease was lost. Keep trying; the main worker
                # will either reconnect before expiry or discover the rotated token at a boundary.
                self.last_error = f"{type(exc).__name__}: {exc}"
                continue
            if not held:
                self.lost.set()
                return


class DerivativeWorker:
    """Drains the derivative queue for a fixed set of workspaces."""

    def __init__(
        self,
        database: Database,
        store: ContentAddressedStore,
        workspaces: frozenset[uuid.UUID],
        *,
        vision: VisionModel | None = None,
        depth: DepthModel | None = None,
        detector: PersonDetector | None = None,
        name: str = "derivatives",
        poll_seconds: float = _POLL_SECONDS,
        lease_seconds: float = MINIMUM_LEASE_SECONDS,
        heartbeat_seconds: float | None = None,
    ) -> None:
        """``lease_seconds`` is a value rather than something read off the vision model.

        The protocol in :mod:`exulanica.ingest.vision` is ``model_id`` and ``observe``, and it stays
        that way: widening it would break every fake in the suite at runtime rather than at lint
        time, since nothing here type-checks. The one place that can compute a lease is the one
        that holds a :class:`~exulanica.models.client.ModelClient` and knows whether there is one at
        all, which is :mod:`exulanica.api.services`. It calls :func:`lease_seconds_for`.

        The default is the floor, which is exactly right for a worker with no vision model and
        too short for one with a slow model and a caller that decided nothing. Too short is
        survivable and says so: the claim token turns it into one duplicated call and a
        ``lease_lost`` outcome, rather than into two workers closing one batch.
        """
        self._database = database
        self._store = store
        self._workspaces = workspaces
        self._vision = vision
        self._depth = depth
        self._detector = detector
        self._name = name
        self._poll_seconds = poll_seconds
        self._lease_seconds = lease_seconds
        computed_heartbeat = min(30.0, lease_seconds / 3.0)
        interval = computed_heartbeat if heartbeat_seconds is None else heartbeat_seconds
        self._heartbeat_seconds = max(0.1, interval)
        self._stop = threading.Event()
        self._started = threading.Event()
        self._lifecycle_lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._last_error: str | None = None
        self._failed_passes = 0

    # -- driving it ---------------------------------------------------------------------

    def drain(self) -> list[JobOutcome]:
        """Claim and run every job that is queued right now, then return.

        **This can raise, and the loop below is what makes that survivable.** A failure inside a
        job is recorded on the job row and does not propagate; a failure opening the connection
        does, because there is no row to record it on and nothing has been claimed. Saying "never
        raises" here and leaving the connect outside the guard is the shape that kills a daemon
        thread in silence.

        This is the whole of the worker's work, factored out of the loop so that a test drives it
        directly rather than starting a thread and waiting. A thread that has to be waited on is
        a test that is slow when it passes and flaky when it does not.

        **The abandon pass runs when there is nothing left to claim**, which is where it belongs
        rather than being convenient: a job that has used every claim is invisible to
        :func:`~orimera.ingest.derivative_queue.claim` for ever and holds
        ``job_one_live_job_per_batch`` against its batch while it sits there, so nothing else can
        ever be queued for that batch and the client watching it never gets a terminal event.
        What this does NOT cover is an instance running no worker at all, which
        ``EXULANICA_DERIVATIVE_WORKER=off`` makes a real deployment: there, nothing abandons
        anything, and the note in ``Services.warnings`` about a queue drained elsewhere is the
        statement of it.
        """
        outcomes: list[JobOutcome] = []
        for workspace_id in sorted(self._workspaces):
            # ONE connection per workspace per drain, not one per job. Postgres forks a backend
            # per connection, and this loop runs every couple of seconds against every workspace
            # for the life of the process, alongside a connection per request and one held for
            # up to thirty minutes by every open formation stream.
            with self._database.session(workspace_id) as connection:
                repository = IngestRepository(connection, workspace_id)
                while not self._stop.is_set():
                    outcome = self._claim_one(connection, repository)
                    if outcome is None:
                        break
                    outcomes.append(outcome)
                outcomes.extend(self._abandon_stranded(connection, repository))
        return outcomes

    def drain_observed(self) -> list[JobOutcome]:
        """Run one finite pass with the same durable lifecycle events as daemon mode."""
        self._record_worker_lifecycle("worker_started")
        try:
            return self.drain()
        finally:
            self._record_worker_lifecycle("worker_stopped")

    def start(self) -> None:
        """Run the loop on a daemon thread. Idempotent."""
        if self._thread is not None:
            return
        self._stop.clear()
        self._started.clear()
        self._thread = threading.Thread(target=self._loop, name=self._name, daemon=True)
        self._thread.start()
        self._started.wait()

    def stop(self, *, timeout: float = 10.0) -> bool:
        """Stop claiming, let the held job finish, and report whether shutdown completed."""
        thread = self._thread
        if thread is not None:
            with self._lifecycle_lock:
                if not self._stop.is_set():
                    # Set the event before the database write so the delivery loop cannot claim
                    # another row while shutdown observability is being persisted. The lifecycle
                    # lock keeps worker_stopped behind this event in the durable order.
                    self._stop.set()
                    self._record_worker_lifecycle("shutdown_requested")
        else:
            self._stop.set()
        if thread is not None:
            thread.join(timeout=timeout)
            if thread.is_alive():
                return False
            self._thread = None
        return True

    def wait(self, timeout: float | None = None) -> bool:
        """Wait for the poll loop. True means it stopped within the requested time."""
        thread = self._thread
        if thread is None:
            return True
        thread.join(timeout=timeout)
        return not thread.is_alive()

    def _loop(self) -> None:
        """Poll until asked to stop, and **survive anything one pass throws**.

        Without this guard the thread dies on the first ``OperationalError`` at connect, a
        database restart or the server's connection slots being exhausted, and it dies in
        silence: ``start()`` ran once from the application lifespan and is a no-op afterwards.
        From then on every upload returns a job id nothing will ever claim, every batch stays
        open, and every subscriber to a formation stream waits out the route's full thirty
        minute cap for a terminal event that is not coming.

        The failure is recorded on the worker so ``/readyz`` can report it, because a queue
        nobody drains and a queue drained elsewhere must not look identical from outside, and a
        wedged thread is the third case that used to look like both.
        """
        with self._lifecycle_lock:
            self._record_worker_lifecycle("worker_started")
            self._started.set()
        try:
            while not self._stop.is_set():
                try:
                    self.drain()
                    self._last_error = None
                except Exception as exc:
                    self._last_error = f"{type(exc).__name__}: {exc}"
                    self._failed_passes += 1
                # Waiting on the event rather than sleeping, so stop() is immediate rather than up
                # to one poll interval late. A shutdown that takes two seconds per worker is a
                # deployment that looks hung.
                self._stop.wait(self._poll_seconds)
        finally:
            with self._lifecycle_lock:
                self._record_worker_lifecycle("worker_stopped")

    def _record_worker_lifecycle(self, event_type: str) -> None:
        """Persist lifecycle per workspace; leave a failed write visible on the worker itself."""
        for workspace_id in sorted(self._workspaces):
            try:
                with self._database.session(workspace_id) as connection:
                    derivative_queue.record_worker_event(
                        connection,
                        workspace_id,
                        worker=self._name,
                        event_type=event_type,
                        message=self._last_error,
                    )
            except Exception as exc:
                self._last_error = f"{type(exc).__name__}: {exc}"
                self._failed_passes += 1

    # -- what /readyz asks -----------------------------------------------------------------

    @property
    def alive(self) -> bool:
        """True when the poll thread is running. The question ``/readyz`` has to be able to ask.

        ``Services.runs_derivative_worker`` says only that a worker was asked for. Reporting
        configuration where liveness belongs is how a wedged thread reads as a healthy instance.
        """
        thread = self._thread
        return thread is not None and thread.is_alive()

    @property
    def last_error(self) -> str | None:
        """The last poll that failed, or None when the last one did not."""
        return self._last_error

    @property
    def failed_passes(self) -> int:
        """How many polls have failed since the worker started. A count, never a guess."""
        return self._failed_passes

    @property
    def name(self) -> str:
        """Stable identifier written into delivery events and process logs."""
        return self._name

    @property
    def workspace_count(self) -> int:
        """Number of explicitly authorised workspace queues this process can drain."""
        return len(self._workspaces)

    # -- one job ------------------------------------------------------------------------

    def _claim_one(
        self, connection: psycopg.Connection, repository: IngestRepository
    ) -> JobOutcome | None:
        """Claim one job and run it. Returns None when the queue for this workspace is empty.

        A failure inside the job is recorded on the job row and on the batch, and does not
        propagate: a worker that died on one bad photograph would stop draining every other
        upload in the instance, which is a much worse failure than the one it is reacting to.
        """
        workspace_id = repository.workspace_id
        claimed = derivative_queue.claim(
            connection, workspace_id, worker=self._name, lease_seconds=self._lease_seconds
        )
        if claimed is None:
            return None
        outcome = JobOutcome(job_id=claimed.job_id, batch_id=claimed.batch_id)
        if claimed.reclaimed:
            Ledger.close_interrupted_delivery_runs(
                repository,
                job_id=claimed.job_id,
                current_claim_token=claimed.claim_token,
            )
        try:
            with self._renewing_lease(repository.workspace_id, claimed) as keeper:
                self._run_job(repository, claimed, outcome, keeper)
        except _LeaseLost:
            # **Withdraw, and touch nothing.** Another worker holds this job and this batch now.
            # Writing either would be the second opinion the token exists to prevent.
            outcome.lease_lost = True
            derivative_queue.record_lease_lost(
                connection,
                workspace_id,
                worker=self._name,
                claimed=claimed,
                message="claim token no longer matches; worker withdrew without a terminal write",
            )
            return outcome
        except Exception as exc:
            outcome.errors.append(f"{type(exc).__name__}: {exc}")
            held = derivative_queue.finish(
                connection,
                workspace_id,
                job_id=claimed.job_id,
                state="failed",
                claim_token=claimed.claim_token,
                error="; ".join(outcome.errors)[:2000],
                failure_class=type(exc).__name__,
                cost=outcome.cost,
                progress_completed=outcome.captures,
                worker=self._name,
            )
            if not held:
                outcome.lease_lost = True
                return outcome
            # **failed, and not what the per-capture counts happen to say.** The counts describe
            # the captures this job reached; a raise outside that loop, in the corpus-wide pass
            # or before the loop began, leaves them at zero or at whatever it got to, and
            # `outcome_for(0, 0)` is "succeeded". A batch that closed succeeded after a job
            # failed would tell the person watching that their upload finished cleanly.
            self._close_batch(repository, claimed.batch_id, "failed")
            return outcome

        if outcome.retryable_failures:
            error = "; ".join(outcome.errors)[:2000]
            failure_class = self._failure_class(outcome, default="retryable_stage_failure")
            if claimed.attempts < derivative_queue.MAX_CLAIMS:
                held = derivative_queue.retry(
                    connection,
                    workspace_id,
                    job_id=claimed.job_id,
                    claim_token=claimed.claim_token,
                    delay_seconds=self._retry_delay(claimed.attempts),
                    error=error,
                    failure_class=failure_class,
                    worker=self._name,
                    cost=outcome.cost,
                )
                if not held:
                    outcome.lease_lost = True
                    derivative_queue.record_lease_lost(
                        connection,
                        workspace_id,
                        worker=self._name,
                        claimed=claimed,
                        message="claim was lost while scheduling a retry",
                    )
                else:
                    outcome.retry_scheduled = True
                return outcome
            outcome.retry_exhausted = True
            outcome.errors.append(
                f"retry budget exhausted after {claimed.attempts} delivery attempts"
            )
        held = derivative_queue.finish(
            connection,
            workspace_id,
            job_id=claimed.job_id,
            # Every capture refused because the user deleted it is not a failure: it is the
            # deletion path working. A job that was entirely deletions is cancelled, which
            # is a third fact and the column already has a word for it.
            state=self._job_state(outcome),
            claim_token=claimed.claim_token,
            error="; ".join(outcome.errors)[:2000] or None,
            failure_class=self._failure_class(outcome),
            cost=outcome.cost,
            progress_completed=outcome.captures,
            worker=self._name,
        )
        if not held:
            # The lease went between the last beat and this write. The job is somebody else's and
            # so is its terminal event.
            outcome.lease_lost = True
            return outcome
        self._close_batch(repository, claimed.batch_id, self._batch_state(outcome))
        return outcome

    def _abandon_stranded(
        self, connection: psycopg.Connection, repository: IngestRepository
    ) -> list[JobOutcome]:
        """End the jobs that have used every claim, and close the batches waiting on them."""
        outcomes: list[JobOutcome] = []
        while not self._stop.is_set():
            stranded = derivative_queue.abandon(
                connection, repository.workspace_id, worker=self._name
            )
            if stranded is None:
                return outcomes
            outcomes.append(
                JobOutcome(
                    job_id=stranded.job_id,
                    batch_id=stranded.batch_id,
                    abandoned=True,
                    errors=[
                        f"{stranded.job_id}: claimed {stranded.attempts} times and stranded "
                        "every time"
                    ],
                )
            )
            self._close_batch(repository, stranded.batch_id, "failed")
        return outcomes

    def _run_job(
        self,
        repository: IngestRepository,
        claimed: derivative_queue.QueuedDerivatives,
        outcome: JobOutcome,
        keeper: _LeaseKeeper,
    ) -> None:
        pipeline = PhotoIngestPipeline(
            repository,
            self._store,
            vision=self._vision,
            depth=self._depth,
            detector=self._detector,
        )
        total = len(claimed.capture_ids)
        for capture_id in claimed.capture_ids:
            # Before the capture rather than after it, so the lease covers the work that follows
            # the beat rather than the work that preceded it.
            self._beat(repository, claimed, keeper)
            started = time.monotonic()
            if not derivative_queue.record_capture(
                repository.connection,
                repository.workspace_id,
                worker=self._name,
                claimed=claimed,
                capture_id=capture_id,
                event_type="capture_started",
                progress_completed=outcome.captures,
                progress_total=total,
            ):
                raise _LeaseLost
            # The capture's current eligible receipt, resolved here rather than assumed. Both
            # paid stages need it: depth has always refused without one, and vision now does too
            # because it sends the photograph to a hosted model. A capture nobody has screened
            # gets neither, and the stages record themselves unavailable with the reason, which
            # is the honest outcome rather than an error: nothing went wrong, nobody authorized
            # sending it anywhere.
            screening = repository.latest_privacy_screening(capture_id)
            result = pipeline.ingest_derivatives(
                capture_id,
                batch_id=claimed.batch_id,
                delivery_job_id=claimed.job_id,
                delivery_claim_token=claimed.claim_token,
                privacy_screening_id=None if screening is None else screening.screening_id,
            )
            outcome.model_calls += result.model_calls
            outcome.input_tokens += result.input_tokens
            outcome.output_tokens += result.output_tokens
            outcome.usd_estimate += result.usd_estimate
            if result.tombstoned:
                outcome.cancelled += 1
                event_type = "capture_cancelled"
            elif result.missing:
                outcome.missing += 1
                if result.error:
                    outcome.errors.append(f"{capture_id}: {result.error}")
                event_type = "capture_missing"
            elif result.unavailable:
                outcome.unavailable += 1
                if result.error:
                    outcome.errors.append(f"{capture_id}: {result.error}")
                event_type = "capture_unavailable"
            elif result.error is not None:
                outcome.failed += 1
                outcome.retryable_failures += int(result.retryable)
                outcome.errors.append(f"{capture_id}: {result.error}")
                event_type = "capture_failed"
            else:
                outcome.succeeded += 1
                event_type = "capture_succeeded"

            if not derivative_queue.record_capture(
                repository.connection,
                repository.workspace_id,
                worker=self._name,
                claimed=claimed,
                capture_id=capture_id,
                event_type=event_type,
                progress_completed=outcome.completed,
                progress_total=total,
                duration_ms=int((time.monotonic() - started) * 1000),
                cost={
                    "model_calls": result.model_calls,
                    "input_tokens": result.input_tokens,
                    "output_tokens": result.output_tokens,
                    "usd_estimate": str(result.usd_estimate),
                },
                failure_class=result.failure_class,
                message=result.error,
            ):
                raise _LeaseLost

        # The whole corpus, once, rather than per photograph: continuity is a relation between
        # captures and cannot be computed from one. Inside the batch so it appears in the
        # formation stream as the stage it is. The same call `exulanica-ingest` makes at the end
        # of a directory, and the same one, so the two cannot drift.
        #
        # The last beat, and the only one whose gap carries two passes over the whole corpus
        # rather than one photograph. Nothing bounds how long those take; see `lease_seconds_for`.
        self._beat(repository, claimed, keeper)
        run_continuity(repository, batch_id=claimed.batch_id)

    def _beat(
        self,
        repository: IngestRepository,
        claimed: derivative_queue.QueuedDerivatives,
        keeper: _LeaseKeeper | None = None,
    ) -> None:
        """Say this worker is still here, and stop the job when the answer is that it is not."""
        if keeper is not None and keeper.lost.is_set():
            raise _LeaseLost
        if not derivative_queue.heartbeat(
            repository.connection,
            repository.workspace_id,
            job_id=claimed.job_id,
            claim_token=claimed.claim_token,
            lease_seconds=self._lease_seconds,
            worker=self._name,
        ):
            raise _LeaseLost(
                f"job {claimed.job_id} was reclaimed while this worker held it; withdrawing "
                "without finishing it and without closing its batch"
            )

    @contextmanager
    def _renewing_lease(
        self, workspace_id: uuid.UUID, claimed: derivative_queue.QueuedDerivatives
    ) -> Iterator[_LeaseKeeper]:
        keeper = _LeaseKeeper(
            self._database,
            workspace_id,
            claimed,
            worker=self._name,
            lease_seconds=self._lease_seconds,
            interval_seconds=self._heartbeat_seconds,
        )
        keeper.start()
        try:
            yield keeper
        finally:
            keeper.stop()

    @staticmethod
    def _job_state(outcome: JobOutcome) -> str:
        if outcome.failed or outcome.retry_exhausted:
            return "failed"
        if outcome.missing:
            return "missing"
        if outcome.unavailable:
            return "unavailable"
        if outcome.cancelled and not outcome.succeeded:
            return "cancelled"
        return "done"

    @staticmethod
    def _batch_state(outcome: JobOutcome) -> str:
        if outcome.failed or outcome.missing or outcome.retry_exhausted:
            return "failed"
        if outcome.unavailable:
            return "partial"
        return IntakeBatch.outcome_for(succeeded=outcome.succeeded, failed=outcome.failed)

    @staticmethod
    def _failure_class(outcome: JobOutcome, *, default: str | None = None) -> str | None:
        if outcome.retry_exhausted:
            return "retry_exhausted"
        if outcome.missing:
            return "missing_input"
        if outcome.unavailable:
            return "unavailable"
        return default

    @staticmethod
    def _retry_delay(attempt: int) -> float:
        """Small bounded exponential delay; attempts is the claim that just failed."""
        return min(60.0, float(2 ** max(0, attempt - 1)))

    @staticmethod
    def _close_batch(repository: IngestRepository, batch_id: uuid.UUID | None, status: str) -> None:
        """Close the watched intake with what happened, which is what ends the stream.

        The caller computes the status rather than handing over counts, because two of the three
        callers have no counts to hand over: a job that raised outside the per-capture loop
        reached whatever the loop reached, or zero, and ``outcome_for(0, 0)`` is "succeeded", and
        an abandoned job was never run by this worker at all.

        A capture the user deleted mid-flight counts as neither succeeded nor failed here: it
        was withdrawn. Counting it as a failure would put a red state in front of somebody who
        had just pressed delete and got exactly what they asked for, and the terminal event
        already tells the truth about what is left: ``photographsAvailable`` counts live
        captures, so a batch whose every photograph was deleted ends as ready with none.

        ``IntakeBatch.close`` refuses a batch that is not ``running``, so this is safe to call
        for a batch some other worker has already closed. It is the second guard rather than the
        first: the token on ``finish`` is what stops this being reached at all.
        """
        if batch_id is None:
            return
        IntakeBatch(repository=repository, batch_id=batch_id).close(status)
