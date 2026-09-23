"""Where a place's saved name may go: see each use, allow it, and stop it.

A place's name goes to a hosted model only while the account holder who named it allows that
use, asked for each place. These routes read and record those decisions and decide nothing:
:mod:`exulanica.consent.place_name_rights` records them and :mod:`exulanica.consent.place_names`
states what they mean.

**The words are the server's.** Each use carries the notice the account holder reads before
allowing it, built from the declared uses and the model manifest. An allow sends that text back,
and a single character of difference is a statement nobody was shown and is refused with
``notice_changed``, so a screen that showed stale or invented words cannot record a grant.

**The actor is the session's.** No body names who decided. Only the account holder who stated a
place's name may allow it; anyone the session belongs to may stop it, because stopping only ever
sends less. A stop is recorded as a new decision after the grant it ends, and the grant stays in
the record.

**A place is addressed by id and answers as one.** An id that is not a place in the caller's
workspace, a person's included, answers 404 ``unknown_reference`` exactly as a foreign id does.
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Callable
from typing import Annotated, Any

import psycopg
from fastapi import APIRouter, Path
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from exulanica.api.dependencies import CurrentSession, ReadOnlyConnection, ScopedConnection
from exulanica.consent.place_name_rights import (
    PlaceNameRightRefused,
    PlaceNameRights,
    UnknownPlace,
    grant_place_name,
    places_with_decisions,
    read_place_name_rights,
    withdraw_place_name,
)

router = APIRouter(tags=["place-name-rights"])

_ROLE = r"^[a-z][a-z0-9_]{0,62}$"


class Allow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: The use to allow, as the read names it.
    use: str = Field(pattern=_ROLE)
    #: The exact notice the account holder was shown for that use.
    notice: str = Field(min_length=1, max_length=2000)


class Stop(BaseModel):
    model_config = ConfigDict(extra="forbid")

    use: str = Field(pattern=_ROLE)


def _problem(status: int, code: str, detail: str) -> JSONResponse:
    """The application's one failure shape, ``{code, detail}``."""
    return JSONResponse(status_code=status, content={"code": code, "detail": detail})


def _no_such_place() -> JSONResponse:
    return _problem(404, "unknown_reference", "no such place")


def _instant(value: dt.datetime | None) -> str | None:
    return None if value is None else value.astimezone(dt.UTC).isoformat()


def _view(rights: PlaceNameRights) -> dict[str, Any]:
    return {
        "entity_id": str(rights.entity_id),
        "name": rights.name,
        "read_at": _instant(rights.read_at),
        "uses": [
            {
                "use": reading.use.role.value,
                "purpose": reading.use.purpose,
                "notice": reading.notice,
                "destination": reading.handoff.destination,
                "models": [
                    {"model": identity.as_record(), "state": state}
                    for identity, state in reading.models
                ],
                "state": reading.state,
                "allowed": reading.allowed,
                "since": _instant(reading.since),
                "until": _instant(reading.until),
                "changed_at": _instant(reading.changed_at),
            }
            for reading in rights.uses
        ],
    }


@router.get("/place-name-rights", summary="Every place whose name has a decision, and each use.")
def every_place(connection: ReadOnlyConnection, session: CurrentSession) -> dict[str, Any]:
    return {
        "places": [
            _view(read_place_name_rights(connection, session.workspace_id, entity_id))
            for entity_id in places_with_decisions(connection, session.workspace_id)
        ]
    }


@router.get("/place-name-rights/{entity_id}", summary="Where one place's name may go, and why not.")
def one_place(
    entity_id: Annotated[uuid.UUID, Path()],
    connection: ReadOnlyConnection,
    session: CurrentSession,
) -> Any:
    try:
        return _view(read_place_name_rights(connection, session.workspace_id, entity_id))
    except UnknownPlace:
        return _no_such_place()


def _decide(record: Callable[[], None]) -> JSONResponse | None:
    """Run one decision, answering its refusal in the application's shape."""
    try:
        record()
    except UnknownPlace:
        return _no_such_place()
    except PlaceNameRightRefused as refused:
        return _problem(409, refused.reason, str(refused))
    except psycopg.errors.SerializationFailure:
        # A final read check held the asset read lock, or another decision took this position.
        # Nothing was recorded; the same request can be sent again.
        return _problem(409, "busy", "a name was being checked at that moment; try again")
    return None


@router.post("/place-name-rights/{entity_id}/grants", status_code=201)
def allow(
    entity_id: Annotated[uuid.UUID, Path()],
    body: Allow,
    connection: ScopedConnection,
    session: CurrentSession,
) -> Any:
    """Allow this place's name to go to every model of one use, against the notice shown."""
    refused = _decide(
        lambda: grant_place_name(
            connection,
            session.workspace_id,
            entity_id=entity_id,
            role=body.use,
            notice=body.notice,
            actor=session.actor,
        ),
    )
    return refused or _view(read_place_name_rights(connection, session.workspace_id, entity_id))


@router.post("/place-name-rights/{entity_id}/withdrawals", status_code=201)
def stop(
    entity_id: Annotated[uuid.UUID, Path()],
    body: Stop,
    connection: ScopedConnection,
    session: CurrentSession,
) -> Any:
    """Stop this place's name going to any model of one use, from the next request on."""
    refused = _decide(
        lambda: withdraw_place_name(
            connection,
            session.workspace_id,
            entity_id=entity_id,
            role=body.use,
            actor=session.actor,
        ),
    )
    return refused or _view(read_place_name_rights(connection, session.workspace_id, entity_id))
