"""What a caller may do, and whether it can happen now, projected from the authorities that decide.

A capability read answers, for one caller and one subject, which operations the product supports,
whether each is available now, and what each takes: the route that performs it, named by the
``"METHOD /path"`` key the permission declarations and the pinned route table use; the permissions
that route declares and whether the caller's grant holds them; the stale-base tokens its body
carries and the reads that return them; and the reads that list its options.

It decides nothing. A domain's adapter states an operation's availability from the predicate the
operation's own write path checks, and this module derives the rest from the application's router
and :data:`~exulanica.api.permissions.ROUTE_RULES`: a route renamed, a permission changed or a body
replaced reaches every read with no edit here. No option, bound, schema or permission is restated,
and nothing a request carries chooses what code runs. The reads are
:mod:`exulanica.api.routes.capabilities`; the contract is ``docs/capabilities/world-api.md``.

An operation is **available** when this server would attempt it now; its inputs may still be
refused by name, a stale base is still refused and a race may still refuse it. **Unavailable** is
supported here but prevented now by a dependency or a state, **unsupported** is never supported for
this world, engine or role, and **unknown** is deciding it needs a fact the caller may not read.
Each but the first carries the stable code the operation answers with. Permission is a separate
answer (``permitted``), so an operation can be available and not permitted to this caller.
"""

from __future__ import annotations

import threading
import uuid
import weakref
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Final, Literal

import psycopg
from fastapi import FastAPI, Request

from exulanica.api.permissions import Permission, Requires, rule_for
from exulanica.api.routes import mounted_routes
from exulanica.api.services import Services
from exulanica.selection.validation import Session
from exulanica.world.object_repository import SourceFacts
from exulanica.world.society_engines import SocietyEngine
from exulanica.world.society_grounds import SocietyGroundKind
from exulanica.world.worlds import WorldKind

__all__ = [
    "AVAILABLE",
    "Availability",
    "Base",
    "Effect",
    "Endpoint",
    "Operation",
    "Preview",
    "Route",
    "Subjects",
    "Surface",
    "VersionContext",
    "describe",
    "surface",
    "unavailable",
    "unknown",
    "unsupported",
]

State = Literal["available", "unavailable", "unsupported", "unknown"]
#: What a later consequence of an operation is about, by the domain's word: whether the world's
#: people use what was placed, whether a chosen model is asked here, whether the world advances
#: on its own after play.
EffectOn = Literal["society", "decisions", "playback"]
#: A route's endpoint function, which is how an adapter names a route without spelling its path.
Endpoint = Callable[..., Any]
#: The methods a route never declares itself: Starlette adds HEAD to every GET, and OPTIONS is
#: never routed to an endpoint (as :func:`exulanica.api.routes.routable_paths` reads them).
_IMPLICIT_METHODS: Final = frozenset({"HEAD", "OPTIONS"})
#: The statuses whose answer schema names what an operation returns.
_ANSWERED: Final = ("200", "201")


@dataclass(frozen=True, slots=True)
class Availability:
    """Whether an operation can happen now, and the code that says why not."""

    state: State
    code: str | None = None

    def __post_init__(self) -> None:
        if self.state == "available" and self.code is not None:
            raise ValueError("an available operation carries no refusal code")
        if self.state in ("unavailable", "unsupported") and not self.code:
            raise ValueError(f"an {self.state} operation names the code it is refused with")


AVAILABLE: Final = Availability("available")


def unavailable(code: str) -> Availability:
    """Supported here, and prevented now by a dependency or a state that ``code`` names."""
    return Availability("unavailable", code)


def unsupported(code: str) -> Availability:
    """Never supported for this world, engine or role, as ``code`` names."""
    return Availability("unsupported", code)


def unknown(code: str | None = None) -> Availability:
    """Deciding it needs a fact this caller may not read."""
    return Availability("unknown", code)


@dataclass(frozen=True, slots=True)
class Base:
    """A stale-base token an operation's body carries: its field, the read that returns the
    current value, and the field of that read holding it."""

    field: str
    read: Endpoint
    value: str


@dataclass(frozen=True, slots=True)
class Subjects:
    """The read, and the field of it, that lists what an operation may act on."""

    read: Endpoint
    field: str


@dataclass(frozen=True, slots=True)
class Preview:
    """The operation that shows another's effect without writing it, whether the write needs it,
    and the body field naming what was reviewed."""

    operation: Endpoint
    required: bool
    token: str | None = None


@dataclass(frozen=True, slots=True)
class Effect:
    """A consequence after an operation succeeds that this server may not produce."""

    on: EffectOn
    availability: Availability


@dataclass(frozen=True, slots=True)
class Operation:
    """What a domain adapter states about one of its routes. The rest is read from the route."""

    endpoint: Endpoint
    availability: Availability
    #: The domain's own word for what the operation acts on.
    subject: str | None
    #: The path values of this subject; a world's routes take ``world_id`` from the read itself.
    bind: Mapping[str, str] = field(default_factory=dict)
    subjects: Subjects | None = None
    base: tuple[Base, ...] = ()
    #: The body field that makes a retry answer with the first result.
    idempotency: str | None = None
    preview: Preview | None = None
    #: The reads that list this operation's choices; never the choices themselves.
    options: tuple[Endpoint, ...] = ()
    #: Whether success records durable state: false for a preview or a read.
    writes: bool = True
    effects: tuple[Effect, ...] = ()
    #: Whether the operation may call a model or commit the world to one is read from its route's
    #: permissions (``model.invoke``). False narrows that for a route which holds ``model.invoke``
    #: only to decide who may act and calls no model: a reviewed exception the descriptor tests
    #: list. It is never widened.
    spends: Literal[False] | None = None

    def __post_init__(self) -> None:
        if self.spends is not None and self.spends is not False:
            raise ValueError("an operation may narrow spends to False, never widen it")


@dataclass(frozen=True, slots=True)
class VersionContext:
    """One world version as every adapter of a version's capability read is given it."""

    request: Request
    connection: psycopg.Connection
    session: Session
    services: Services
    held: frozenset[Permission]
    world_id: str
    kind: WorldKind
    version_id: uuid.UUID
    source: SourceFacts
    #: The society ground the society ground catalog states for the source's composer, or None
    #: where it states none.
    ground: SocietyGroundKind | None
    #: The version's society (``society_id``, ``engine_version``), or None before one is brought.
    society: Mapping[str, Any] | None
    #: The engine the version's society runs, or else the one the engine table creates a new one
    #: with on this ground; None where no ground is stated.
    engine: SocietyEngine | None

    @property
    def bind(self) -> dict[str, str]:
        return {"version_id": str(self.version_id)}


@dataclass(frozen=True, slots=True)
class Route:
    """One mounted route as a descriptor names it."""

    method: str
    path: str
    #: The OpenAPI component of its request body and of its answer, where it declares one.
    input: str | None
    output: str | None

    @property
    def key(self) -> str:
        return f"{self.method} {self.path}"


def _component(content: Mapping[str, Any] | None) -> str | None:
    schema = (content or {}).get("application/json", {}).get("schema", {})
    reference = schema.get("$ref")
    return reference.rsplit("/", 1)[-1] if isinstance(reference, str) else None


class Surface:
    """The application's routes by endpoint, read once from its router and OpenAPI document."""

    def __init__(self, app: FastAPI) -> None:
        paths = app.openapi().get("paths", {})
        routes: dict[Endpoint, list[Route]] = {}
        for node in mounted_routes(app):
            endpoint = getattr(node, "endpoint", None)
            path = getattr(node, "path", None)
            methods = sorted(set(getattr(node, "methods", None) or ()) - _IMPLICIT_METHODS)
            if endpoint is None or path is None:
                continue
            for method in methods:
                operation = paths.get(path, {}).get(method.lower(), {})
                answers = operation.get("responses", {})
                output = next(
                    (
                        found
                        for status in _ANSWERED
                        if (found := _component(answers.get(status, {}).get("content")))
                    ),
                    None,
                )
                routes.setdefault(endpoint, []).append(
                    Route(
                        method=method,
                        path=path,
                        input=_component(operation.get("requestBody", {}).get("content")),
                        output=output,
                    )
                )
        self._routes = routes

    def route(self, endpoint: Endpoint) -> Route:
        """The one route ``endpoint`` serves, or a refusal naming the function."""
        found = self._routes.get(endpoint, [])
        if len(found) != 1:
            raise LookupError(
                f"{getattr(endpoint, '__qualname__', endpoint)!r} serves {len(found)} routes of "
                "this application, not one"
            )
        return found[0]


_SURFACES: Final[weakref.WeakKeyDictionary[FastAPI, Surface]] = weakref.WeakKeyDictionary()
_SURFACES_LOCK: Final = threading.Lock()


def surface(app: FastAPI) -> Surface:
    """The routes of ``app``, read the first time a capability read asks and kept with it."""
    with _SURFACES_LOCK:
        found = _SURFACES.get(app)
        if found is None:
            found = _SURFACES[app] = Surface(app)
        return found


def describe(operation: Operation, routes: Surface, held: frozenset[Permission]) -> dict[str, Any]:
    """One operation as a capability read serves it, for a caller holding ``held``."""
    route = routes.route(operation.endpoint)
    rule = rule_for(route.method, route.path)
    required = rule.permissions if isinstance(rule, Requires) else frozenset()
    invokes = Permission.MODEL_INVOKE in required
    if operation.spends is False and not invokes:
        raise ValueError(
            f"{route.key} requires no {Permission.MODEL_INVOKE}, so there is no spending to narrow"
        )
    preview = operation.preview
    return {
        "operation": route.key,
        "bind": dict(operation.bind),
        "requires": sorted(str(permission) for permission in required),
        "permitted": required <= held,
        "state": operation.availability.state,
        "code": operation.availability.code,
        "subject": operation.subject,
        "subjects": None
        if operation.subjects is None
        else {
            "read": routes.route(operation.subjects.read).key,
            "field": operation.subjects.field,
        },
        "input": route.input,
        "output": route.output,
        "base": [
            {"field": base.field, "read": routes.route(base.read).key, "value": base.value}
            for base in operation.base
        ],
        "idempotency": operation.idempotency,
        "preview": None
        if preview is None
        else {
            "operation": routes.route(preview.operation).key,
            "required": preview.required,
            "token": preview.token,
        },
        "options": [routes.route(read).key for read in operation.options],
        "writes": operation.writes,
        "spends": invokes and operation.spends is None,
        # A consequence of success is stated only for an operation that can succeed now.
        "effects": [
            {"on": effect.on, "state": effect.availability.state, "code": effect.availability.code}
            for effect in operation.effects
        ]
        if operation.availability.state == "available"
        else [],
        # Installation components an operation needs, from the installation facts once they are
        # served (D3); none are read yet, so none are named.
        "dependencies": [],
    }
