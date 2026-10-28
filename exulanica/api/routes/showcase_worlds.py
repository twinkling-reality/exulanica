"""The showcase worlds an installation serves, and the caller's own copy of one.

``GET /worlds/showcase`` answers the catalog (:mod:`exulanica.world.showcase_worlds`) as the lock
serves it, by key: each world's key, title, sentence, identity (the ``world_id`` every copy
of it is made under, so a page knows a world its workspace holds by its entry's) and card picture's
record, whose bytes ``GET /worlds/showcase/{showcase}/picture?sha256=`` answers while ``sha256`` is
their digest, so a browser keeps them as long as it likes, and a digest that is not its picture's
answers 404 ``picture_not_found``. Both read the installation's own files, the same for every
caller, and name nothing of any workspace; they need a session (``world.read``), a guest's
included.

``POST /worlds/showcase/{showcase}`` makes the served showcase world ``showcase`` names
(:mod:`exulanica.world.showcase_worlds`) in the caller's own workspace, made again from what its
making decided with no model call, under its identity, and answers its saved entry: 201 with the
copy made now, brought to life as the made world was (:mod:`exulanica.api.showcase_dressing`: its
people, and the cast given their models), or 200 with the copy the workspace already holds, as the
visitor left it. The answer's ``incomplete`` names each step of the dressing that did not happen,
by code; the world stands either way.

A key the installation does not serve answers 404 ``unknown_showcase_world`` on each route here,
the same for every caller: the catalog is the installation's, and nothing here reads or names
another workspace's world. A world on land where the deployment makes no worlds on land answers 422
``landform_not_served``. Every refusal of the making is the one ``POST /worlds/generated`` or a
kind's card answers, by name, with nothing written. The copy is held to the caller's own budgets
(a guest's included), and what its cast's minds decide is paid from the caller's own allowance, so
the route needs ``world.write`` and ``model.invoke``.
"""

from __future__ import annotations

from typing import Annotated, Any

import psycopg
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict

from exulanica.api.dependencies import (
    CurrentSession,
    ScopedConnection,
    get_services,
    holds_as_guest,
)
from exulanica.api.routes.society_control import host_base_tick_interval_ms
from exulanica.api.routes.world_entries import SavedWorldEntryView, _view
from exulanica.api.sayable import sayable
from exulanica.api.services import Services
from exulanica.api.showcase_dressing import dress_showcase
from exulanica.api.society_making import SocietyHooks
from exulanica.selection.validation import Session
from exulanica.world.composers import GeneratedWorldRefused, UnknownWorldComposer
from exulanica.world.kinds.samples import SiteRefused
from exulanica.world.kinds.worker import KindWorkWaiting
from exulanica.world.saved_entries import SavedWorldEntryRepository
from exulanica.world.showcase_worlds import make_showcase_world, showcase_world, showcase_worlds
from exulanica.world.worlds import WorldLimitReached, WorldsReadOnly, require_world_registration

router = APIRouter(prefix="/worlds", tags=["worlds"])

_PRIVATE = {"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"}


class ShowcasePictureView(BaseModel):
    """A showcase world's card picture: the engine's own first view of the world, by its digest."""

    model_config = ConfigDict(extra="forbid")

    sha256: str
    media_type: str
    width: int
    height: int


class ShowcaseWorldView(BaseModel):
    """A served showcase world, as a page offers it."""

    model_config = ConfigDict(extra="forbid")

    key: str
    #: The made world's title, which its copy is given.
    title: str
    #: The words the world was made from.
    sentence: str
    #: The identity every copy is made under.
    world_id: str
    #: Its card picture, or null where its document names none.
    picture: ShowcasePictureView | None


class ShowcaseCatalogView(BaseModel):
    """Every showcase world the installation serves, by key."""

    model_config = ConfigDict(extra="forbid")

    worlds: list[ShowcaseWorldView]


def _problem(
    status: int, code: str, detail: str, *, headers: dict[str, str] | None = None, **extra: Any
) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content=sayable({"code": code, "detail": detail, **extra}),
        headers=headers,
    )


@router.get(
    "/showcase",
    response_model=ShowcaseCatalogView,
    summary="The showcase worlds this installation serves, each with its card picture's digest.",
)
def showcase_catalog(_session: CurrentSession) -> JSONResponse:
    """Every served showcase world's key, title, sentence, identity and card picture's record."""
    catalog = ShowcaseCatalogView(
        worlds=[
            ShowcaseWorldView(
                key=world.key,
                title=world.title,
                sentence=world.sentence,
                world_id=world.world_id,
                picture=None
                if world.picture is None
                else ShowcasePictureView(
                    sha256=world.picture.sha256,
                    media_type=world.picture.media_type,
                    width=world.picture.width,
                    height=world.picture.height,
                ),
            )
            for world in showcase_worlds().values()
        ]
    )
    return JSONResponse(content=catalog.model_dump(mode="json"), headers=_PRIVATE)


@router.get(
    "/showcase/{showcase}/picture",
    summary="A showcase world's card picture, while the digest named is its own.",
    responses={404: {"description": "No showcase world of that key, or no picture of that digest"}},
)
def showcase_picture(
    showcase: str,
    _session: CurrentSession,
    sha256: Annotated[str, Query(pattern="^[0-9a-f]{64}$")],
) -> Response:
    """The card picture's bytes, while ``sha256`` is their digest: the address names the bytes, so
    a browser keeps them as long as it likes."""
    world = showcase_world(showcase)
    if world is None:
        return _problem(
            404, "unknown_showcase_world", "No showcase world of that name is served here."
        )
    if world.picture is None or world.picture.sha256 != sha256:
        return _problem(404, "picture_not_found", "no picture with this digest")
    return Response(
        content=world.picture.data,
        media_type=world.picture.media_type,
        headers={
            "ETag": f'"{sha256}"',
            "Cache-Control": "private, max-age=31536000, immutable",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post(
    "/showcase/{showcase}",
    status_code=201,
    summary="Make your own copy of a showcase world, or open the one you hold.",
    responses={
        200: {"description": "The copy the workspace already holds."},
        404: {"description": "No showcase world of that key is served here."},
        409: {"description": "Refused by name; nothing was written."},
    },
)
def open_showcase_world(
    showcase: str,
    request: Request,
    connection: ScopedConnection,
    session: CurrentSession,
    services: Annotated[Services, Depends(get_services)],
    guest: Annotated[bool, Depends(holds_as_guest)],
) -> JSONResponse:
    """Make the caller's copy of the showcase world ``showcase`` and bring it to life, or answer the
    copy the caller's workspace already holds."""
    from exulanica.grammar.landform import LandformRefused

    world = showcase_world(showcase)
    if world is None:
        return _problem(
            404, "unknown_showcase_world", "No showcase world of that name is served here."
        )
    if world.land is not None and not services.worlds_on_land:
        return _problem(
            422, "landform_not_served", "This server makes no worlds on land.", path="land"
        )
    try:
        require_world_registration(connection)
    except WorldsReadOnly as exc:
        return _problem(403, exc.code, str(exc))
    entries = SavedWorldEntryRepository(
        connection, session.workspace_id, services.store, guest=guest
    )
    try:
        entry, made = make_showcase_world(entries, world, created_by=session.actor)
    except SiteRefused as exc:
        return _problem(409, exc.code, str(exc), refusals=list(exc.refusals))
    except KindWorkWaiting as exc:
        return _problem(503, exc.code, str(exc), headers={"Retry-After": str(exc.retry_seconds)})
    except LandformRefused as exc:
        return _problem(422, exc.code, exc.detail, path=exc.path)
    except (GeneratedWorldRefused, UnknownWorldComposer, WorldLimitReached) as exc:
        return _problem(409, exc.code, str(exc))
    except psycopg.errors.UniqueViolation:
        # Two asks at once: the other made it, so this one answers that copy.
        entry, made = make_showcase_world(entries, world, created_by=session.actor)
    incomplete = (
        dress_showcase(
            SocietyHooks.of_app(request.app),
            connection,
            Session(workspace_id=session.workspace_id, actor=session.actor),
            entry.entry_id,
            world,
            # A visitor's copy opens playing, at the host's tick, as a made town does.
            playing_tick_ms=host_base_tick_interval_ms(request),
        )
        if made
        else []
    )
    view: SavedWorldEntryView = _view(
        entries.entry(entry.entry_id), societies_of_things=services.societies_of_things
    )
    return JSONResponse(
        status_code=201 if made else 200,
        content={"entry": view.model_dump(mode="json"), "made": made, "incomplete": incomplete},
    )
