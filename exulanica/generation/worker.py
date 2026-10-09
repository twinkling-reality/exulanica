"""The generation worker: one pass follows every batch in flight, settles what is decided and, while
a session is warm, answers or queues each served workspace's waiting requests.

One pass (:meth:`PieceGenerationWorker.run_once`), each workspace on its own, so a fault in one
(logged with its kind) never stops the others:

1. **The session.** The latest registered session still open (``generation_session``) and its
   state from its heartbeats in the bucket (off, starting, warm or ended:
   :func:`exulanica.generation.session.session_state`).
2. **Following**, each batch on its own, against the session it went to and by its own entry id.
   When its done marker says it ran, the receipts the marker names are read against their requests
   (:func:`exulanica.generation.entries.outputs`), each piece is kept through the shared store's one
   write path (:func:`exulanica.generation.pieces.store_piece`), and the batch ends done. When the
   marker says the session refused the entry, or a marker or output does not read as this entry's,
   the batch ends refused. With no done marker, a batch no session claimed expires once its
   ``not_after`` has passed (with :data:`~exulanica.generation.entries.CLOCK_ALLOWANCE` for the
   clocks), or at once when its own session's last heartbeat says it ended (an entry names the one
   session that may take it), and one a session claimed expires once its claim plus its job's stop
   has passed. A newer session's registration ends nothing by itself. A batch whose requests no
   longer read under the deployed catalogs ends refused (``request_unreadable``), its measured
   time settled.
3. **Settling.** Every batch's end decides each request's settlement in the same transaction: what
   its items measured at the compute catalog's rate, at most its reservation, and charged once for
   the requests that share a request digest (to the oldest; the others settle at USD 0); not_sent
   when no session took the entry or it never reached the bucket; unknown when a session took it
   and said nothing more, when its done marker states more time than its job's stop, or the
   workspace was deleted while it was queued. Each decided settlement
   is then taken by the spending authority and marked settled, and retried on every pass until it
   is.
4. **Answering and queueing**, only while the session is warm, and only for a workspace with no
   batch in flight. A waiting request every variant of which the installation already keeps
   (``generated_piece``, under the request's digest, the session's models and the post-process
   version) is answered from it at once, with no GPU run and no charge. A waiting request that no
   longer reads under the deployed catalogs (its budgets digest changed) ends failed
   ``request_unreadable``, since no session could make it. The rest, as many as the session's time
   left allows, each read before any is admitted, are admitted one by one under the workspace's
   ``nebius_ai_cloud_gpu`` grant at their worst case; the admitted ones are recorded as one batch
   (each request queued, naming its reservation), then dispatched, then written as one queue entry
   with one item set per request digest, ``ready.json`` last. A failure before ``ready.json`` ends
   the batch refused with nothing sent. A request the allowance refuses stays waiting, and so do the
   ones after it.

Nothing here starts, stops or creates a cloud resource: the operator starts and stops sessions. The
worker holds two credentials, both from the operator's environment and read in this process only:
the runtime database role, and the generation bucket's key, whose request set can put, get and list,
and delete nothing.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from exulanica_pieces.canonical import Refused
from exulanica_pieces.records import (
    POSTPROCESS_VERSION,
    build_job,
    cache_key,
    read_job,
    read_request,
)

from exulanica.db.session import Database
from exulanica.generation import batches, entries
from exulanica.generation.bucket import GenerationBucket
from exulanica.generation.entries import CLOCK_ALLOWANCE, EntryRefused
from exulanica.generation.pieces import PieceRefused, store_piece, stored_bytes
from exulanica.generation.requests import GPU_PROVIDER, GenerationCatalogs
from exulanica.generation.session import SessionState, session_state
from exulanica.models.spending import SpendingRefused, SpendingRequest, SpendingTicket
from exulanica.models.usage import CallUsage, CostBasis
from exulanica.spending.ledger import DurableSpending
from exulanica.things.kinds import ThingKind
from exulanica.world.style_pack_library import StylePackLibrary

__all__ = ["SPENDING_ROLE", "PieceGenerationWorker"]

_LOG = logging.getLogger(__name__)

#: The role a piece request's reservation is admitted under in the spending ledger.
SPENDING_ROLE = "piece_generation"
_BASES = {"reported": CostBasis.REPORTED, "unknown": CostBasis.UNKNOWN}


def _key(piece_request_id: uuid.UUID) -> str:
    """A request's spending key: its own id, so a replayed admission is the same reservation."""
    return f"piece:{piece_request_id}"


def _instant(text: str) -> datetime:
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def _job_stop(job_canonical: str) -> int:
    return int(read_job(job_canonical.encode("ascii"))["stop"]["stop_at_seconds"])


@dataclass
class PieceGenerationWorker:
    """One pass at a time over the served workspaces; every collaborator is injected."""

    database: Database
    bucket: GenerationBucket
    pieces_store: Any
    spending: DurableSpending
    catalogs: GenerationCatalogs
    library: StylePackLibrary
    shipped: Mapping[tuple[str, int], ThingKind]
    workspaces: Callable[[], Iterable[uuid.UUID]]
    store_bound: int
    now: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))

    def run_once(self) -> dict[str, Any]:
        """One pass; returns what it did, by workspace, for the worker's log."""
        now = self.now()
        with self.database.unscoped() as connection:
            session = batches.open_session(connection, now)
        state: SessionState = "off"
        beat = None
        if session is not None:
            try:
                beat = entries.latest_beat(self.bucket, session.session_sha256)
            except Exception as failure:
                # A heartbeat that does not read leaves the session not warm: nothing is queued,
                # and following and settling, which need no heartbeat, go on.
                _LOG.warning(
                    "the session's heartbeat does not read: %s", type(failure).__qualname__
                )
                state = "starting"
            else:
                state = session_state(
                    registered=True, window_ends_at=session.window_ends_at, beat=beat, now=now
                )
        report: dict[str, Any] = {"session": state, "workspaces": {}}
        for workspace_id in sorted(self.workspaces()):
            try:
                with self.database.session(workspace_id) as connection:
                    # Read for each workspace, so a slow pass never dates a later one's caps early.
                    done = self._serve(connection, workspace_id, session, state, beat, self.now())
            except Exception as failure:  # one workspace's fault never stops the others
                _LOG.warning(
                    "workspace %s was not served this pass: %s",
                    workspace_id,
                    type(failure).__qualname__,
                )
                continue
            if done:
                report["workspaces"][str(workspace_id)] = done
        return report

    def _serve(
        self,
        connection: Any,
        workspace_id: uuid.UUID,
        session: batches.OpenSession | None,
        state: SessionState,
        beat: Mapping[str, Any] | None,
        now: datetime,
    ) -> dict[str, Any]:
        # A request a deletion cancelled while queued: its entry is withdrawn first, so a session
        # that has not claimed it never does, and only then is its settlement decided.
        for piece_batch_id in batches.cancelled_batches(connection, workspace_id):
            entries.write_withdrawn(self.bucket, entries.entry_id(piece_batch_id), now)
        batches.decide_cancelled(connection, workspace_id)
        ended = self._follow(connection, workspace_id, now)
        settled = self._settle_decided(connection, workspace_id, now)
        answered: list[str] = []
        queued = None
        if state == "warm" and session is not None and beat is not None:
            answered, queued = self._queue(connection, workspace_id, session, beat, now)
        return {
            key: value
            for key, value in (
                ("ended", ended),
                ("settled", settled),
                ("answered", answered),
                ("queued", queued),
            )
            if value
        }

    # -- following --------------------------------------------------------------------------------

    def _follow(self, connection: Any, workspace_id: uuid.UUID, now: datetime) -> list[str]:
        ended = []
        for batch in batches.batches_in_flight(connection, workspace_id):
            try:
                if self._follow_one(connection, workspace_id, batch, now):
                    ended.append(str(batch.piece_batch_id))
            except batches.BatchNotOpen:
                continue
            except Exception as failure:  # one batch's fault never stops the workspace's others
                _LOG.warning(
                    "batch %s was not followed this pass: %s",
                    batch.piece_batch_id,
                    type(failure).__qualname__,
                )
        return ended

    def _follow_one(
        self, connection: Any, workspace_id: uuid.UUID, batch: batches.BatchInFlight, now: datetime
    ) -> bool:
        went_to = batches.session_by_id(connection, batch.generation_session_id)
        if went_to is None:
            return False
        entry = entries.entry_id(batch.piece_batch_id)
        named = {
            "job_sha256": batch.job_sha256,
            "session_sha256": went_to.session_sha256,
            "queued_at": batch.queued_at,
        }
        # Read before the markers: a session whose heartbeat says it ended wrote every claim and
        # done marker it ever will before that heartbeat, and no other session takes its entries.
        ended = self._session_ended(went_to.session_sha256)
        try:
            marker = entries.done(self.bucket, entry, **named)
            claim = None if marker is not None else entries.claim(self.bucket, entry, **named)
        except EntryRefused as refused:
            # A marker at this entry's name that is not this entry's: whether a session ran the
            # entry is not known, so its reservations stay whole until reconciled.
            self._end(connection, workspace_id, batch, "refused", now, refused.code, "unknown")
            return True
        if marker is not None:
            self._ended(connection, workspace_id, batch, went_to, marker)
            return True
        if claim is not None:
            claimed_at = _instant(claim["at"])
            batches.record_claim(connection, workspace_id, batch.piece_batch_id, claimed_at)
            deadline = claimed_at + timedelta(seconds=_job_stop(batch.job_canonical))
            if now > deadline + CLOCK_ALLOWANCE:
                self._end(connection, workspace_id, batch, "expired", now, None, "unknown")
                return True
            return False
        if ended or now > batch.not_after + CLOCK_ALLOWANCE:
            # No session took the entry, and none will: only its own session may, and that one has
            # ended or its deadline has passed. Nothing of it was run.
            self._end(connection, workspace_id, batch, "expired", now, None, "not_sent")
            return True
        return False

    def _session_ended(self, session_sha256: str) -> bool:
        """Whether the session's last heartbeat says it ended; a heartbeat that does not read
        says nothing, and the batch waits for its deadline."""
        try:
            beat = entries.latest_beat(self.bucket, session_sha256)
        except Exception as failure:
            _LOG.warning("a heartbeat does not read: %s", type(failure).__qualname__)
            return False
        return beat is not None and str(beat.get("state", "")).startswith("ended")

    def _end(
        self,
        connection: Any,
        workspace_id: uuid.UUID,
        batch: batches.BatchInFlight,
        state: str,
        ended_at: datetime,
        refusal: str | None,
        basis: str,
    ) -> None:
        settlements = {
            request.piece_request_id: (
                basis,
                request.worst_case_usd if basis == "unknown" else Decimal(0),
            )
            for request in batch.requests
        }
        batches.end_batch(
            connection,
            workspace_id,
            batch,
            state=state,
            ended_at=ended_at,
            settlements=settlements,
            refusal=refusal,
        )

    def _ended(
        self,
        connection: Any,
        workspace_id: uuid.UUID,
        batch: batches.BatchInFlight,
        session: batches.OpenSession,
        marker: Mapping[str, Any],
    ) -> None:
        ended_at = _instant(marker["ended_at"])
        batches.record_claim(
            connection, workspace_id, batch.piece_batch_id, _instant(marker["claimed_at"])
        )
        if "refused" in marker:
            # The session refused the entry before running any of it. Its reason stays in its done
            # marker in the bucket; the row names the kind.
            self._end(
                connection, workspace_id, batch, "refused", ended_at, "entry_refused", "not_sent"
            )
            return
        settlements = self._measured(batch, session, marker)
        if settlements is None:
            # Milliseconds past the job's own stop: the marker is not a measurement this session
            # could have made, so each request's whole reservation stays until reconciled.
            _LOG.warning(
                "batch %s: its done marker states more time than its stop", batch.piece_batch_id
            )
            settlements = {
                request.piece_request_id: ("unknown", request.worst_case_usd)
                for request in batch.requests
            }
        documents = {request.request_sha256: request for request in batch.requests}
        try:
            try:
                read = {
                    digest: _request_document(request, self.catalogs)
                    for digest, request in documents.items()
                }
            except Refused as refused:
                # The catalogs changed under the batch (its budgets digest): its pieces cannot be
                # checked against what was asked, so none is kept.
                raise EntryRefused("request_unreadable", str(refused)) from refused
            found = entries.outputs(self.bucket, marker, read)
        except EntryRefused as refused:
            # The GPU time was spent, so it is still settled; no output is kept.
            batches.end_batch(
                connection,
                workspace_id,
                batch,
                state="refused",
                ended_at=ended_at,
                settlements=settlements,
                refusal=refused.code,
            )
            return
        kept = []
        held = stored_bytes(self.pieces_store)
        for output in found:
            try:
                stored = store_piece(
                    self.pieces_store,
                    request_raw=documents[output.request_sha256].request_canonical.encode("ascii"),
                    receipt_raw=output.receipt,
                    piece=output.piece,
                    components_sha256=session.components_sha256,
                    catalogs=self.catalogs,
                    library=self.library,
                    shipped=self.shipped,
                    bound=self.store_bound,
                    held=held,
                )
            except PieceRefused as refused:
                _LOG.warning(
                    "a generated piece was not kept: %s (%s)", refused.code, output.piece_sha256
                )
                continue
            if stored.written:
                held += len(output.piece)
            kept.append(
                batches.KeptOutput(
                    output=output,
                    cache_key=stored.admitted.cache_key,
                    components_sha256=session.components_sha256,
                    postprocess_version=POSTPROCESS_VERSION,
                )
            )
        batches.end_batch(
            connection,
            workspace_id,
            batch,
            state="done",
            ended_at=ended_at,
            settlements=settlements,
            outputs=kept,
        )

    def _measured(
        self,
        batch: batches.BatchInFlight,
        session: batches.OpenSession,
        marker: Mapping[str, Any],
    ) -> dict[uuid.UUID, tuple[str, Decimal]] | None:
        """Each request's settlement from the done marker: the measured time of its digest at the
        rate, at most its reservation, charged once to the oldest request holding the digest. None
        when the marker states more time, over all its digests, than the job's stop allows, or when
        the deployed compute catalog no longer prices the session's GPU."""
        compute = self.catalogs.compute.entries.get(session.compute_key)
        if compute is None:
            _LOG.warning("no compute catalog entry prices %s", session.compute_key)
            return None
        stop_milliseconds = _job_stop(batch.job_canonical) * 1000
        milliseconds = marker["request_milliseconds"]
        if sum(int(value) for value in milliseconds.values()) > stop_milliseconds:
            return None
        settlements: dict[uuid.UUID, tuple[str, Decimal]] = {}
        charged: set[str] = set()
        for request in sorted(
            batch.requests, key=lambda r: (r.requested_at, str(r.piece_request_id))
        ):
            usd = Decimal(0)
            if request.request_sha256 not in charged:
                charged.add(request.request_sha256)
                measured = int(milliseconds.get(request.request_sha256, 0))
                usd = min(compute.usd_for_milliseconds(measured), request.worst_case_usd)
            settlements[request.piece_request_id] = ("reported", usd)
        return settlements

    # -- settling ---------------------------------------------------------------------------------

    def _settle_decided(self, connection: Any, workspace_id: uuid.UUID, now: datetime) -> int:
        gate = self.spending.for_workspace(workspace_id)
        settled = 0
        for decided in batches.unsettled(connection, workspace_id):
            ticket = SpendingTicket(
                reservation_id=decided.reservation_id,
                authority_id=decided.reservation_authority_id,
                workspace_id=workspace_id,
                usd=Decimal(0),
                key=_key(decided.piece_request_id),
                holder=decided.reservation_holder,
            )
            try:
                if _reservation_open(connection, workspace_id, decided.reservation_id):
                    if decided.basis == "not_sent":
                        gate.release(ticket)
                    else:
                        gate.settle(
                            ticket,
                            CallUsage(
                                role=SPENDING_ROLE,
                                model_id=GPU_PROVIDER,
                                provider=GPU_PROVIDER,
                                prompt_tokens=0,
                                completion_tokens=0,
                                reasoning_tokens=0,
                                cached_prompt_tokens=0,
                                usd=decided.usd,
                                cost_basis=_BASES[decided.basis],
                            ),
                        )
            except Exception as failure:  # retried on the next pass
                _LOG.warning(
                    "the settlement of %s waits for the next pass: %s",
                    decided.piece_request_id,
                    type(failure).__qualname__,
                )
                continue
            batches.mark_settled(connection, workspace_id, decided.piece_request_id, now)
            settled += 1
        return settled

    # -- answering and queueing -------------------------------------------------------------------

    def _queue(
        self,
        connection: Any,
        workspace_id: uuid.UUID,
        session: batches.OpenSession,
        beat: Mapping[str, Any],
        now: datetime,
    ) -> tuple[list[str], str | None]:
        if batches.batches_in_flight(connection, workspace_id):
            return [], None
        waiting = batches.waiting_requests(connection, workspace_id)
        answered: list[str] = []
        rest = []
        for row in waiting:
            key = cache_key(row["request_sha256"], session.components_sha256, POSTPROCESS_VERSION)
            cached = [
                piece
                for piece in batches.cached_pieces(connection, key)
                if piece["variant"] < int(row["variants"])
            ]
            if {piece["variant"] for piece in cached} == set(range(int(row["variants"]))):
                end = batches.answer_from_cache(
                    connection, workspace_id, row["piece_request_id"], cache_key=key, cached=cached
                )
                if end is not None:
                    answered.append(str(row["piece_request_id"]))
                continue
            if not self._readable(connection, workspace_id, row, session):
                continue
            rest.append(row)
        if session.compute_key not in self.catalogs.compute.entries:
            # The session's GPU is no longer priced: nothing is admitted against it; the requests
            # wait for a session the catalog prices.
            _LOG.warning("no compute catalog entry prices %s", session.compute_key)
            return answered, None
        ends_at = min(
            _instant(beat["started_at"]) + timedelta(seconds=session.stop_seconds),
            session.window_ends_at,
        )
        chosen = self._fitting(rest, session, (ends_at - now - CLOCK_ALLOWANCE).total_seconds())
        if not chosen:
            return answered, None
        compute = self.catalogs.compute.entries[session.compute_key]
        gate = self.spending.for_workspace(workspace_id)
        admitted: list[tuple[dict[str, Any], SpendingTicket]] = []
        for row in chosen:
            try:
                ticket = gate.admit(
                    SpendingRequest(
                        provider=GPU_PROVIDER,
                        model_id=session.compute_key,
                        role=SPENDING_ROLE,
                        usd=Decimal(row["worst_case_usd"]),
                        key=_key(row["piece_request_id"]),
                    )
                )
            except SpendingRefused as refused:
                _LOG.info("a piece request waits: %s", refused.reason)
                break
            admitted.append((row, ticket))
        if not admitted:
            return answered, None
        try:
            job_raw, requests = self._job([row for row, _ in admitted], session, compute)
        except Refused as failure:
            # Each request read on its own above; a job that still does not build sends nothing.
            _LOG.warning("a job was not built: %s", failure)
            for _row, ticket in admitted:
                gate.release(ticket)
            return answered, None
        try:
            piece_batch_id = batches.record_batch(
                connection,
                workspace_id,
                generation_session_id=session.generation_session_id,
                job_raw=job_raw,
                queued_at=now,
                not_after=ends_at,
                queued=[
                    batches.QueuedReservation(
                        piece_request_id=row["piece_request_id"],
                        reservation_id=ticket.reservation_id,
                        authority_id=ticket.authority_id,
                        holder=ticket.holder or "",
                    )
                    for row, ticket in admitted
                ],
            )
        except batches.PieceRequestNotWaiting:
            # Nothing was written or sent: each reservation is released as never sent.
            for _row, ticket in admitted:
                gate.release(ticket)
            return answered, None
        entry = entries.entry_id(piece_batch_id)
        try:
            for _row, ticket in admitted:
                gate.dispatch(ticket)
            entries.write_files(self.bucket, entry, job_raw, requests)
        except Exception as failure:  # no session takes an entry without its ready.json
            _LOG.warning("a batch was not sent: %s", type(failure).__qualname__)
            self._not_sent(connection, workspace_id, piece_batch_id, now)
            return answered, None
        # ready.json last, and only while the batch is still queued, under the workspace's lock: a
        # deletion is then either before it (nothing is offered) or after it (the entry is
        # withdrawn). A failure writing it may still have reached the bucket, so the batch stays
        # queued and is followed (its claim, done marker, session or not_after decide it).
        try:
            with batches.while_queued(connection, workspace_id, piece_batch_id) as queued:
                if queued:
                    entries.write_ready(
                        self.bucket,
                        entry,
                        job_raw,
                        requests,
                        session_sha256=session.session_sha256,
                        queued_at=now,
                        not_after=ends_at,
                    )
        except Exception as failure:
            _LOG.warning(
                "a batch's ready.json may not have been written: %s", type(failure).__qualname__
            )
            return answered, entry
        if not queued:
            # Deleted between its record and its offer: nothing reached a session.
            batches.decide_cancelled(connection, workspace_id, unsent={piece_batch_id})
            return answered, None
        return answered, entry

    def _readable(
        self,
        connection: Any,
        workspace_id: uuid.UUID,
        row: Mapping[str, Any],
        session: batches.OpenSession,
    ) -> bool:
        """Whether a waiting request reads under the catalogs this server deploys and takes the
        session's route. One that no longer reads ends failed request_unreadable; one for another
        route waits for a session of that route (session open registers none)."""
        try:
            request = read_request(row["request_canonical"].encode("ascii"), self.catalogs.budgets)
        except Refused:
            batches.fail_unreadable(connection, workspace_id, row["piece_request_id"])
            return False
        return request["route"] == session.route

    def _fitting(
        self, rows: list[dict[str, Any]], session: batches.OpenSession, seconds_left: float
    ) -> list[dict[str, Any]]:
        """The oldest waiting requests whose one job the session can still finish: its stop (the
        bounding item seconds for one item set per request digest, and the job's stop factor) inside
        the session's time left."""
        compute = self.catalogs.compute.entries[session.compute_key]
        chosen: list[dict[str, Any]] = []
        digests: dict[str, int] = {}
        for row in rows:
            trial = dict(digests)
            trial.setdefault(row["request_sha256"], int(row["variants"]))
            stop = sum(trial.values()) * compute.item_seconds_bound * 3 // 2
            if stop > seconds_left:
                break
            digests = trial
            chosen.append(row)
        return chosen

    def _job(
        self, rows: list[dict[str, Any]], session: batches.OpenSession, compute: Any
    ) -> tuple[bytes, list[bytes]]:
        """One job with one item set per request digest, whichever requests hold it."""
        requests: dict[str, bytes] = {}
        for row in rows:
            requests.setdefault(row["request_sha256"], row["request_canonical"].encode("ascii"))
        items = sum(
            _request_document_raw(raw, self.catalogs)["variants"] for raw in requests.values()
        )
        job_raw = build_job(
            route=session.route,
            components_sha256=session.components_sha256,
            requests=list(requests.values()),
            code_sha256=session.code_sha256,
            container=session.container,
            estimate_seconds=items * compute.item_seconds_bound,
            budgets=self.catalogs.budgets,
        )
        return job_raw, list(requests.values())

    def _not_sent(
        self, connection: Any, workspace_id: uuid.UUID, piece_batch_id: uuid.UUID, now: datetime
    ) -> None:
        for batch in batches.batches_in_flight(connection, workspace_id):
            if batch.piece_batch_id == piece_batch_id:
                self._end(connection, workspace_id, batch, "refused", now, "not_sent", "not_sent")
        self._settle_decided(connection, workspace_id, now)


def _request_document(request: batches.QueuedRequest, catalogs: GenerationCatalogs) -> Any:
    return _request_document_raw(request.request_canonical.encode("ascii"), catalogs)


def _request_document_raw(raw: bytes, catalogs: GenerationCatalogs) -> Any:
    return read_request(raw, catalogs.budgets)


def _reservation_open(connection: Any, workspace_id: uuid.UUID, reservation_id: uuid.UUID) -> bool:
    """Whether the spending authority still holds the reservation open; one it already settled or
    released was taken by an earlier pass whose mark did not commit."""
    row = connection.execute(
        "select state from spending_reservation where workspace_id = %s and reservation_id = %s",
        (workspace_id, reservation_id),
    ).fetchone()
    if row is None:
        return False
    state = row["state"] if isinstance(row, Mapping) else row[0]
    return state in ("admitted", "dispatched")
