"""A world version's moments, for its History (exulanica.world.society_moments).

*   ``GET /world/versions/{version_id}/history/moments`` answers
    ``exulanica.world-history-moments/v1``: what the version's characters did that a person would
    tell, newest last, at most ``limit`` before minute ``before``, each with the lines said in it,
    who decided, where, the run it happened in, its scene and the other models' answers to its
    decision. ``more`` says whether earlier ones exist. A version whose world has no society has no
    moments. It writes nothing.

    With ``recipe``, the framing recipe a page draws by, each moment's ``picture`` is the one kept
    for it by that recipe (:mod:`exulanica.world.moment_pictures`), its digest and size, or null,
    so a page draws only what nobody kept. The read itself needs less than a picture's bytes do, so
    a moment names its picture only to a caller whose grant reads them
    (``GET /world/pictures/{sha256}``); for anyone else, and without ``recipe``, it is null.

    With ``story=true``, only the moments History's line draws: those a model, a person playing or
    an outside program decided, and those with a being this person touched (given a model, asked
    in a run, placed); ``before``, ``limit`` and ``more`` count within them.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any, Final

from fastapi import APIRouter, Query, Request

from exulanica.api.dependencies import CurrentSession, HeldPermissions, ScopedConnection
from exulanica.api.permissions import Permission, Requires, rule_for
from exulanica.api.routes.society import _call, _repository
from exulanica.api.routes.society_control import repository as control_repository
from exulanica.api.world_scope import WorldId
from exulanica.models.manifest import load_manifest
from exulanica.world.moment_pictures import RECIPE_PATTERN, MomentPictureRepository
from exulanica.world.society_moments import MOMENTS_PROFILE, READ_MOST, read_moments

__all__ = ["router"]

router = APIRouter(prefix="/world", tags=["history"])

#: The route that serves a kept picture's bytes: its own rule says who is told of one.
_PICTURE_BYTES: Final = ("GET", "/world/pictures/{sha256}")


def _reads_pictures(held: frozenset[Permission]) -> bool:
    """Whether a grant holding ``held`` may read a kept picture's bytes; no if that route's rule is
    ever anything but a plain requirement (a kind that asks more, as an invitation or a browser
    owner does, is not read here), so a change there names no picture until this is read again."""
    rule = rule_for(*_PICTURE_BYTES)
    return type(rule) is Requires and rule.permissions <= held


@router.get("/versions/{version_id}/history/moments")
def read_version_moments(
    version_id: uuid.UUID,
    connection: ScopedConnection,
    session: CurrentSession,
    held: HeldPermissions,
    request: Request,
    world_id: WorldId,
    before: Annotated[int | None, Query(ge=0)] = None,
    limit: Annotated[int, Query(ge=1, le=READ_MOST)] = 50,
    recipe: Annotated[
        str | None, Query(min_length=4, max_length=56, pattern=RECIPE_PATTERN.pattern)
    ] = None,
    story: bool = False,
) -> Any:
    """The version's moments, newest last, each with its kept picture by the recipe asked for."""

    def read() -> Any:
        with connection.transaction():
            row = _repository(connection, session, request, world_id)._row(version_id)
            if row is None:
                return {
                    "profile": MOMENTS_PROFILE,
                    "version_id": str(version_id),
                    "now": None,
                    "moments": [],
                    "more": False,
                }
            sessions = control_repository(connection, session, request, world_id).sessions(
                version_id
            )
            manifest = load_manifest()
            answer = read_moments(
                connection,
                session.workspace_id,
                row,
                before=before,
                limit=limit,
                sessions=sessions,
                model_name=manifest.model_name,
                story=story,
            )
            if recipe is not None and _reads_pictures(held):
                moments = answer["moments"]
                kept = MomentPictureRepository(connection, session.workspace_id).moments(
                    world_id, [uuid.UUID(moment["moment_id"]) for moment in moments], recipe
                )
                for moment in moments:
                    picture = kept.get(uuid.UUID(moment["moment_id"]))
                    moment["picture"] = None if picture is None else picture.view()
            return answer

    return _call(read, invalid_status=409)
