"""What the authorities recorded for a Companion plan's steps: the receipts, read, never asserted.

A plan (:mod:`exulanica.selection.action_plan`) is carried out by a client sending its steps to the
routes they name. This module is how the Companion learns what happened, and the only thing it
reports: each step's receipt as the authority stored it, read back from the authority's own
records, so an answer never states an effect that no record shows.

The plan a client sends back is used only to decide what to look up. Every fact in the answer is
read here, in the caller's workspace and world: a version edit whose base is the step's pinned base
and whose kind and subject are the step's, a style proposal by the id the step carried, the style
version applied from it. A plan altered on its way back can only make its own answer say less.

Per step:

*   ``applied``: the record exists; ``receipts`` name it by the ids an accepted-operation reference
    stores, and ``matches_preview`` says whether what was recorded is what the preview showed.
*   ``not_applied``: no such record, and the version still stands at the step's pinned base, so
    nothing happened. Sending the step again is still possible.
*   ``superseded``: no such record, and the version moved past the pin: another change came first,
    and the step's request would now be refused as stale.
*   ``pending``: a later step of a compound plan, not yet prepared, so there is nothing to read.

Content-addressed state can recur (an undo returns a version to an earlier digest), so a record
made again from the same base after the first is reported in ``repeats``, never folded into it.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from typing import Any, Final

import psycopg

from exulanica.selection.action_plan import (
    ARRANGE,
    MOVE,
    PLACE,
    REMOVE,
    STYLE_APPLY,
    STYLE_PREVIEW,
    UNDO,
    document_sha256,
)
from exulanica.selection.validation import Session
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


def action_outcome(
    connection: psycopg.Connection,
    request: Mapping[str, Any],
    session: Session,
    *,
    world_id: str,
) -> dict[str, Any]:
    """The receipts the authorities recorded for ``request["steps"]``, and the plan's state.

    Raises ``UnknownWorldResource`` for a version this world does not hold, as every version read
    does, so a foreign version is answered as a write answers it.
    """
    version_id = uuid.UUID(str(request["version_id"]))
    repository = WorldObjectRepository(connection, session.workspace_id, world_id=world_id)
    row = repository.edit_base_row(version_id)
    current = {"state_sha256": row["state_sha256"], "edit_seq": int(row["edit_seq"])}
    answered: list[dict[str, Any]] = []
    for step in request["steps"]:
        operation = str(step.get("operation"))
        if step.get("state") == "pending" and operation not in (STYLE_APPLY,):
            answered.append(_step(step, "pending"))
        elif operation in _EDIT_KINDS:
            answered.append(_edit_step(connection, session, world_id, version_id, step, current))
        elif operation == STYLE_PREVIEW:
            answered.append(_style_preview_step(connection, session, world_id, step))
        elif operation == STYLE_APPLY:
            answered.append(_style_apply_step(connection, session, world_id, request["steps"]))
        else:
            raise InvalidOutcomeStep(f"{operation!r} is not an operation a Companion plan names")
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
    }


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
    rows = connection.execute(
        "select edit_id,edit_seq,kind,object_id,undone_edit_id,base_state_sha256,"
        "result_state_sha256,after_document from world_alternate_version_edit "
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
    if not chains:
        state = "not_applied" if current["state_sha256"] == base else "superseded"
        return _step(step, state)
    first, *again = chains
    return _step(
        step,
        "applied",
        receipts=[_edit_reference(step, world_id, version_id, row) for row in first],
        repeats=[
            _edit_reference(step, world_id, version_id, row) for chain in again for row in chain
        ],
        matches_preview=len(expected) == len(first)
        and all(
            _same(row["after_document"], item) for row, item in zip(first, expected, strict=True)
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
