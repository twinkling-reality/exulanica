"""The public surface of the API, as data a review can read.

Two views of the same application, both generated and neither written by hand:

*   **The route table**: one row per mounted ``(method, path)``, in the order the application
    matches them, with the endpoint function, the OpenAPI operation id, the declared status, the
    response model, the request body, the database role the route is given and the permission
    rule :data:`exulanica.api.permissions.ROUTE_RULES` declares for it.
*   **The OpenAPI document** the application serves at ``/openapi.json``, rendered in the
    application's own key order, so path order still shows route order.

``scripts/snapshot_api_surface.py`` writes both into ``tests/snapshots/`` and
``tests/test_api_surface_snapshot.py`` holds the application to them, so a change to what a
client can call, send or receive is a diff somebody reads rather than a side effect of a refactor.
Nothing here enumerates routes by reading route modules: the rows come from the application's own
router through :func:`exulanica.api.routes.mounted_routes`, the walk ``routable_paths`` reads too.

**The database role** is the role of the connection a route is given by dependency injection:
``runtime`` for :data:`~exulanica.api.dependencies.ScopedConnection` (the non-owner runtime role
behind ``Services.database``), ``read-only`` for
:data:`~exulanica.api.dependencies.ReadOnlyConnection` (``Services.readonly_database``), and
``not injected`` for a route given neither. The last does not mean a route touches no database:
``/readyz`` and the sign-in routes open their own connections through their services, and the row
says only that no connection reaches them by dependency.
"""

from __future__ import annotations

import json
import types
import typing
from collections.abc import Callable, Iterator
from types import SimpleNamespace
from typing import Any, Final

from fastapi import FastAPI
from fastapi.routing import APIRoute

from exulanica.api.dependencies import readonly_connection, scoped_connection
from exulanica.api.permissions import Authentication, Public, Requires, rule_for
from exulanica.api.routes import mounted_routes

__all__ = [
    "DATABASE_ROLES",
    "render_openapi",
    "render_route_table",
    "route_table",
    "routing_only_application",
]

#: The connection dependencies a route can be given, and the role each one connects as.
DATABASE_ROLES: Final[dict[Callable[..., Any], str]] = {
    scoped_connection: "runtime",
    readonly_connection: "read-only",
}
_NOT_INJECTED: Final = "not injected"
#: The methods ``routable_paths`` leaves out, for the reason it gives: Starlette adds HEAD to every
#: GET and OPTIONS is never routed to an endpoint here.
_IMPLICIT_METHODS: Final = frozenset({"HEAD", "OPTIONS"})


def routing_only_application() -> FastAPI:
    """The real application, built without services, for reading its routes and schema.

    :func:`exulanica.api.app.create_app` reads three attributes of its services while it builds
    the router and nothing else until a request arrives, so this application can be walked and
    can produce its OpenAPI document with no database, store or credential configured. It cannot
    serve a request. A fourth attribute read at build time fails here loudly, by name.
    """
    from exulanica.api.app import create_app

    services = SimpleNamespace(
        society_decision_provider=None, society_base_tick_interval_ms=1000, society_runtime=None
    )
    return create_app(services, verify=False)  # type: ignore[arg-type]


def _type_name(annotation: object) -> str | None:
    """A response model as a reader writes it, without module paths that a move would change."""
    if annotation is None:
        return None
    origin = typing.get_origin(annotation)
    if origin is None:
        return getattr(annotation, "__name__", repr(annotation))
    arguments = [_type_name(argument) or "None" for argument in typing.get_args(annotation)]
    if origin in (typing.Union, types.UnionType):
        return " | ".join(arguments)
    return f"{getattr(origin, '__name__', repr(origin))}[{', '.join(arguments)}]"


def _dependency_calls(dependant: object) -> Iterator[object]:
    for dependency in getattr(dependant, "dependencies", ()):
        yield dependency.call
        yield from _dependency_calls(dependency)


def _database_role(route: object) -> str:
    if not isinstance(route, APIRoute):
        return _NOT_INJECTED
    calls = set(_dependency_calls(route.dependant))
    roles = sorted(role for call, role in DATABASE_ROLES.items() if call in calls)
    return ", ".join(roles) if roles else _NOT_INJECTED


def _permission(method: str, path: str) -> dict[str, object]:
    # Through rule_for, which reads the one map at call time, so the table cannot describe a
    # declaration other than the one the permission floor consults.
    rule = rule_for(method, path)
    if isinstance(rule, Requires):
        return {"requires": sorted(str(permission) for permission in rule.permissions)}
    if isinstance(rule, Public):
        return {"public": rule.reason}
    if isinstance(rule, Authentication):
        return {"authentication": rule.reason}
    # An application create_app built cannot reach this: it refuses an undeclared route.
    return {"undeclared": True}


def _request_body(operation: dict[str, Any] | None) -> str | None:
    """The body schema an operation takes, by component name, or its media type when inline."""
    if operation is None or "requestBody" not in operation:
        return None
    content = operation["requestBody"].get("content", {})
    for media_type, described in sorted(content.items()):
        reference = described.get("schema", {}).get("$ref")
        if reference:
            return reference.rsplit("/", 1)[-1]
        return media_type
    return None


def route_table(app: FastAPI) -> list[dict[str, object]]:
    """One row per mounted ``(method, path)``, in the order the application matches them."""
    paths = app.openapi().get("paths", {})
    rows: list[dict[str, object]] = []
    for route in mounted_routes(app):
        path = getattr(route, "path", None)
        if path is None:
            continue
        for method in sorted(set(getattr(route, "methods", None) or ()) - _IMPLICIT_METHODS):
            operation = paths.get(path, {}).get(method.lower())
            rows.append(
                {
                    "method": method,
                    "path": path,
                    "endpoint": getattr(route, "name", None),
                    "operation_id": None if operation is None else operation.get("operationId"),
                    "status_code": getattr(route, "status_code", None),
                    "response_model": _type_name(getattr(route, "response_model", None)),
                    "request_body": _request_body(operation),
                    "database_role": _database_role(route),
                    "permission": _permission(method, path),
                }
            )
    return rows


def render_route_table(rows: list[dict[str, object]]) -> str:
    """A JSON array with one route per line, so a changed route is a one-line diff."""
    lines = ",\n".join("  " + json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows)
    return f"[\n{lines}\n]\n"


def render_openapi(document: dict[str, Any]) -> str:
    """The OpenAPI document in the application's own key order, one value per line."""
    return json.dumps(document, ensure_ascii=False, indent=1) + "\n"
