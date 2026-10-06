"""What the authorities recorded for a Companion plan's steps: the receipts, read, never asserted.

A plan (:mod:`exulanica.selection.action_plan`) is carried out by a client sending its steps to the
routes they name. This module is how the Companion learns what happened, and the only thing it
reports: each step's receipt as the authority stored it, read back from the authority's own
records, so an answer never states an effect that no record shows.

The plan a client sends back is used only to decide what to look up. Every fact in the answer is
read here, in the caller's workspace and world: a version edit whose base is the step's pinned base
and whose kind and subject are the step's, a style proposal by the id the step carried, the style
version applied from it. A plan altered on its way back can only make its own answer say less.

**A step is credited only with the record its own request produced.** Two requests sent from the
same bases make records of the same shape, and the second is refused as stale, so a record found by
its bases alone may be another writer's, even the same person's in another tab. Each step a client
sent therefore comes back with ``answer``: the status its own request was answered with and the
identity that answer named (an edit's ``edit_seq`` and ``state_sha256``, a control step's
``event_seq`` and ``document_sha256``, a configuration's ``revision`` and ``last_event_seq``, a
society's ``society_id``). A record is the step's receipt only when the answer names it and it
matches what the step asked; an edit or a playback control must also be the caller's own (bringing
people in is idempotent, so a request sent after another's is answered with the society already
there). A step sent back with no answer, or with a refusal, is never ``applied``; records others
made from its bases are listed in ``repeats``.

Per step:

*   ``applied``: the step's answer names the record and the record exists; ``receipts`` name it by
    the ids an accepted-operation reference stores, and ``matches_preview`` says whether what was
    recorded is what the preview showed.
*   ``not_applied``: no record of the step's own request, and the version still stands at the
    step's pinned base, so nothing happened. Sending the step again is still possible.
*   ``superseded``: no record of the step's own request, and the version moved past the pin:
    another change came first, and the step's request would now be refused as stale.
*   ``pending``: a later step of a compound plan, not yet prepared, so there is nothing to read.

Content-addressed state can recur (an undo returns a version to an earlier digest), and another
request can be sent from the same bases, so every other record of the step's shape is reported in
``repeats``, never folded into its receipt.

A simulation plan's steps are a chain, read the way they were sent: from the first step's pins,
each configuration is the control event its answer names that moved the control revision one past
the step's base to the step's mode and speed, and each control step is the ``manual_step`` event
its answer names that ran the society on from the minute and state the step before it left. The
first step the records do not show stops the reading; every step after it is ``not_applied``. A
chain that paused a playing world and stopped before playing it again leaves it paused: the answer
says so, offers ``play``, and nothing resumes it.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from typing import Any, Final

import psycopg

from exulanica.selection.action_plan import (
    ARRANGE,
    BRING_PEOPLE,
    CONTROL,
    CONTROL_STEP,
    MOVE,
    PLACE,
    REMOVE,
    STYLE_APPLY,
    STYLE_PREVIEW,
    UNDO,
    ClockReader,
    SimulationAction,
    document_sha256,
)
from exulanica.selection.validation import Session
from exulanica.world.object_edit_preview import read_only_snapshot
from exulanica.world.object_repository import WorldObjectRepository

__all__ = ["OUTCOME_PROFILE", "STEP_STATES", "InvalidOutcomeStep", "action_outcome"]

OUTCOME_PROFILE: Final = "exulanica.companion-action-outcome/v1"
#: Every state a step's outcome can be in.
STEP_STATES: Final = frozenset({"applied", "not_applied", "superseded", "pending"})


class InvalidOutcomeStep(ValueError):
    """A step that does not have the shape a plan gives it; answered 422, nothing read."""

    code = "invalid_outcome_step"


#: The edit kind each version-edit operation records, and whether a subject id names it.
_EDIT_KINDS: Final[Mapping[str, str]] = {
    PLACE: "add_object",
    MOVE: "move_object",
    REMOVE: "remove_object",
    UNDO: "undo",
    ARRANGE: "add_object",
}
#: The playback controls a simulation plan's chain is sent to.
_CONTROLS: Final = frozenset({CONTROL, CONTROL_STEP})


def action_outcome(
    connection: psycopg.Connection,
    request: Mapping[str, Any],
    session: Session,
    *,
    world_id: str,
    clock: ClockReader,
) -> dict[str, Any]:
    """The receipts the authorities recorded for ``request["steps"]``, and the plan's state.

    Raises ``UnknownWorldResource`` for a version this world does not hold, as every version read
    does, so a foreign version is answered as a write answers it. ``clock`` is read only for a
    simulation plan, whose people's state now is the clock read's, as the plan's bases were.
    """
    version_id = uuid.UUID(str(request["version_id"]))
    repository = WorldObjectRepository(connection, session.workspace_id, world_id=world_id)
    row = repository.edit_base_row(version_id)
    current: dict[str, Any] = {
        "state_sha256": row["state_sha256"],
        "edit_seq": int(row["edit_seq"]),
    }
    steps = request["steps"]
    answered: list[dict[str, Any]] = []
    alternatives: list[str] = []
    if any(step.get("operation") in _CONTROLS for step in steps):
        # One snapshot: the people's state now and the receipts the chain is read from agree.
        with read_only_snapshot(connection):
            read = clock()
            society = read.get("society")
            answered = _control_chain(connection, session, world_id, steps, read)
        current["society"] = society
        alternatives = _after_chain(steps, answered, society)
    else:
        answered = [
            _one_step(connection, session, world_id, version_id, step, steps, current)
            for step in steps
        ]
    return {
        "profile": OUTCOME_PROFILE,
        "world_id": world_id,
        "version_id": str(version_id),
        # Echoed, not verified: a client can name any digest. The receipts are the authorities'
        # records; matches_preview compares them with the preview the client sent back, so it
        # answers that client's question and is no proof of a plan this server made.
        "plan_sha256": request.get("plan_sha256"),
        "state": _plan_state(answered),
        "current": current,
        "steps": answered,
        "alternatives": alternatives,
    }


def _one_step(
    connection: psycopg.Connection,
    session: Session,
    world_id: str,
    version_id: uuid.UUID,
    step: Mapping[str, Any],
    steps: Sequence[Mapping[str, Any]],
    current: Mapping[str, Any],
) -> dict[str, Any]:
    """One step of an edit, appearance or bring-people plan, read from its authority's records."""
    operation = str(step.get("operation"))
    if step.get("state") == "pending" and operation not in (STYLE_APPLY,):
        return _step(step, "pending")
    if operation in _EDIT_KINDS:
        return _edit_step(connection, session, world_id, version_id, step, current)
    if operation == STYLE_PREVIEW:
        return _style_preview_step(connection, session, world_id, step)
    if operation == STYLE_APPLY:
        return _style_apply_step(connection, session, world_id, steps)
    if operation == BRING_PEOPLE:
        return _bring_people_step(connection, session, world_id, version_id, step)
    raise InvalidOutcomeStep(f"{operation!r} is not an operation a Companion plan names")


def _step(step: Mapping[str, Any], state: str, **found: Any) -> dict[str, Any]:
    assert state in STEP_STATES
    return {
        "index": step.get("index"),
        "operation": step.get("operation"),
        "state": state,
        #: Why a step reads as it does when the authority recorded a refusal (a style proposal's
        #: own status), or null.
        "code": found.get("code"),
        "receipts": found.get("receipts", []),
        "repeats": found.get("repeats", []),
        "matches_preview": found.get("matches_preview"),
    }


def _answer(step: Mapping[str, Any]) -> Mapping[str, Any] | None:
    """What the step's own request was answered with, when it was answered with success; None for
    a step never sent, sent back without its answer, or refused."""
    answer = step.get("answer")
    if not isinstance(answer, Mapping) or not 200 <= int(answer.get("status") or 0) < 300:
        return None
    return answer


def _plan_state(steps: Sequence[Mapping[str, Any]]) -> str:
    """``applied`` when every step that could run has; ``partial`` when some have; otherwise the
    first step's own state."""
    states = [step["state"] for step in steps if step["state"] != "pending"]
    if not states:
        return "not_applied"
    if all(state == "applied" for state in states):
        return "partial" if any(step["state"] == "pending" for step in steps) else "applied"
    if any(state == "applied" for state in states):
        return "partial"
    return states[0]


def _same(recorded: Any, expected: Any) -> bool:
    """Whether a recorded document is the one a preview showed, compared by digest."""
    if recorded is None or expected is None:
        return recorded is None and expected is None
    return document_sha256(recorded) == document_sha256(expected)


def _undone(step: Mapping[str, Any]) -> str | None:
    """The edit an undo step's preview said it would reverse, when it said one."""
    preview = (step.get("preview") or {}).get("document") or {}
    undoes = (preview.get("would_change") or {}).get("undoes") or {}
    edit_id = undoes.get("edit_id")
    return None if edit_id is None else str(edit_id)


def _expected_after(step: Mapping[str, Any]) -> list[Any]:
    """What the step's preview said each record would hold after it, in the order recorded."""
    preview = (step.get("preview") or {}).get("document") or {}
    if step.get("operation") == ARRANGE:
        return [item.get("document") for item in preview.get("would_add") or ()]
    change = preview.get("would_change") or {}
    if step.get("operation") == PLACE:
        return [change.get("document")]
    return [change.get("after")]


def _subjects(step: Mapping[str, Any]) -> list[str | None]:
    """The subject id each record the step makes names, in the order they are made."""
    operation = step.get("operation")
    if operation == ARRANGE:
        preview = (step.get("preview") or {}).get("document") or {}
        return [str(item.get("object_id")) for item in preview.get("would_add") or ()]
    if operation == PLACE:
        return [str(((step.get("body") or {}).get("placement") or {}).get("subject_id"))]
    if operation in (MOVE, REMOVE):
        return [str((step.get("bind") or {}).get("object_id"))]
    return [None]


def _edit_step(
    connection: psycopg.Connection,
    session: Session,
    world_id: str,
    version_id: uuid.UUID,
    step: Mapping[str, Any],
    current: Mapping[str, Any],
) -> dict[str, Any]:
    """A version edit step: its records, found by the pinned base, kind and subject."""
    with _client_shape(step):
        pins = step.get("pins") or {}
        base = str(pins.get("base_state_sha256"))
        after_seq = int(pins.get("edit_seq") or 0)
        kind = _EDIT_KINDS[str(step["operation"])]
        subjects = _subjects(step)
        if not subjects:
            # An arrangement step sent back without the preview that names what it adds.
            raise ValueError("the step names nothing it would record")
        undone = _undone(step) if step.get("operation") == UNDO else None
        expected = _expected_after(step)
        answer = _answer(step)
        named = None if answer is None else (int(answer["edit_seq"]), str(answer["state_sha256"]))
    rows = connection.execute(
        "select edit_id,edit_seq,kind,object_id,undone_edit_id,base_state_sha256,"
        "result_state_sha256,after_document,actor from world_alternate_version_edit "
        "where workspace_id=%s and world_id=%s and version_id=%s and edit_seq>%s "
        "order by edit_seq",
        (session.workspace_id, world_id, version_id, after_seq),
    ).fetchall()
    chains: list[list[Mapping[str, Any]]] = []
    for index, row in enumerate(rows):
        if row["base_state_sha256"] != base or not _made_by(row, kind, subjects[0]):
            continue
        if undone is not None and str(row["undone_edit_id"]) != undone:
            continue
        chain = [row]
        # An arrangement's objects are recorded one after another in its one transaction, each
        # from the state the one before it left.
        for subject, following in zip(subjects[1:], rows[index + 1 :], strict=False):
            if following["base_state_sha256"] != chain[-1]["result_state_sha256"] or not _made_by(
                following, kind, subject
            ):
                break
            chain.append(following)
        if len(chain) == len(subjects):
            chains.append(chain)
    # The step's own records: the chain its answer ends at, every row made by the caller.
    own = next(
        (
            chain
            for chain in chains
            if named == (int(chain[-1]["edit_seq"]), chain[-1]["result_state_sha256"])
            and all(row["actor"] == session.actor for row in chain)
        ),
        None,
    )
    others = [
        _edit_reference(step, world_id, version_id, row)
        for chain in chains
        if chain is not own
        for row in chain
    ]
    if own is None:
        state = "not_applied" if current["state_sha256"] == base else "superseded"
        return _step(step, state, repeats=others)
    return _step(
        step,
        "applied",
        receipts=[_edit_reference(step, world_id, version_id, row) for row in own],
        repeats=others,
        matches_preview=len(expected) == len(own)
        and all(
            _same(row["after_document"], item) for row, item in zip(own, expected, strict=True)
        ),
    )


def _made_by(row: Mapping[str, Any], kind: str, subject: str | None) -> bool:
    if row["kind"] != kind:
        return False
    return subject is None or row["object_id"] == subject


def _edit_reference(
    step: Mapping[str, Any], world_id: str, version_id: uuid.UUID, row: Mapping[str, Any]
) -> dict[str, Any]:
    """An accepted-operation reference, carrying the ids a project's context stores for it, under
    the same names."""
    return {
        "operation": step.get("operation"),
        "world_id": world_id,
        "version_id": str(version_id),
        "edit_id": str(row["edit_id"]),
        "edit_seq": int(row["edit_seq"]),
        "result_state_sha256": row["result_state_sha256"],
        "kind": row["kind"],
        "object_id": row["object_id"],
    }


def _proposal_id(steps: Sequence[Mapping[str, Any]]) -> uuid.UUID | None:
    for step in steps:
        if step.get("operation") == STYLE_PREVIEW:
            with _client_shape(step):
                raw = (step.get("body") or {}).get("proposal_id")
                return None if raw is None else uuid.UUID(str(raw))
    return None


@contextmanager
def _client_shape(step: Mapping[str, Any]) -> Iterator[None]:
    """Read what a client sent back, refusing a shape no plan has as one 422 rather than a crash.

    Only the reading of the client's step is held here; every read of the authorities runs
    outside it, so a fault there is never mistaken for a malformed step.
    """
    try:
        yield
    except (AttributeError, LookupError, TypeError, ValueError) as malformed:
        raise InvalidOutcomeStep(
            f"step {step.get('index')!r} does not have the shape a plan gives it"
        ) from malformed


def _style_preview_step(
    connection: psycopg.Connection, session: Session, world_id: str, step: Mapping[str, Any]
) -> dict[str, Any]:
    """Step 0 of an appearance plan: the proposal and preview the style lifecycle recorded."""
    proposal_id = _proposal_id([step])
    if proposal_id is None:
        return _step(step, "not_applied")
    row = connection.execute(
        "select p.status as proposal_status,v.preview_id,v.status as preview_status "
        "from world_style_proposal p left join world_style_preview v "
        "on v.workspace_id=p.workspace_id and v.world_id=p.world_id "
        "and v.proposal_id=p.proposal_id "
        "where p.workspace_id=%s and p.world_id=%s and p.proposal_id=%s",
        (session.workspace_id, world_id, proposal_id),
    ).fetchone()
    if row is None:
        return _step(step, "not_applied")
    if row["preview_id"] is None:
        # The lifecycle records a refused proposal too, and opens no preview for it: a base that
        # moved first is ``stale``, a reference it would not take is ``rejected``.
        state = "superseded" if row["proposal_status"] == "stale" else "not_applied"
        return _step(step, state, code=row["proposal_status"])
    if _answer(step) is None:
        # The proposal's preview is recorded, and this step's own request was not answered with
        # it: sending the step again would be refused.
        return _step(step, "superseded")
    return _step(
        step,
        "applied",
        receipts=[
            {
                "operation": STYLE_PREVIEW,
                "world_id": world_id,
                "proposal_id": str(proposal_id),
                "proposal_status": row["proposal_status"],
                "preview_id": str(row["preview_id"]),
                "preview_status": row["preview_status"],
            }
        ],
    )


def _style_apply_step(
    connection: psycopg.Connection,
    session: Session,
    world_id: str,
    steps: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Step 1 of an appearance plan: the style version applied from step 0's proposal."""
    step = next(item for item in steps if item.get("operation") == STYLE_APPLY)
    proposal_id = _proposal_id(steps)
    if proposal_id is None:
        return _step(step, "not_applied")
    row = connection.execute(
        "select version_id,revision from world_style_version "
        "where workspace_id=%s and world_id=%s and applied_from_proposal_id=%s",
        (session.workspace_id, world_id, proposal_id),
    ).fetchone()
    if row is None:
        return _step(step, "not_applied")
    if _answer(step) is None:
        return _step(step, "superseded")
    return _step(
        step,
        "applied",
        receipts=[
            {
                "operation": STYLE_APPLY,
                "world_id": world_id,
                "style_version_id": str(row["version_id"]),
                "revision": int(row["revision"]),
                "proposal_id": str(proposal_id),
            }
        ],
    )


# -- simulation: the playback controls' receipts, followed as a chain -----------------------------


def _control_chain(
    connection: psycopg.Connection,
    session: Session,
    world_id: str,
    steps: Sequence[Mapping[str, Any]],
    clock: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """A simulation plan's steps, read from the first step's pins along the receipts they left.

    ``clock`` is the version's clock read now: a step pinned to a clock revision that moved is
    refused as stale whatever the controls hold, so it is ``superseded``, never ``not_applied``.
    A configuration leaves the society where it stood when the configuration landed, and a playing
    world moves on until its pause does, so the control step after a configuration is the
    ``manual_step`` its answer names, recorded after it at its revision; a later one runs on from
    the minute and state the step before it left. Each receipt comes after the one before it, and
    each is the one its step's answer names.
    """
    society = clock.get("society")
    with _client_shape(steps[0]):
        pins = steps[0].get("pins") or {}
        clock_moved = int(clock["revision"]) != int(pins["clock_revision"])
        revision = int(pins["control_revision"])
        #: The minute and state the next control step runs on from, or None after a configuration.
        base: tuple[int, str] | None = (int(pins["tick"]), str(pins["society_state_sha256"]))
        wanted: list[
            tuple[Mapping[str, Any], tuple[str, int] | None, tuple[int, str | None] | None]
        ] = []
        for step in steps:
            operation = str(step["operation"])
            answer = _answer(step)
            if operation == CONTROL:
                body = step.get("body") or {}
                # The configuration's event is the last its answer's control read names; the
                # event's own revision is matched when it is read.
                named = None if answer is None else (int(answer["last_event_seq"]), None)
                wanted.append((step, (str(body["mode"]), int(body["speed"])), named))
            elif operation == CONTROL_STEP:
                named = (
                    None
                    if answer is None
                    else (int(answer["event_seq"]), str(answer["document_sha256"]))
                )
                wanted.append((step, None, named))
            else:
                raise ValueError("a simulation plan's steps are playback controls only")
    if society is None:
        return [_step(step, "not_applied") for step in steps]
    society_id = uuid.UUID(str(society["society_id"]))
    after = 0
    answered: list[dict[str, Any]] = []
    for step, configures, named in wanted:
        if answered and answered[-1]["state"] != "applied":
            # A chain stops at its first step the records do not show: nothing after it was sent.
            answered.append(_step(step, "not_applied"))
            continue
        if configures is not None:
            event = _control_event(
                connection,
                session,
                society_id,
                "configured",
                named,
                after=after,
                revision=revision + 1,
            )
            if event is not None and (event["mode"], event["speed"]) == configures:
                revision, after, base = revision + 1, int(event["event_seq"]), None
                answered.append(
                    _step(step, "applied", receipts=[_control_reference(step, world_id, event)])
                )
                continue
            stands = not clock_moved and int(society["control_revision"]) == revision
        else:
            event = (
                _control_event(
                    connection,
                    session,
                    society_id,
                    "manual_step",
                    named,
                    after=after,
                    revision=revision,
                )
                if base is None
                else _control_event(
                    connection,
                    session,
                    society_id,
                    "manual_step",
                    named,
                    after=after,
                    tick_from=base[0],
                    previous=base[1],
                )
            )
            if event is not None:
                revision, after = int(event["revision"]), int(event["event_seq"])
                base = (int(event["tick_to"]), str(event["state_sha256"]))
                answered.append(
                    _step(step, "applied", receipts=[_control_reference(step, world_id, event)])
                )
                continue
            # After a configuration only control steps move a paused society, and none ran at
            # its revision, so the revision says whether the step's bases still stand.
            stands = (
                not clock_moved
                and int(society["control_revision"]) == revision
                and (base is None or (int(society["tick"]), str(society["state_sha256"])) == base)
            )
        # Not recorded: still sendable while the controls stand where the step's bases are,
        # and refused as stale once anything moved them.
        answered.append(_step(step, "not_applied" if stands else "superseded"))
    return answered


def _control_event(
    connection: psycopg.Connection,
    session: Session,
    society_id: uuid.UUID,
    kind: str,
    named: tuple[int, str | None] | None,
    *,
    after: int,
    revision: int | None = None,
    tick_from: int | None = None,
    previous: str | None = None,
) -> dict[str, Any] | None:
    """The control event of ``kind`` the step's own request left, recorded after event ``after``.

    ``named`` is the event the step's answer names, by sequence (and, for a control step, digest);
    None finds nothing. The event must also be the step's: a configuration made by the caller at
    the revision it made, a control step requested by the caller from the minute and state it ran
    on from, or after a configuration, at its revision.
    """
    if named is None:
        return None
    event_seq, digest = named
    actor = "requested_by" if kind == "manual_step" else "actor_id"
    match = f"document->>'kind'=%s and event_seq>%s and event_seq=%s and document->>'{actor}'=%s"
    values: list[Any] = [kind, after, event_seq, str(session.actor)]
    if digest is not None:
        match += " and document_sha256=%s"
        values.append(digest)
    if revision is not None:
        match += " and (document->>'revision')::bigint=%s"
        values.append(revision)
    if tick_from is not None:
        match += (
            " and (document->>'tick_from')::bigint=%s and document->>'previous_state_sha256'=%s"
        )
        values += [tick_from, previous]
    row = connection.execute(
        "select event_seq,document,document_sha256 from world_society_control_event "
        "where workspace_id=%s and society_id=%s and " + match,
        (session.workspace_id, society_id, *values),
    ).fetchone()
    if row is None:
        return None
    return {
        **row["document"],
        "event_seq": int(row["event_seq"]),
        "document_sha256": row["document_sha256"],
    }


def _control_reference(
    step: Mapping[str, Any], world_id: str, event: Mapping[str, Any]
) -> dict[str, Any]:
    """A playback control's receipt, carrying the fields a project's context stores for it under
    the same names (a configuration's minute and state are null), and the event's own sequence
    and digest."""
    stepped = event["kind"] == "manual_step"
    return {
        "operation": step.get("operation"),
        "world_id": world_id,
        "version_id": str(event["branch_id"]),
        "revision": int(event["revision"]),
        "tick": int(event["tick_to"]) if stepped else None,
        "state_sha256": str(event["state_sha256"]) if stepped else None,
        "event_seq": int(event["event_seq"]),
        "document_sha256": event["document_sha256"],
    }


def _after_chain(
    steps: Sequence[Mapping[str, Any]],
    answered: Sequence[Mapping[str, Any]],
    society: Mapping[str, Any] | None,
) -> list[str]:
    """``play`` when the plan ends by playing the world again, that step did not run, and the
    world stands paused: the chain stopped after its pause, and nothing resumes it on its own."""
    if society is None or society.get("mode") != "paused":
        return []
    last = steps[-1]
    resumes = last.get("operation") == CONTROL and (last.get("body") or {}).get("mode") == (
        "playing"
    )
    if resumes and answered[-1]["state"] != "applied":
        return [SimulationAction.PLAY.value]
    return []


def _bring_people_step(
    connection: psycopg.Connection,
    session: Session,
    world_id: str,
    version_id: uuid.UUID,
    step: Mapping[str, Any],
) -> dict[str, Any]:
    """People brought in: the version's society, in the step's region and with its engine."""
    with _client_shape(step):
        body = step.get("body") or {}
        region = str(body["region_id"])
        engine = body.get("profile")
        answer = _answer(step)
        named = None if answer is None else str(answer["society_id"])
    row = connection.execute(
        "select society_id,region_id,engine_version from world_society "
        "where workspace_id=%s and world_id=%s and version_id=%s",
        (session.workspace_id, world_id, version_id),
    ).fetchone()
    if row is None:
        return _step(step, "not_applied")
    if (
        row["region_id"] != region
        or engine not in (None, row["engine_version"])
        or str(row["society_id"]) != named
    ):
        # A version holds one society, and this one is not what the step's own request was
        # answered with (another region, another engine, or no answer naming it). Bringing people
        # in is idempotent: the same request sent after another's is answered with the society
        # already there, and that answer names it, whoever brought it in.
        return _step(step, "superseded")
    return _step(
        step,
        "applied",
        receipts=[
            {
                "operation": BRING_PEOPLE,
                "world_id": world_id,
                "version_id": str(version_id),
                "society_id": str(row["society_id"]),
                "region_id": row["region_id"],
                "engine": row["engine_version"],
            }
        ],
    )
