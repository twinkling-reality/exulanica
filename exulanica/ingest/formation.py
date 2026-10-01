"""The provenance ledger, projected into the phases the interface names.

``interaction-model.md`` 8.1 is the rule this module exists to keep: "Every visual formation
state is paired with a factual label naming the REAL pipeline stage and the REAL unit of
progress. There is no synthetic progress bar and no invented percentage." So every number below
is counted from ``pipeline_event`` rows that a stage actually wrote, and a number that cannot be
counted is absent rather than estimated.

**The two vocabularies are not the same and this is where they meet.** The ledger records the
stages this pipeline has: ``intake``, ``rendition``, ``vision``, ``scene_group``. The interface
names the stages a person can see: media extraction, entity indexing, continuity search. The
mapping is one to many in one direction and empty in the other, and both halves are honest:

*   ``intake`` and ``rendition`` are the two halves of one visible stage. A visitor does not have
    a concept of a rendition and would not be better off with one.
*   ``camera_recovery`` and ``reconstruction`` are visible stages that NOTHING PRODUCES. They
    belong to the offline reconstruction job, which does not run. They are absent from the stream
    rather than emitted as instantly complete, because a stage reported as done that never ran is
    the exact shape of the dishonesty this file is written against.

**Counters are a fold, not a query per event.** ``done`` at any point in the stream is the number
of runs that had finished that phase by that point, computed by walking the events in order. That
makes a resumed stream report the same numbers as an uninterrupted one, which a per-event
``count(*)`` would not: a client that reconnected would see history recomputed against the
present and watch a counter jump backwards or forwards for no reason a user could explain.

**Detections are a snapshot and say so.** How many people, objects and places have been found is
not derivable from the ledger, because an occurrence is not a ledger event. It is counted once
per projection and attached to the last event of that projection only. The client treats
detections as accumulating and carries the last value forward, so a stream of events that mostly
do not carry one is the normal case rather than a gap.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass, field
from typing import Any, Final

import psycopg

__all__ = [
    "FORMATION_OUTCOMES",
    "FORMATION_STAGES",
    "PHASE_OF_STAGE",
    "RECEIVED_TOKEN",
    "FormationEvent",
    "project_formation",
]

#: The visible stages, in order. **This list is duplicated in
#: ``web/packages/formation/src/events.ts`` and the two must agree**, because the client
#: rejects an event whose phase sorts before the one it is showing. The duplication is pinned by
#: ``tests/test_formation_stream.py``, which parses the TypeScript and compares, rather than by
#: this comment.
FORMATION_STAGES: Final[tuple[str, ...]] = (
    "received",
    "media_extraction",
    "camera_recovery",
    "reconstruction",
    "entity_indexing",
    "continuity_search",
)

#: Terminal states. ``partial`` and ``failed`` are outcomes rather than error screens: 8.3 says
#: failure leaves the partial region in place, and that partial usability is the point.
FORMATION_OUTCOMES: Final[tuple[str, ...]] = (
    "review_required",
    "ready",
    "partial",
    "failed",
)

#: Backend stage key to visible phase. A stage absent from this mapping produces no event, which
#: is how a stage nobody has a concept of stays out of a stream nobody would understand.
PHASE_OF_STAGE: Final[dict[str, str]] = {
    "intake": "media_extraction",
    "rendition": "media_extraction",
    "vision": "entity_indexing",
    "scene_group": "continuity_search",
}

#: The stage whose success MEANS a run has finished a phase. ``media_extraction`` counts
#: renditions rather than intakes, because a photograph whose bytes were hashed but not yet
#: decoded has not finished being extracted, and counting the earlier half would report the stage
#: done while half its work was outstanding.
_COMPLETING_STAGE: Final[dict[str, str]] = {
    "media_extraction": "rendition",
    "entity_indexing": "vision",
    "continuity_search": "scene_group",
}

#: The resume token of the synthetic first event.
#:
#: ``received`` is not a ledger row: it is the batch opening, and the batch has no event of its
#: own. The token is a fixed string rather than a uuid so that the two kinds of token cannot be
#: confused, and so that a client resuming from it is unambiguously asking for "everything the
#: ledger has recorded" rather than for events after some particular uuid.
RECEIVED_TOKEN: Final = "received"


@dataclass(frozen=True, slots=True)
class FormationEvent:
    """One event as the interface consumes it. Field names are the client's, not the schema's."""

    event_id: str
    capture_id: str
    phase: str
    stage_index: int
    #: Server wall clock in milliseconds. Elapsed time is a difference of two of these, never a
    #: reading of the client's own clock.
    at: int
    counters: dict[str, Any] | None = None
    detections: dict[str, int] | None = None
    outcome: dict[str, Any] | None = None
    photographs: int | None = None
    note: str | None = None

    def as_payload(self) -> dict[str, Any]:
        """The JSON the client parses. Absent fields are omitted rather than sent as null.

        Omitted rather than null because the client's reducer reads ``event.counters ?? previous``
        and an explicit null is the same as absent to it, so sending one would be sending a value
        that means nothing and costs bytes on every event of a long stream.
        """
        payload: dict[str, Any] = {
            "eventId": self.event_id,
            "captureId": self.capture_id,
            "phase": self.phase,
            "stageIndex": self.stage_index,
            "at": self.at,
        }
        if self.counters is not None:
            payload["counters"] = self.counters
        if self.detections is not None:
            payload["detections"] = self.detections
        if self.outcome is not None:
            payload["outcome"] = self.outcome
        if self.photographs is not None:
            payload["photographs"] = self.photographs
        if self.note is not None:
            payload["note"] = self.note
        return payload


@dataclass
class _Progress:
    """Runs that have completed each phase, as the fold walks the ledger."""

    completed: dict[str, set[uuid.UUID]] = field(default_factory=dict)

    def record(self, phase: str, run_id: uuid.UUID) -> int:
        done = self.completed.setdefault(phase, set())
        done.add(run_id)
        return len(done)


def _ms(value: dt.datetime | None) -> int:
    """A timestamp in milliseconds. Never the local clock: this is the server's own reading."""
    return 0 if value is None else int(value.timestamp() * 1000)


def project_formation(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    batch_id: uuid.UUID,
    *,
    after: str | None = None,
) -> list[FormationEvent]:
    """Every formation event for this batch after ``after``, in order.

    ``after`` is None for a fresh subscription, :data:`RECEIVED_TOKEN` to skip only the synthetic
    first event, or a ledger ``event_id`` to resume mid-stream.

    The batch is read first and its absence is an empty list rather than an exception. Row-level
    security means a batch in another workspace and a batch that never existed are the same
    observation from here, which is the property the whole surface is built on: the API is not an
    existence oracle.
    """
    batch = connection.execute(
        "select batch_id, declared_size, started_at, ended_at, status from intake_batch "
        "where workspace_id = %s and batch_id = %s",
        (workspace_id, batch_id),
    ).fetchone()
    if batch is None:
        return []

    events: list[FormationEvent] = []
    key = str(batch_id)

    if after is None:
        events.append(
            FormationEvent(
                event_id=RECEIVED_TOKEN,
                capture_id=key,
                phase="received",
                stage_index=0,
                at=_ms(batch["started_at"]),
                # None while the source is still being enumerated, which is a real state and the
                # reason the column is nullable. A client shown a total before one was counted
                # would render a fraction of a number nobody had measured.
                photographs=batch["declared_size"],
            )
        )

    # Ordered by event_id, which is a uuidv7 and therefore time-ordered in its own bytes. That is
    # what lets a resume be a single `>` comparison across every run in the batch rather than a
    # per-run cursor. `pipeline_event` carries no workspace_id, so the join through `pipeline_run`
    # is what scopes this: that table's own policy is the filter.
    resume = None if after in (None, RECEIVED_TOKEN) else after
    rows = connection.execute(
        "select pe.event_id, pe.run_id, pe.type, pe.stage_key, pe.error_class, "
        "  pe.error_message, pe.occurred_at "
        "from pipeline_event pe join pipeline_run pr on pr.run_id = pe.run_id "
        "where pr.workspace_id = %s and pr.batch_id = %s "
        + ("and pe.event_id > %s " if resume else "")
        + "order by pe.event_id",
        (workspace_id, batch_id, resume) if resume else (workspace_id, batch_id),
    ).fetchall()

    # The fold is over EVERY event in the batch, not only those after the resume point, because a
    # counter is a count of what has happened and a resumed stream must agree with an
    # uninterrupted one. Only the events after the resume point are emitted.
    progress = _Progress()
    if resume:
        for row in connection.execute(
            "select pe.run_id, pe.type, pe.stage_key from pipeline_event pe "
            "join pipeline_run pr on pr.run_id = pe.run_id "
            "where pr.workspace_id = %s and pr.batch_id = %s and pe.event_id <= %s "
            "order by pe.event_id",
            (workspace_id, batch_id, resume),
        ).fetchall():
            _advance(progress, row)

    for row in rows:
        event = _event_for(row, progress, key, batch["declared_size"])
        if event is not None:
            events.append(event)

    if batch["ended_at"] is not None:
        events.append(_terminal(connection, workspace_id, batch, key))

    if events:
        detections = _detections(connection, workspace_id, batch_id)
        events[-1] = _with_detections(events[-1], detections)
    return events


def _advance(progress: _Progress, row: Any) -> str | None:
    """Fold one ledger row into the running counts, and report which phase it completed.

    ``stage_reused`` counts exactly as much as ``stage_succeeded``, because the counter answers
    "how many photographs have finished this stage" and not "how much work did the machine do".
    A photograph whose rendition already existed IS extracted, and a second ingest that reported
    three of six would be reporting a corpus that is entirely ready as half failed.
    """
    if row["type"] not in ("stage_succeeded", "stage_reused"):
        return None
    phase = PHASE_OF_STAGE.get(row["stage_key"] or "")
    if phase is None or _COMPLETING_STAGE[phase] != row["stage_key"]:
        return None
    progress.record(phase, row["run_id"])
    return phase


def _event_for(
    row: Any, progress: _Progress, key: str, total: int | None
) -> FormationEvent | None:
    """One ledger row becomes at most one formation event.

    Most rows become nothing, and that is correct rather than lossy. ``artifact_written``,
    ``input_resolved`` and ``assertion_emitted`` are the Assembly Replay's material and say
    nothing a visitor watching a region form could act on; a stream that carried them would be a
    log with a progress bar drawn on it. The two that do become events are a stage finishing and
    a stage failing, which are the two things a person watching is waiting to hear.
    """
    stage_key = row["stage_key"] or ""
    phase = PHASE_OF_STAGE.get(stage_key)
    if phase is None:
        return None
    index = FORMATION_STAGES.index(phase)
    at = _ms(row["occurred_at"])

    if row["type"] in ("stage_failed", "stage_unavailable", "stage_missing"):
        # A failure is an event in the stream and carries the pipeline's own message in the slot
        # marked as coming from the pipeline. The honest label is written client-side from the
        # numbers; this is the note beside it, never merged into it.
        return FormationEvent(
            event_id=str(row["event_id"]),
            capture_id=key,
            phase=phase,
            stage_index=index,
            at=at,
            note=f"{row['error_class']}: {row['error_message']}"
            if row["error_class"]
            else "a stage failed",
        )

    completed = _advance(progress, row)
    if completed is None:
        return None

    # `continuity_search` is one run for the whole batch rather than one per photograph, so a
    # done-of-total over it would be "1 of 1", which is a fraction that says nothing. It reports
    # no counters and renders as the breathing, elapsed-time state the client already has for a
    # stage that cannot count itself.
    # `total` is the batch's declared size once the source has been counted, and None before.
    # Withholding it after the walk would be withholding a number that exists: a person watching
    # 6 photographs extract is entitled to "4 of 6" rather than "4". Before the walk finishes
    # there is genuinely no total, and that is the case the nullable column and the nullable
    # field both exist for.
    counters = (
        None
        if completed == "continuity_search"
        else {"done": len(progress.completed[completed]), "total": total}
    )
    return FormationEvent(
        event_id=str(row["event_id"]),
        capture_id=key,
        phase=completed,
        stage_index=index,
        at=at,
        counters=counters,
    )


def _with_detections(event: FormationEvent, detections: dict[str, int] | None) -> FormationEvent:
    if detections is None:
        return event
    return FormationEvent(
        event_id=event.event_id,
        capture_id=event.capture_id,
        phase=event.phase,
        stage_index=event.stage_index,
        at=event.at,
        counters=event.counters,
        detections=detections,
        outcome=event.outcome,
        photographs=event.photographs,
        note=event.note,
    )


def _detections(
    connection: psycopg.Connection, workspace_id: uuid.UUID, batch_id: uuid.UUID
) -> dict[str, int] | None:
    """People, objects and places found so far in this batch's photographs.

    One mote is drawn per detection that has actually landed, so this counts occurrence rows and
    not anything a stage intended to produce. Classes with no shape in the Atlas are excluded
    rather than folded into the nearest bucket: a voice is not an object.
    """
    rows = connection.execute(
        "select o.class, count(*) as n from occurrence o "
        "join capture c on c.capture_id = o.capture_id "
        "join pipeline_run pr on pr.capture_id = c.capture_id "
        "where o.workspace_id = %s and pr.batch_id = %s and c.deleted_at is null "
        "group by o.class",
        (workspace_id, batch_id),
    ).fetchall()
    if not rows:
        return None
    counts = {row["class"]: int(row["n"]) for row in rows}
    return {
        "people": counts.get("person", 0),
        "objects": counts.get("object", 0),
        "places": counts.get("place", 0),
    }


def _terminal(
    connection: psycopg.Connection, workspace_id: uuid.UUID, batch: Any, key: str
) -> FormationEvent:
    """The one event that says the batch is over, and what it left behind.

    ``photographsAvailable`` is what the user can open right now, whatever happened to the
    geometry, and it is counted from live captures rather than from the declared size. A batch
    that failed halfway still has photographs in it, and saying so is the difference between a
    partial result and an error screen.
    """
    available = connection.execute(
        "select count(distinct pr.capture_id) as n from pipeline_run pr "
        "join capture c on c.capture_id = pr.capture_id "
        "where pr.workspace_id = %s and pr.batch_id = %s and c.deleted_at is null",
        (workspace_id, batch["batch_id"]),
    ).fetchone()
    open_questions = connection.execute(
        "select count(*) as n from match_proposal where workspace_id = %s and outcome = 'surfaced'",
        (workspace_id,),
    ).fetchone()
    stopped = connection.execute(
        "select pe.type, pe.stage_key, pe.error_class from pipeline_event pe "
        "join pipeline_run pr on pr.run_id = pe.run_id "
        "where pr.workspace_id = %s and pr.batch_id = %s "
        "and pe.type in ('stage_failed','stage_unavailable','stage_missing') "
        "order by pe.event_id desc limit 1",
        (workspace_id, batch["batch_id"]),
    ).fetchone()

    status = batch["status"]
    questions = int(open_questions["n"]) if open_questions else 0
    if status == "succeeded":
        phase = "review_required" if questions > 0 else "ready"
    elif status == "partial":
        phase = "partial"
    else:
        phase = "failed"

    outcome: dict[str, Any] = {
        # The rung the regions actually earned. Nothing reconstructs, so nothing earned better
        # than rung 4, and claiming otherwise would be claiming geometry that was never built.
        # When reconstruction lands this reads what the pipeline recorded.
        "rung": 4,
        "openQuestions": questions,
        "photographsAvailable": int(available["n"]) if available else 0,
    }
    if phase in ("partial", "failed") and stopped is not None:
        stopped_phase = PHASE_OF_STAGE.get(stopped["stage_key"] or "")
        if stopped_phase is not None:
            outcome["stoppedAt"] = stopped_phase
        reason = {
            "stage_unavailable": "unavailable",
            "stage_missing": "missing",
        }.get(stopped["type"], "stage_error")
        outcome["reason"] = "cancelled" if status == "cancelled" else reason
    elif status == "cancelled":
        # Withdrawn photographs record no failed stage, so nothing above names a reason; the
        # batch's own status is the reason, and it is not a failure of the pipeline.
        outcome["reason"] = "cancelled"

    return FormationEvent(
        event_id=f"batch:{batch['batch_id']}:{status}",
        capture_id=key,
        phase=phase,
        stage_index=len(FORMATION_STAGES),
        at=_ms(batch["ended_at"]),
        outcome=outcome,
    )
