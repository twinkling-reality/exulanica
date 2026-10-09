"""A person plays one being of a world's society of things ("Play this one").

``POST /world/versions/{version_id}/society/play`` starts playing one being, ``POST
.../play/{subject_id}/give-back`` gives it back, ``GET .../play/{subject_id}/turn`` reads what the
being is offered in the minute to come, and ``POST .../play/{subject_id}/answer`` posts the person's
answer for that minute (:mod:`exulanica.world.society_play`). Starting, giving back and answering
take ``world.write``. A read never names the account that plays a being, only whether it is the
reader (``played_by_you``).
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any, Final

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from exulanica.api.dependencies import CurrentSession, ScopedConnection
from exulanica.api.world_scope import WorldId
from exulanica.epistemics.saved_names import recognised_spans, saved_names
from exulanica.things.lines import LineRefused, check_line
from exulanica.world.deciders import decider, is_played
from exulanica.world.decision_roles import DecisionRole, decision_roles
from exulanica.world.errors import UnknownWorldResource
from exulanica.world.society import UnavailableSocietyInput, UnknownSociety
from exulanica.world.society_model_choice_repository import (
    ModelChoiceRefused,
    SocietyModelChoiceRepository,
)
from exulanica.world.society_play import (
    QUIET_MINUTES,
    PlayRefused,
    answer_document,
    quiet_minutes,
    record_answer,
)
from exulanica.world.society_repository import SocietyRepository
from exulanica.world.worlds import require_world

router = APIRouter(prefix="/world/versions/{version_id}/society/play", tags=["society"])

__all__ = ["PLAY_CONFLICTS", "router"]

#: A refusal of a play answered with 409 rather than 422: the society or the being, not the body.
PLAY_CONFLICTS: Final = frozenset(
    {
        "engine_takes_no_play",
        "being_played",
        "not_played",
        "decided_from_outside",
        "choice_key_reused",
    }
)
#: Whom a person plays: a society's people, so these routes serve the role deciding for them.
SUBJECT: Final = "person"


class PlayBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: uuid.UUID
    subject_id: uuid.UUID


class GiveBackBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: uuid.UUID


class PlayAnswerBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    #: The minute the answer is for: the society's current minute, the one about to be played.
    base_tick: Annotated[StrictInt, Field(ge=0)]
    #: The option chosen, by its label as the turn read gives it.
    label: Annotated[str, Field(min_length=1, max_length=400)]
    #: What the being says, exactly where the option says something.
    line: Annotated[str, Field(min_length=1, max_length=2000)] | None = None


def _role() -> DecisionRole:
    found = [role for role in decision_roles() if role.subject == SUBJECT]
    if len(found) != 1:
        raise UnknownWorldResource("no one role decides for a society's people")
    return found[0]


def _society(
    connection: ScopedConnection, session: CurrentSession, request: Request, world_id: str
) -> SocietyRepository:
    require_world(connection, session.workspace_id, world_id)
    authorizer = getattr(request.app.state, "society_input_authorizer", None)
    return SocietyRepository(
        connection,
        session.workspace_id,
        world_id=world_id,
        input_authorizer=(
            None if authorizer is None else lambda doc: authorizer(connection, session, doc)
        ),
    )


def _refused(code: str, detail: str, status: int, **more: Any) -> JSONResponse:
    return JSONResponse(status_code=status, content={"code": code, "detail": detail, **more})


def _choice_refused(exc: ModelChoiceRefused) -> JSONResponse:
    return _refused(exc.code, exc.detail, 409 if exc.code in PLAY_CONFLICTS else 422)


def _shown(choice: dict[str, Any], session: CurrentSession) -> dict[str, Any]:
    """A play choice as a read shows it: the person by whether they are the reader, never by
    their account."""
    described = choice["decider"]
    mine = described.get("account_id") == str(session.actor)
    return {
        key: value
        for key, value in choice.items()
        if key not in ("decider", "chosen_by", "model", "document_sha256", "request_id")
    } | {"decider": {"kind": "person"}, "played_by_you": mine}


def _played_by(
    connection: ScopedConnection,
    session: CurrentSession,
    world_id: str,
    version_id: uuid.UUID,
    role: DecisionRole,
    subject: str,
) -> dict[str, Any] | None:
    """The choice by which a person plays ``subject`` now, or None where nobody plays it."""
    current = SocietyModelChoiceRepository(
        connection, session.workspace_id, world_id=world_id
    ).current(version_id, role)
    held = current.get(subject)
    if held is None or not is_played(held["decider"]):
        return None
    return held


@router.post("", status_code=201)
def start_playing(
    version_id: uuid.UUID,
    body: PlayBody,
    connection: ScopedConnection,
    session: CurrentSession,
    world_id: WorldId,
) -> Any:
    """Start playing one being: a choice naming it with the person who plays, the session's
    account. Refused by name where the society is not a society of things
    (``engine_takes_no_play``), another person plays it (``being_played``), its own program
    decides for it (``decided_from_outside``) or its kind lets no person decide for it
    (``decider_not_allowed``)."""
    require_world(connection, session.workspace_id, world_id)
    role = _role()
    repository = SocietyModelChoiceRepository(connection, session.workspace_id, world_id=world_id)
    try:
        chosen = repository.record_play(
            version_id,
            role,
            request_id=body.idempotency_key,
            subject=str(body.subject_id),
            account_id=session.actor,
            contract=role.contract(role.terms(repository.engine(version_id)).versions),
        )
    except ModelChoiceRefused as exc:
        return _choice_refused(exc)
    except UnknownSociety as exc:
        return _refused("society_unavailable", str(exc), 404)
    return _shown(chosen, session)


@router.post("/{subject_id}/give-back")
def give_back(
    version_id: uuid.UUID,
    subject_id: uuid.UUID,
    body: GiveBackBody,
    connection: ScopedConnection,
    session: CurrentSession,
    world_id: WorldId,
) -> Any:
    """Give the being back: it is decided for again as it was before the play began. Refused
    ``not_played`` where the reader does not play it."""
    require_world(connection, session.workspace_id, world_id)
    role = _role()
    repository = SocietyModelChoiceRepository(connection, session.workspace_id, world_id=world_id)
    try:
        ended = repository.give_back(
            version_id,
            role,
            request_id=body.idempotency_key,
            subject=str(subject_id),
            account_id=session.actor,
            chosen_by=session.actor,
            contract=role.contract(role.terms(repository.engine(version_id)).versions),
            ended="given_back",
        )
    except ModelChoiceRefused as exc:
        return _choice_refused(exc)
    except UnknownSociety as exc:
        return _refused("society_unavailable", str(exc), 404)
    return _shown(ended, session)


@router.get("/{subject_id}/turn")
def turn(
    version_id: uuid.UUID,
    subject_id: uuid.UUID,
    connection: ScopedConnection,
    session: CurrentSession,
    request: Request,
    world_id: WorldId,
) -> Any:
    """What the being is offered in the minute to come, read from the society's stored state as
    its request will offer it: each option's label, kind, the place or being it names and whether
    it takes a line; the line's bound; whether the reader plays it; how many quiet minutes are
    left before the being is given back; and when the minute is due."""
    society = _society(connection, session, request, world_id)
    role = _role()
    subject = str(subject_id)
    try:
        row = society._row(version_id)
        if row is None:
            return _refused("society_unavailable", "society is unavailable", 404)
        latest = society._chain(row)
        document = society._inputs(row, [latest])[latest]
    except UnavailableSocietyInput as exc:
        return _refused("unavailable_society_input", str(exc), 424)
    if subject not in set(role.adapter.subjects(row["state"])):
        return _refused("person_not_in_this_world", "nobody of that id is here", 404)
    contract = role.contract(role.terms(row["engine_version"]).versions)
    options = role.adapter.options(
        role, row["state"], document, subject, contract, seed=row["seed"]
    )
    line_kinds = frozenset(getattr(role.adapter, "LINE_KINDS", ()))
    held = _played_by(connection, session, world_id, version_id, role, subject)
    quiet = (
        0
        if held is None
        else quiet_minutes(
            connection,
            session.workspace_id,
            row["society_id"],
            subject,
            role.receipt_profile,
            int(held.get("since_tick") or 0),
        )
    )
    control = connection.execute(
        "select mode, speed, base_tick_interval_ms, next_due_at from world_society_control "
        "where workspace_id = %s and society_id = %s",
        (session.workspace_id, row["society_id"]),
    ).fetchone()
    playing = control is not None and control["mode"] == "playing"
    return {
        "subject_id": subject,
        "base_tick": row["current_tick"],
        "options": [
            {
                "label": option.label,
                "kind": option.kind,
                "target_id": option.target_id,
                "being_id": option.partner_id or option.addressee_id,
                "takes_line": option.kind in line_kinds,
            }
            for option in options
        ],
        "line_characters_maximum": contract.value("line_characters_maximum"),
        "played": held is not None,
        "played_by_you": held is not None and held["decider"]["account_id"] == str(session.actor),
        "quiet_minutes": QUIET_MINUTES,
        "quiet_left": QUIET_MINUTES - quiet,
        "next_due_at": None
        if not playing or control["next_due_at"] is None
        else control["next_due_at"].isoformat(),
        "minute_ms": None if not playing else control["base_tick_interval_ms"] // control["speed"],
    }


@router.post("/{subject_id}/answer", status_code=202)
def answer(
    version_id: uuid.UUID,
    subject_id: uuid.UUID,
    body: PlayAnswerBody,
    connection: ScopedConnection,
    session: CurrentSession,
    request: Request,
    world_id: WorldId,
) -> Any:
    """The reader's answer for the being they play, for the minute ``base_tick``: one option the
    minute offers, by its label, and its line where it says something. Checked as any decider's
    answer is, and kept as the latest for that minute; the minute takes the latest. Refused
    ``minute_passed`` (409, with the current minute) where that minute has been played,
    ``not_played`` where the reader does not play the being, and by the check that fails."""
    society = _society(connection, session, request, world_id)
    role = _role()
    subject = str(subject_id)
    held = _played_by(connection, session, world_id, version_id, role, subject)
    if held is None or held["decider"] != decider(
        {"kind": "person", "account_id": str(session.actor)}
    ):
        exc = ModelChoiceRefused("not_played")
        return _choice_refused(exc)
    try:
        row = society._row(version_id)
        if row is None:
            return _refused("society_unavailable", "society is unavailable", 404)
        if body.base_tick != row["current_tick"]:
            raise PlayRefused("minute_passed", tick=row["current_tick"])
        if subject not in set(role.adapter.subjects(row["state"])):
            # A being that left the world is offered nothing, played or not.
            return _refused("person_not_in_this_world", "nobody of that id is here", 404)
        latest = society._chain(row)
        document = society._inputs(row, [latest])[latest]
        contract = role.contract(role.terms(row["engine_version"]).versions)
        options = role.adapter.options(
            role, row["state"], document, subject, contract, seed=row["seed"]
        )
        option = next((offered for offered in options if offered.label == body.label), None)
        if option is None:
            raise PlayRefused("label_not_offered")
        takes_line = option.kind in frozenset(getattr(role.adapter, "LINE_KINDS", ()))
        line = body.line
        if takes_line and line is None:
            raise PlayRefused("line_needed")
        if not takes_line and line is not None:
            raise PlayRefused("line_not_taken")
        if line is not None:
            try:
                line = check_line(line, maximum=contract.value("line_characters_maximum"))
            except LineRefused as exc:
                raise PlayRefused("line_out_of_bounds") from exc
            if recognised_spans(line, saved_names(connection, session.workspace_id)):
                raise PlayRefused("line_refused_by_rules")
        kept = record_answer(
            connection,
            workspace_id=session.workspace_id,
            world_id=world_id,
            society_id=row["society_id"],
            account_id=session.actor,
            document=answer_document(subject, row["current_tick"], option.label, line),
        )
    except UnavailableSocietyInput as exc:
        return _refused("unavailable_society_input", str(exc), 424)
    except PlayRefused as exc:
        more = {} if exc.tick is None else {"current_tick": exc.tick}
        return _refused(exc.code, exc.detail, exc.status, **more)
    return {"subject_id": subject, "base_tick": kept["base_tick"], "answer_seq": kept["answer_seq"]}
