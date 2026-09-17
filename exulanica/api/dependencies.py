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

Two things happen in the application-level dependency and nowhere else, because each must happen
exactly once per request. A refusal is counted in ``route_permission_refusal`` before it is
raised, and a route whose declaration requires ``tiles.materialise`` is charged one tile against
the workspace quota before it runs, unless it is declared in
:data:`~exulanica.api.permissions.SELF_CHARGING_TILE_ROUTES`, which names the routes that charge
the quota themselves, once per tile delivered rather than once per request, and why each does.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

import psycopg
from fastapi import Depends, Header, Request

from exulanica.api.authorisation import TokenNotAccepted
from exulanica.api.permissions import (
    ACCOUNT_OWNER_PERMISSIONS,
    SELF_CHARGING_TILE_ROUTES,
    Authentication,
    Permission,
    PermissionRefused,
    Public,
    record_refusal,
    require,
    rule_for,
)
from exulanica.api.quotas import charge_tiles
from exulanica.api.services import Services
from exulanica.epistemics.assertions import AssertionWriter
from exulanica.identity import IdentityRepository
from exulanica.selection.validation import Session

__all__ = [
    "TILES_PER_REQUEST",
    "CurrentSession",
    "ReadOnlyConnection",
    "ScopedConnection",
    "WorkspaceIdentity",
    "authorise_route",
    "current_session",
    "get_services",
]


def get_services(request: Request) -> Services:
    return request.app.state.services


#: What one request to a ``tiles.materialise`` route is charged. One tile per request, because the
#: route that will carry it does not exist yet and a batch size is its decision to declare.
TILES_PER_REQUEST = 1

#: Where :func:`authorise_route` leaves the session it has already held to this route's
#: declaration, so :func:`current_session` does not resolve the caller a second time. Request state
#: is per request and set only by server code; nothing a client sends can reach it.
_AUTHORISED = "exulanica_authorised_session"


def _matched_path(request: Request) -> str | None:
    """The template of the route FastAPI matched, never the URL the caller sent."""
    return getattr(request.scope.get("route"), "path", None)


def _needs_no_credential(request: Request, path: str | None) -> bool:
    return isinstance(rule_for(request.method, path), Public | Authentication)


def _grant(request: Request, authorization: str | None) -> tuple[Session, frozenset[Permission]]:
    """Resolve the caller to a session and what it may do, or refuse.

    An explicit header always wins, including malformed or expired credentials. A failed bearer
    request cannot acquire different authority by falling back to a browser cookie.

    A bearer token holds the permissions its grant names. A browser session holds
    :data:`~exulanica.api.permissions.ACCOUNT_OWNER_PERMISSIONS`, and that is a declaration rather
    than a default: a browser session exists only for an account membership, migration 0058 allows
    exactly one membership role, ``owner``, and ``AccountRepository.session`` refuses any membership
    that is not it. ``tests/test_route_permissions.py`` reads that check and fails when a second
    role appears, so a new role cannot inherit the owner's grant by omission.

    The scheme is checked before a token is looked up, so a caller sending a basic credential gets
    the same refusal as a caller sending nothing, rather than having their value compared against
    the configured secrets.
    """
    services = get_services(request)
    if authorization is None and services.accounts is not None:
        return services.accounts.authenticate_request(request), ACCOUNT_OWNER_PERMISSIONS
    scheme, _, presented = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not presented:
        raise TokenNotAccepted("expected an Authorization header of the form 'Bearer <token>'")
    return services.tokens.grant_for(presented.strip())


def authorise_route(request: Request) -> None:
    """The route permission floor. Installed on the application, so it runs for every route.

    Public routes and the sign-in surface return at once and never look at a credential, so a
    liveness probe cannot go red because a token rotated and a sign-in cannot require the session
    it creates. Every other route resolves the caller, then its declaration, in that order, so an
    anonymous caller learns nothing about what a route requires. The header is read from the
    request rather than declared as a parameter, because a declared parameter here would advertise
    an Authorization header on the public routes too.
    """
    path = _matched_path(request)
    if _needs_no_credential(request, path):
        return
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
    charges_here = (request.method.upper(), path) not in SELF_CHARGING_TILE_ROUTES
    if (
        charges_here
        and not isinstance(rule, Public)
        and Permission.TILES_MATERIALISE in rule.permissions
    ):
        with services.database.session(session.workspace_id) as connection:
            charge_tiles(connection, session.workspace_id, TILES_PER_REQUEST)
    setattr(request.state, _AUTHORISED, session)


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


def scoped_connection(request: Request, session: CurrentSession) -> Iterator[psycopg.Connection]:
    """A connection bound to the caller's workspace, for the duration of one request."""
    with get_services(request).database.session(session.workspace_id) as connection:
        yield connection


def readonly_connection(request: Request, session: CurrentSession) -> Iterator[psycopg.Connection]:
    """The same, as the role that holds SELECT and nothing else, when one is configured."""
    services = get_services(request)
    with services.readonly_database.session(session.workspace_id) as connection:
        yield connection


ScopedConnection = Annotated[psycopg.Connection, Depends(scoped_connection)]
ReadOnlyConnection = Annotated[psycopg.Connection, Depends(readonly_connection)]


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
