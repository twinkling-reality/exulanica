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

Where a process was composed with an installation, each read also reads the installation's facts
(:func:`exulanica.api.installation.installation_facts`) once and hands them to :func:`describe`.
An operation names the components it needs to succeed (``Operation.needs``) and an effect the
component that decides it (``Effect.component``), by the installation's own component names.
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

from exulanica.api.installation import COMPONENTS, installation_facts
from exulanica.api.permissions import Permission, Requires, rule_for
from exulanica.api.routes import mounted_routes
from exulanica.api.services import Services
from exulanica.selection.validation import Session
from exulanica.spending.status import SpendingRefusals
from exulanica.traffic.errors import UnsupportedNetworkError
from exulanica.world.errors import InvalidStructuralData
from exulanica.world.object_repository import SourceFacts
from exulanica.world.society_engines import SocietyEngine
from exulanica.world.society_grounds import SocietyGroundKind
from exulanica.world.traffic_episodes import TrafficInput, TrafficRefused
from exulanica.world.traffic_host import saved_world_roads
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
    "installation_facts_of",
    "surface",
    "unavailable",
    "unknown",
    "unsupported",
]

State = Literal["available", "unavailable", "unsupported", "unknown"]
#: What a later consequence of an operation is about, by the domain's word: whether the world's
#: people use what was placed, whether a chosen model is asked here, whether the world advances
#: on its own after play, whether an admitted asset is prepared on this installation.
EffectOn = Literal["society", "decisions", "playback", "preparation"]
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
    #: The installation component whose state decides the effect where the installation's facts
    #: state it; ``availability`` stands where they do not.
    component: str | None = None

    def __post_init__(self) -> None:
        if self.component is not None and self.component not in COMPONENTS:
            raise ValueError(f"{self.component!r} is not an installation component")


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
    #: The installation components the operation needs to succeed, by the installation's names
    #: (:data:`~exulanica.api.installation.COMPONENTS`).
    needs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.spends is not None and self.spends is not False:
            raise ValueError("an operation may narrow spends to False, never widen it")
        unknown_names = [name for name in self.needs if name not in COMPONENTS]
        if unknown_names:
            raise ValueError(f"{unknown_names!r} are not installation components")


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
    #: What :meth:`roads` read, once it has: the roads, or the refusal reading them raised.
    _roads: TrafficInput | Exception | None = field(
        default=None, init=False, repr=False, compare=False
    )
    #: What :meth:`spending` read, once it has, as a one-item tuple: None is a read's answer too.
    _spending: tuple[SpendingRefusals | None] | None = field(
        default=None, init=False, repr=False, compare=False
    )

    @property
    def bind(self) -> dict[str, str]:
        return {"version_id": str(self.version_id)}

    def roads(self) -> TrafficInput:
        """The roads the version's snapshot states (:func:`saved_world_roads`), read once for
        every adapter that asks; each adapter answers the one read's refusal by its own codes."""
        outcome = self._roads
        if outcome is None:
            try:
                outcome = saved_world_roads(
                    self.connection,
                    self.session.workspace_id,
                    self.world_id,
                    self.source.snapshot_id,
                )
            except (TrafficRefused, UnsupportedNetworkError, InvalidStructuralData) as refused:
                outcome = refused
            object.__setattr__(self, "_roads", outcome)
        if isinstance(outcome, Exception):
            raise outcome.with_traceback(None)
        return outcome

    def spending(self) -> SpendingRefusals | None:
        """What admission would answer this workspace's next attempt, by provider
        (:meth:`Services.spending_refusals`), read once for every adapter that asks; None in a
        process no durable authority admits."""
        outcome = self._spending
        if outcome is None:
            outcome = (self.services.spending_refusals(self.connection, self.session.workspace_id),)
            object.__setattr__(self, "_spending", outcome)
        return outcome[0]


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


#: The component states that keep an operation which needs the component from succeeding. A
#: ``degraded`` component is listed and changes nothing; ``configured`` and ``ready`` are not
#: listed.
_PREVENTING: Final = frozenset({"not_installed", "unavailable", "refused"})
_UNLISTED: Final = frozenset({"configured", "ready"})
#: Why a process with no installation profile states a component it cannot see: listed, and never a
#: reason to refuse, since the process cannot tell whether another runs it.
_UNDECLARED: Final = "undeclared_installation"


def installation_facts_of(services: Services) -> Mapping[str, Any] | None:
    """The installation facts a capability read projects, read once for the whole read; None in a
    process composed with no installation (a ``Services`` built by hand), whose descriptors then
    name no dependency."""
    if services.installation is None:
        return None
    return installation_facts(services)


def _component_refusal(component: str, entry: Mapping[str, Any]) -> str:
    """The code a component's state refuses by: the installation's reason, else its state."""
    reason = entry.get("reason")
    return reason if isinstance(reason, str) else f"{component}_{entry['state']}"


def _installed(
    operation: Operation, facts: Mapping[str, Any] | None
) -> tuple[Availability, list[dict[str, Any]], tuple[Effect, ...]]:
    """The operation's availability, dependencies and effects under the installation's facts.

    A write is unavailable while the installation refuses to serve (a restore not complete), by the
    facts' reason. Otherwise the operation's own refusal stands, as its route answers it first; an
    operation its own predicate allows is unavailable by the first component it needs that is not
    installed, unavailable or refused. Each component it needs that is not configured or ready is
    listed by its state and reason; one a process cannot see without a profile is listed and
    decides nothing. An effect that names a component takes the component's state.
    """
    if facts is None:
        return operation.availability, [], operation.effects
    components = {entry["component"]: entry for entry in facts["components"]}
    needed = [
        (name, entry)
        for name in operation.needs
        if (entry := components.get(name)) is not None and entry["state"] not in _UNLISTED
    ]
    availability = operation.availability
    serving = facts["serving"]
    if operation.writes and serving["state"] == "refused":
        availability = unavailable(serving["reason"])
    elif availability.state == "available":
        blocking = next(
            (
                (name, entry)
                for name, entry in needed
                if entry["state"] in _PREVENTING and entry.get("reason") != _UNDECLARED
            ),
            None,
        )
        if blocking is not None:
            availability = unavailable(_component_refusal(*blocking))
    dependencies = [
        {"component": name, "state": entry["state"], "code": entry.get("reason")}
        for name, entry in needed
    ]
    effects = tuple(_effect(effect, components) for effect in operation.effects)
    return availability, dependencies, effects


def _effect(effect: Effect, components: Mapping[str, Mapping[str, Any]]) -> Effect:
    """``effect`` as its component's state decides it: unknown where a process without a profile
    cannot see the component, unavailable where it is not installed, unavailable or refused, and
    available otherwise; as the adapter stated it where the facts say nothing of the component."""
    entry = None if effect.component is None else components.get(effect.component)
    if effect.component is None or entry is None:
        return effect
    if entry.get("reason") == _UNDECLARED:
        decided = unknown(_UNDECLARED)
    elif entry["state"] in _PREVENTING:
        decided = unavailable(_component_refusal(effect.component, entry))
    else:
        decided = AVAILABLE
    return Effect(effect.on, decided, effect.component)


def describe(
    operation: Operation,
    routes: Surface,
    held: frozenset[Permission],
    facts: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """One operation as a capability read serves it, for a caller holding ``held``, under the
    installation's ``facts`` where the process has them (:func:`installation_facts_of`)."""
    route = routes.route(operation.endpoint)
    rule = rule_for(route.method, route.path)
    required = rule.permissions if isinstance(rule, Requires) else frozenset()
    invokes = Permission.MODEL_INVOKE in required
    if operation.spends is False and not invokes:
        raise ValueError(
            f"{route.key} requires no {Permission.MODEL_INVOKE}, so there is no spending to narrow"
        )
    preview = operation.preview
    availability, dependencies, effects = _installed(operation, facts)
    return {
        "operation": route.key,
        "bind": dict(operation.bind),
        "requires": sorted(str(permission) for permission in required),
        "permitted": required <= held,
        "state": availability.state,
        "code": availability.code,
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
            for effect in effects
        ]
        if availability.state == "available"
        else [],
        "dependencies": dependencies,
    }
