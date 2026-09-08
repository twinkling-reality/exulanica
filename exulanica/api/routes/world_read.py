"""The World Read API: the routes a generative world model reads a real place through.

Roadmap Phase 10 capability 1. The bundle and every decision inside it are
:mod:`exulanica.graph.world_read`, one layer down. What is left here is the routing: take the
workspace off the session, ask for one scene or for one place at one time, and turn "not readable"
into the same answer for every reason it might not be readable.

Three things these routes do that are not obvious.

**404 for a foreign scene, never 403.** The evaluation methodology's M10 requires it: a 403 would
confirm that a scene id exists and belongs to somebody, which is exactly what a cross-tenant probe
is looking for. Nonexistent and foreign ids are indistinguishable from outside.

**410 for a withdrawn scene, and it comes for free.** The bundle is built from
``reconstruction_scene_rows``, whose query already excludes anything ``tombstone_blocks_scene``
covers, so a withdrawn scene simply is not there and the caller receives 404. That is not good
enough for a caller holding a bundle from before the deletion, so the withdrawal is checked
explicitly and answered 410: the fact that a person deleted something is a fact they are entitled
to, and it is different from the thing never having existed.

**Read-only connection.** A route that hands a world model everything it may condition on is the
last place that should hold a connection able to write.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Query
from fastapi.responses import JSONResponse

from exulanica.api.dependencies import CurrentSession, ReadOnlyConnection, get_services
from exulanica.api.services import Services
from exulanica.errors import CanonicalisationError
from exulanica.graph.asset_read_policy import (
    bundle_scene_ids,
    evaluation_time,
    final_check,
    scene_allowed,
    scene_inputs,
)
from exulanica.graph.observations import scene_observations
from exulanica.graph.world_read import place_read_bundle, world_read_bundle
from exulanica.graph.world_read_views import views_current

router = APIRouter(prefix="/world-read", tags=["world-read"])


def _problem(status: int, code: str, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"code": code, "detail": detail})


def _withdrawn(connection: Any, workspace: uuid.UUID, scene_id: uuid.UUID) -> bool:
    """Whether this workspace's own scene was withdrawn, as opposed to never existing.

    Asked only after the bundle came back empty, and only about a scene row that is in this
    workspace, so the answer cannot distinguish another tenant's ids from absent ones.
    """
    row = connection.execute(
        "select tombstone_blocks_scene(%s, %s) as blocked "
        "from reconstruction_scene where workspace_id = %s and scene_id = %s",
        (workspace, scene_id, workspace, scene_id),
    ).fetchone()
    return bool(row is not None and row["blocked"])


def _place_state(connection: Any, workspace: uuid.UUID, place_id: uuid.UUID) -> tuple[bool, bool]:
    """Whether this workspace holds this place, and whether it has an anchor.

    ``tombstone_blocks_place`` fails closed on both a withdrawn anchor and no anchor at all, which
    is right for the guard and wrong for the answer: one of those is a deletion the caller is
    entitled to hear about and the other is a place nobody has aligned yet. So the two halves are
    asked separately, and only about a place row already known to be in this workspace, so the
    answer cannot distinguish another tenant's ids from absent ones.
    """
    row = connection.execute(
        "select exists (select 1 from place "
        "                where workspace_id = %s and place_id = %s) as known, "
        "       exists (select 1 from place_version "
        "                where workspace_id = %s and place_id = %s and frame_hops = 0) as anchored",
        (workspace, place_id, workspace, place_id),
    ).fetchone()
    return bool(row["known"]), bool(row["anchored"])


@router.get(
    "/scenes/{scene_id}",
    summary="What a generative world model may condition on for one scene, digest-bound.",
)
def scene_bundle(
    scene_id: Annotated[uuid.UUID, Path()],
    connection: ReadOnlyConnection,
    session: CurrentSession,
    services: Annotated[Services, Depends(get_services)],
) -> JSONResponse:
    with connection.transaction():
        connection.execute("set transaction isolation level repeatable read read only")
        try:
            bundle = world_read_bundle(connection, session.workspace_id, scene_id, services.store)
        except CanonicalisationError as error:
            # A coordinate this reader cannot encode is a degenerate receipt, not a missing scene.
            # 424 rather than 500, and rather than 404, so the caller learns the scene is theirs
            # and unreadable instead of being told it does not exist.
            return _problem(424, "unreadable_scene", str(error))
        if bundle is None:
            if _withdrawn(connection, session.workspace_id, scene_id):
                return _problem(410, "tombstoned", "this reconstructed scene was withdrawn")
            return _problem(404, "unknown_reference", "no such scene")
        dependencies = {
            key: scene_inputs(connection, session.workspace_id, key, services.store)
            for key in bundle_scene_ids(bundle)
        }
        at_time = evaluation_time(connection)
        if not dependencies or not all(
            scene_allowed(connection, session.workspace_id, key, value, at_time)
            for key, value in dependencies.items()
        ):
            return _problem(404, "unknown_reference", "current scene inputs are unavailable")
        response = JSONResponse(content=bundle, headers={"Cache-Control": "private, no-store"})
    with final_check(connection) as at_time:
        if not views_current(connection, session.workspace_id, bundle, at_time):
            return _problem(409, "view_changed", "posed view selection changed; refresh bundle")
        if not all(
            scene_allowed(connection, session.workspace_id, key, value, at_time)
            for key, value in dependencies.items()
        ):
            return _problem(404, "unknown_reference", "current scene inputs are unavailable")
    return response


@router.get(
    "/places/{place_id}",
    summary="What a generative world model may condition on for one place at one time.",
)
def place_bundle(
    place_id: Annotated[uuid.UUID, Path()],
    connection: ReadOnlyConnection,
    session: CurrentSession,
    services: Annotated[Services, Depends(get_services)],
    at: Annotated[
        dt.datetime | None,
        Query(description="Resolve the version of this place in force at this instant."),
    ] = None,
) -> JSONResponse:
    """A place and a time, resolved to the version in force then.

    Four answers, and the reason they are four rather than two is that a caller can act on each.

    *   **404** for a place that does not exist and for another workspace's, indistinguishable,
        for the same M10 reason the scene address gives.
    *   **424** for a place with no anchor. The place row exists and has no shared frame yet,
        which is the window between creating it and its first accepted alignment. Answering 404
        would deny a place the caller can see, and 410 would say somebody deleted it.
    *   **410** for a place whose anchor was withdrawn. Every version's frame is the anchor's, so
        withdrawing the anchor's photographs takes the shared frame with it, and the caller
        holding an earlier bundle is entitled to learn that rather than to be told 404.
    *   **200** for a readable place, INCLUDING one with no version at or before ``at``. That is
        an answer, not an absence: the bundle carries the place, its versions and their times, no
        scene at all, and says which of those it is. Turning it into a 404 would report a place
        that exists as missing.

    ``at`` is optional and a missing one means the latest dated version rather than "now". A read
    whose answer depends on the clock has a digest that moves with no write behind it, which
    ``exulanica/graph/world_read.py`` records the cost of. A naive timestamp is refused rather
    than assumed to be UTC: the column is UTC and guessing is how an hour goes missing.
    """
    if at is not None and at.tzinfo is None:
        return _problem(
            422,
            "unzoned_time",
            "`at` must carry a UTC offset. This read will not assume one for you.",
        )
    with connection.transaction():
        connection.execute("set transaction isolation level repeatable read read only")
        try:
            bundle = place_read_bundle(
                connection, session.workspace_id, place_id, services.store, at=at
            )
        except CanonicalisationError as error:
            return _problem(424, "unreadable_place", str(error))
        if bundle is None:
            known, anchored = _place_state(connection, session.workspace_id, place_id)
            if not known:
                return _problem(404, "unknown_reference", "no such place")
            if not anchored:
                return _problem(
                    424,
                    "place_without_anchor",
                    "this place has no anchor scene, so it has no shared frame to read yet",
                )
            return _problem(410, "tombstoned", "this place's anchor scene was withdrawn")
        dependencies = {
            key: scene_inputs(connection, session.workspace_id, key, services.store)
            for key in bundle_scene_ids(bundle)
        }
        at_time = evaluation_time(connection)
        if not dependencies or not all(
            scene_allowed(connection, session.workspace_id, key, value, at_time)
            for key, value in dependencies.items()
        ):
            return _problem(404, "unknown_reference", "current scene inputs are unavailable")
        response = JSONResponse(content=bundle, headers={"Cache-Control": "private, no-store"})
    with final_check(connection) as at_time:
        if not views_current(connection, session.workspace_id, bundle, at_time):
            return _problem(409, "view_changed", "posed view selection changed; refresh bundle")
        if not all(
            scene_allowed(connection, session.workspace_id, key, value, at_time)
            for key, value in dependencies.items()
        ):
            return _problem(404, "unknown_reference", "current scene inputs are unavailable")
    return response


@router.get(
    "/scenes/{scene_id}/observations",
    summary="Which photographs actually observed each retained sparse point.",
)
def scene_observation_graph(
    scene_id: Annotated[uuid.UUID, Path()],
    connection: ReadOnlyConnection,
    session: CurrentSession,
    services: Annotated[Services, Depends(get_services)],
    limit: Annotated[
        int | None,
        Query(ge=1, description="Return at most this many points, in point-id order."),
    ] = None,
    after_point_id: Annotated[
        int | None,
        Query(description="Continue after this point id, from a previous page's next_point_id."),
    ] = None,
) -> JSONResponse:
    """Click-to-evidence's recorded half.

    A scene with no accepted pose receipt answers 404 alongside a missing and a foreign one. That
    is deliberate: "this scene exists but its pose was refused" is a fact about somebody's library,
    and the read surface does not distinguish reasons a caller may not have.

    ``limit`` and ``after_point_id`` page the answer, and no limit means the whole graph, which is
    what this route has always returned and what a client already reading it expects. The response
    says which one it got: MEASURED 2026-09-07 against the retained reference instance, the bowl
    scene's graph is 97,633,587 canonical bytes and the volcanic scene's is 1,179,240,157, so a
    caller who wants a page has to be able to ask for one, and a caller who gets a page has to be
    told so.
    """
    with connection.transaction():
        connection.execute("set transaction isolation level repeatable read read only")
        try:
            records = scene_observations(
                connection,
                session.workspace_id,
                scene_id,
                services.store,
                limit=limit,
                after_point_id=after_point_id,
            )
        except CanonicalisationError as error:
            return _problem(424, "unreadable_scene", str(error))
        if records is None:
            if _withdrawn(connection, session.workspace_id, scene_id):
                return _problem(410, "tombstoned", "this reconstructed scene was withdrawn")
            return _problem(404, "unknown_reference", "no observation graph for this scene")
        buffered = scene_inputs(connection, session.workspace_id, scene_id, services.store)
        if not scene_allowed(
            connection, session.workspace_id, scene_id, buffered, evaluation_time(connection)
        ):
            return _problem(404, "unknown_reference", "current observation inputs are unavailable")
        response = JSONResponse(content=records, headers={"Cache-Control": "private, no-store"})
    with final_check(connection) as at_time:
        if not scene_allowed(connection, session.workspace_id, scene_id, buffered, at_time):
            return _problem(404, "unknown_reference", "current observation inputs are unavailable")
    return response
