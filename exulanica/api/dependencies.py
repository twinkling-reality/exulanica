"""The four things a route is given, and why a route is given nothing else.

A route in this API validates and delegates. It receives a session, a connection already scoped
to that session's workspace, and whichever repository it needs, and it hands the work to the
package that owns it. There is no business logic in a route, which is a claim that is checkable:
every route function in this package is short enough to read in one screen, and the logic it
delegates to has its own tests that do not go through HTTP.

The connection dependency is where the workspace binding actually happens. It opens a session
through :meth:`exulanica.db.session.Database.session`, which issues
``set_config('exulanica.workspace_id', ...)`` before handing the connection over, so every query a
route runs is already under row-level security scoped to the caller. A route cannot forget,
because a route never opens a connection.

**Permissions are enforced here for the same reason.** :func:`authorise_route` is an
application-level dependency, installed by :func:`exulanica.api.app.create_app`, so FastAPI runs
it before every route's own dependencies, before path, query and body validation, and before any
connection is opened for the route. It reads the matched route's declaration from
:mod:`exulanica.api.permissions`, resolves the caller, and refuses a grant that does not cover
the declaration. A route cannot forget, because a route never registers it.
:func:`current_session`, which every authenticated route depends on, applies the identical check
itself when that dependency has not already run, so a route mounted on an application somebody
built without ``create_app`` is not left open by that omission.

Three things happen in the application-level dependency and nowhere else, because each must
happen exactly once per request. A refusal is counted in ``route_permission_refusal`` before it is
raised; an admitted request is counted against its workspace's share of its capacity class
(:mod:`exulanica.api.admission`), at the first moment the workspace is known; and a route whose
declaration requires ``tiles.materialise`` is charged one tile against the workspace quota before
it runs, unless it is declared in :data:`~exulanica.api.permissions.SELF_CHARGING_TILE_ROUTES`,
which names the routes that charge the quota themselves, once per tile delivered rather than once
per request, and why each does. The share is claimed after the permission check and before the
charge, so a request that is not permitted is refused exactly as it would be on an idle server,
and a request refused for capacity is never charged.

**The dependency is asynchronous and never touches a database on the event loop.** Public and
sign-in routes return without leaving the loop, so liveness needs no worker thread. Everything that
can reach a database, the credential lookup, the refusal record, the share and the charge, runs in
the threadpool, in that order.

**A channel route is the door's, and resolves the door's credential instead.** Its declaration
(:class:`~exulanica.api.permissions.Channel`) names which: the deployment's credential for one
bridge, or a channel credential that opens one grant (:mod:`exulanica.door.secrets`). Anything else
presented there, an account's token or a browser session included, is refused as an unknown
credential is, with 401, and a door credential presented on any other route meets the token
directory, which does not know it. A channel credential's workspace is claimed against its share of
the capacity class, as an account's is.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager
from typing import Annotated

import psycopg
from fastapi import Depends, Header, Request
from starlette.concurrency import run_in_threadpool

from exulanica.api.admission import claim_workspace
from exulanica.api.authorisation import TokenNotAccepted
from exulanica.api.permissions import (
    MEMBERSHIP_ROLE_PERMISSIONS,
    SELF_CHARGING_TILE_ROUTES,
    Authentication,
    Channel,
    Permission,
    PermissionRefused,
    Public,
    record_refusal,
    require,
    rule_for,
)
from exulanica.api.quotas import charge_tiles
from exulanica.api.services import Services
from exulanica.door.bridges import Bridge, BridgeNotAccepted
from exulanica.door.secrets import ChannelNotAccepted, ChannelSession, open_channel
from exulanica.epistemics.assertions import AssertionWriter
from exulanica.identity import IdentityRepository
from exulanica.selection.validation import Session

__all__ = [
    "TILES_PER_REQUEST",
    "CurrentBridge",
    "CurrentChannel",
    "CurrentSession",
    "HeldPermissions",
    "ReadOnlyConnection",
    "ReadOnlySessions",
    "ScopedConnection",
    "ScopedSessions",
    "WorkspaceIdentity",
    "authorise_route",
    "current_session",
    "get_services",
    "held_permissions",
]


def get_services(request: Request) -> Services:
    return request.app.state.services


#: Default charge for a ``tiles.materialise`` route that is not in
#: :data:`~exulanica.api.permissions.SELF_CHARGING_TILE_ROUTES`. One tile per request; a route
#: that charges by the world it specifies declares that count on its own entry.
TILES_PER_REQUEST = 1

#: Where :func:`authorise_route` leaves the session it has already held to this route's
#: declaration, so :func:`current_session` does not resolve the caller a second time. Request state
#: is per request and set only by server code; nothing a client sends can reach it.
_AUTHORISED = "exulanica_authorised_session"
#: Where it leaves the grant it held the route to, beside the session, for a read that says which
#: other routes the caller may use (:func:`held_permissions`).
_AUTHORISED_GRANT = "exulanica_authorised_grant"
#: Where it leaves what a channel route's door credential resolved to: the bridge, or the channel.
_DOOR_BRIDGE = "exulanica_door_bridge"
_DOOR_CHANNEL = "exulanica_door_channel"


def _matched_path(request: Request) -> str | None:
    """The template of the route FastAPI matched, never the URL the caller sent."""
    return getattr(request.scope.get("route"), "path", None)


def _needs_no_credential(request: Request, path: str | None) -> bool:
    return isinstance(rule_for(request.method, path), Public | Authentication)


def _grant(request: Request, authorization: str | None) -> tuple[Session, frozenset[Permission]]:
    """Resolve the caller to a session and what it may do, or refuse.

    An explicit header always wins, including malformed or expired credentials. A failed bearer
    request cannot acquire different authority by falling back to a browser cookie.

    A bearer token holds the permissions its grant names. A browser session holds the grant of its
    membership role, :data:`~exulanica.api.permissions.MEMBERSHIP_ROLE_PERMISSIONS`, and that is a
    declaration rather than a default: a browser session exists only for an account membership, the
    migrations allow ``owner`` and ``guest`` (0058, 0139), and ``AccountRepository.session``
    refuses any other. ``tests/test_route_permissions.py`` reads the latest check and fails when a
    role appears without a grant, so a new role cannot inherit another's by omission.

    The scheme is checked before a token is looked up, so a caller sending a basic credential gets
    the same refusal as a caller sending nothing, rather than having their value compared against
    the configured secrets.
    """
    services = get_services(request)
    if authorization is None and services.accounts is not None:
        account = services.accounts.browser_session(request)
        return account.session, MEMBERSHIP_ROLE_PERMISSIONS[account.role]
    scheme, _, presented = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not presented:
        raise TokenNotAccepted("expected an Authorization header of the form 'Bearer <token>'")
    return services.tokens.grant_for(presented.strip())


async def authorise_route(request: Request) -> None:
    """The route permission floor. Installed on the application, so it runs for every route.

    Public routes and the sign-in surface return at once and never look at a credential, so a
    liveness probe cannot go red because a token rotated, a sign-in cannot require the session it
    creates, and neither needs a worker thread. Every other route resolves the caller, then its
    declaration, in that order, so an anonymous caller learns nothing about what a route requires.
    The header is read from the request rather than declared as a parameter, because a declared
    parameter here would advertise an Authorization header on the public routes too.
    """
    path = _matched_path(request)
    if _needs_no_credential(request, path):
        return
    rule = rule_for(request.method, path)
    if isinstance(rule, Channel):
        await run_in_threadpool(_authorise_channel, request, rule)
        return
    await run_in_threadpool(_authorise, request, path)


def _bearer(request: Request) -> str:
    scheme, _, presented = (request.headers.get("authorization") or "").partition(" ")
    if scheme.lower() != "bearer" or not presented.strip():
        raise TokenNotAccepted("expected an Authorization header of the form 'Bearer <token>'")
    return presented.strip()


def _door_bridge(request: Request) -> Bridge:
    door = get_services(request).door
    presented = _bearer(request)
    if door is None:
        raise TokenNotAccepted("no door credential opens anything here")
    try:
        return door.bridges.for_credential(presented)
    except BridgeNotAccepted as exc:
        raise TokenNotAccepted("no door credential opens anything here") from exc


def _door_channel(request: Request) -> ChannelSession:
    services = get_services(request)
    presented = _bearer(request)
    if services.door is None:
        raise TokenNotAccepted("no door credential opens anything here")
    try:
        return open_channel(
            services.database, services.door.bridges, presented, services.door.open_to
        )
    except ChannelNotAccepted as exc:
        raise TokenNotAccepted("no door credential opens anything here") from exc


def _authorise_channel(request: Request, rule: Channel) -> None:
    """The door's half of the floor: resolve the credential a channel route declares, or refuse."""
    if rule.credential == "bridge":
        setattr(request.state, _DOOR_BRIDGE, _door_bridge(request))
        return
    channel = _door_channel(request)
    claim_workspace(request.scope, channel.workspace_id)
    setattr(request.state, _DOOR_CHANNEL, channel)


def current_bridge(request: Request) -> Bridge:
    """The bridge whose deployment credential reached this channel route."""
    found = getattr(request.state, _DOOR_BRIDGE, None)
    return found if found is not None else _door_bridge(request)


def current_channel(request: Request) -> ChannelSession:
    """The grant whose channel credential reached this channel route."""
    found = getattr(request.state, _DOOR_CHANNEL, None)
    return found if found is not None else _door_channel(request)


CurrentBridge = Annotated[Bridge, Depends(current_bridge)]
CurrentChannel = Annotated[ChannelSession, Depends(current_channel)]


def _authorise(request: Request, path: str | None) -> None:
    """The half of :func:`authorise_route` that may reach a database, run in a worker thread."""
    session, held = _grant(request, request.headers.get("authorization"))
    services = get_services(request)
    try:
        rule = require(held, request.method, path)
    except PermissionRefused as refused:
        with services.database.session(session.workspace_id) as connection:
            record_refusal(
                connection,
                workspace_id=session.workspace_id,
                actor=session.actor,
                refused=refused,
            )
        raise
    claim_workspace(request.scope, session.workspace_id)
    charges_here = (request.method.upper(), path) not in SELF_CHARGING_TILE_ROUTES
    if (
        charges_here
        and not isinstance(rule, Public)
        and Permission.TILES_MATERIALISE in rule.permissions
    ):
        with services.database.session(session.workspace_id) as connection:
            charge_tiles(connection, session.workspace_id, TILES_PER_REQUEST)
    setattr(request.state, _AUTHORISED, session)
    setattr(request.state, _AUTHORISED_GRANT, held)


def current_session(
    request: Request, authorization: Annotated[str | None, Header()] = None
) -> Session:
    """The caller's session, already held to the route's declaration.

    In an application ``create_app`` built, :func:`authorise_route` has already resolved and
    authorised this request, and its session is returned as it left it. Anywhere else this
    resolves the caller and applies the same declaration itself, because it is then the only
    check left.
    """
    authorised = getattr(request.state, _AUTHORISED, None)
    if authorised is not None:
        return authorised
    session, held = _grant(request, authorization)
    path = _matched_path(request)
    if not _needs_no_credential(request, path):
        require(held, request.method, path)
    return session


CurrentSession = Annotated[Session, Depends(current_session)]


def held_permissions(request: Request, _session: CurrentSession) -> frozenset[Permission]:
    """Everything the caller's grant holds, once the route's own declaration has held it.

    A capability read says whether the caller may use other routes, which needs the whole grant
    rather than the permissions its own route required. In an application ``create_app`` built,
    :func:`authorise_route` left the grant beside the session. Anywhere else
    :func:`current_session` has resolved the caller and applied the route's declaration, and the
    same grant is resolved again here. Request state is set only by server code.
    """
    held = getattr(request.state, _AUTHORISED_GRANT, None)
    if held is None:
        _, held = _grant(request, request.headers.get("authorization"))
    return held


HeldPermissions = Annotated[frozenset[Permission], Depends(held_permissions)]


def scoped_connection(request: Request, session: CurrentSession) -> Iterator[psycopg.Connection]:
    """A connection bound to the caller's workspace, for the duration of one request."""
    with get_services(request).database.session(session.workspace_id) as connection:
        yield connection


def readonly_connection(request: Request, session: CurrentSession) -> Iterator[psycopg.Connection]:
    """The same, as the role that holds SELECT and nothing else, when one is configured."""
    services = get_services(request)
    with services.readonly_database.session(session.workspace_id) as connection:
        yield connection


async def readonly_sessions(
    request: Request, session: CurrentSession
) -> Callable[[], AbstractContextManager[psycopg.Connection]]:
    """Short read-only connections bound to the caller's workspace, opened when the route asks.

    For a route that must not hold one connection for its whole response, which a streamed
    response otherwise does: a request-scoped connection is closed only after the response ends.
    The workspace is bound here, so the route still never names one.
    """
    database = get_services(request).readonly_database
    workspace_id = session.workspace_id
    return lambda: database.session(workspace_id)


async def scoped_sessions(
    request: Request, session: CurrentSession
) -> Callable[[], AbstractContextManager[psycopg.Connection]]:
    """Short connections as the runtime role, bound to the caller's workspace, opened when the
    route asks: :func:`readonly_sessions` for a route that needs the runtime role, such as one
    that authorizes bytes under the final read check and then streams them, so no connection is
    held while they are sent.
    """
    database = get_services(request).database
    workspace_id = session.workspace_id
    return lambda: database.session(workspace_id)


ScopedConnection = Annotated[psycopg.Connection, Depends(scoped_connection)]
ReadOnlyConnection = Annotated[psycopg.Connection, Depends(readonly_connection)]
ReadOnlySessions = Annotated[
    Callable[[], AbstractContextManager[psycopg.Connection]], Depends(readonly_sessions)
]
ScopedSessions = Annotated[
    Callable[[], AbstractContextManager[psycopg.Connection]], Depends(scoped_sessions)
]


class WorkspaceIdentity:
    """The identity repositories, built on the request's own connection.

    A small container rather than three separate dependencies, because every identity route
    needs the same three and constructing them is where the workspace is asserted a second time.
    """

    def __init__(self, connection: ScopedConnection, session: CurrentSession) -> None:
        self.connection = connection
        self.session = session
        self.repository = IdentityRepository(connection, session.workspace_id)
        self.assertions = AssertionWriter(connection, session.workspace_id)
