"""Who a placed being is, as its world's owner writes it: one route that writes or clears it.

``POST /world/versions/{version_id}/things/{thing_id}/character`` appends a record for the being
the author placed under ``thing_id`` (the placed id the move and remove routes take), over the
newest record the caller read (``base_revision``, null where it read none), and answers
``exulanica.thing-character/v1``: the record, and whether the version's society shows it
(``society``: ``runs_characters``, ``began_before_characters`` or ``none``)
(:mod:`exulanica.world.thing_characters`). A null ``character`` clears it. Where the version's
society records the character module, its next input is composed in the same transaction, so the
being's decider is shown the character from the society's next minute; a society made before
that module never shows one, and a character reaches such a being only in a new version's society.

Refused by name: 404 ``unknown_reference`` for a thing the version does not hold; 409
``character_changed`` (the newest revision in ``revision``) and ``no_change``; 422
``character_out_of_bounds``, ``character_carries_a_saved_name`` and ``character_for_beings_only``;
424 ``unavailable_society_input`` where the society's next input cannot be composed, and then
nothing is written.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

import psycopg
from fastapi import APIRouter, Path, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, StrictInt, StrictStr

from exulanica.api.dependencies import CurrentSession, ScopedConnection, get_services
from exulanica.api.world_scope import WorldId
from exulanica.epistemics.saved_names import saved_names
from exulanica.world.placed_things import PLACED_THING_ID_PATTERN
from exulanica.world.society import UnavailableSocietyInput
from exulanica.world.thing_characters import (
    CHARACTER_PROFILE,
    ThingCharacterRefused,
    screened_character,
    society_reads_characters,
    write_character,
)
from exulanica.world.workspace_lock import lock_workspace
from exulanica.world.worlds import require_world

router = APIRouter(prefix="/world", tags=["world"])

_STATUS = {
    "character_changed": 409,
    "no_change": 409,
    "character_out_of_bounds": 422,
    "character_carries_a_saved_name": 422,
    "character_for_beings_only": 422,
}


class CharacterBody(BaseModel):
    """What the owner writes: a name, words about the being, or both."""

    model_config = ConfigDict(extra="forbid")

    name: StrictStr | None = None
    about: StrictStr | None = None


class ThingCharacterBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: The newest record's revision as the caller read it; null where it read none.
    base_revision: StrictInt | None
    #: The character to write, or null to clear it.
    character: CharacterBody | None


def _refused(exc: ThingCharacterRefused) -> JSONResponse:
    content: dict[str, Any] = {"code": exc.code, "detail": exc.detail}
    if exc.code == "character_changed":
        content["revision"] = exc.revision
    return JSONResponse(status_code=_STATUS[exc.code], content=content)


@router.post(
    "/versions/{version_id}/things/{thing_id}/character",
    summary="The world's owner writes or clears who a placed being is; answers the record.",
)
def thing_character_write(
    version_id: Annotated[uuid.UUID, Path()],
    thing_id: Annotated[str, Path(pattern=PLACED_THING_ID_PATTERN)],
    body: ThingCharacterBody,
    connection: ScopedConnection,
    session: CurrentSession,
    request: Request,
    world_id: WorldId,
) -> JSONResponse:
    services = get_services(request)
    require_world(connection, session.workspace_id, world_id)
    runtime = services.society_runtime
    if runtime is not None:
        # A site world's place its society's next input needs, made before the transaction.
        runtime.prepare_authored_edit(connection, session, world_id, version_id)
    observer = getattr(request.app.state, "society_authored_edit", None)
    try:
        with connection.transaction():
            lock_workspace(connection, session.workspace_id)
            character = screened_character(
                None if body.character is None else body.character.model_dump(exclude_none=True),
                saved_names(connection, session.workspace_id),
            )
            record = write_character(
                connection,
                workspace_id=session.workspace_id,
                world_id=world_id,
                version_id=version_id,
                placed_id=thing_id,
                base_revision=body.base_revision,
                character=character,
                actor=session.actor,
            )
            society = society_reads_characters(
                connection, session.workspace_id, world_id, version_id
            )
            if society == "runs_characters" and observer is not None:
                observer(connection, session, version_id)
    except ThingCharacterRefused as exc:
        return _refused(exc)
    except psycopg.errors.UniqueViolation:
        # Another writer appended over the same record first.
        return JSONResponse(
            status_code=409,
            content={
                "code": "character_changed",
                "detail": "another character was written since this one was read",
                "revision": None,
            },
        )
    except UnavailableSocietyInput as exc:
        return JSONResponse(
            status_code=424, content={"code": "unavailable_society_input", "detail": str(exc)}
        )
    return JSONResponse(
        content={
            "profile": CHARACTER_PROFILE,
            "version_id": str(version_id),
            "placed_id": thing_id,
            **record.document(),
            "society": society,
        },
        headers={"Cache-Control": "private, no-store"},
    )
