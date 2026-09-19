"""What every route requires, declared once, and the refusal a missing grant produces.

Before this module a bearer token reached every router. Row-level security still kept one
workspace out of another's rows, but it was the only thing standing, which made a second boundary
carry a first boundary's load: a token issued for uploading photographs could also delete a
memory, withdraw a consent or rewrite the world. This is the first boundary.

**One declaration, and the router is what it is checked against.** :data:`ROUTE_RULES` maps every
mounted ``(method, path)`` to one of three declarations: :class:`Public`, carrying the reason the
route needs no credential; :class:`Authentication`, for the sign-in surface, which needs no prior
credential because it is where one is issued, checked and ended; or :class:`Requires`, naming the
permissions the route needs. Nothing
here enumerates routes by reading the route modules. :func:`require_complete_declaration` compares
the map against :func:`exulanica.api.routes.routable_paths`, the one walk of the router tree this
codebase has, and :func:`exulanica.api.app.create_app` refuses to build an application whose
surface and declaration disagree in either direction. A route added anywhere under
``exulanica/api/routes/`` therefore fails every test that builds the application, with its own
name in the message, until somebody decides what it requires. A declaration for a route that no
longer exists fails the same way, because a rule about nothing is the same defect pointing the
other way.

**The vocabulary is closed.** :class:`Permission` is an enum, a grant naming anything else is
refused when the token directory loads, and there is no wildcard: a wildcard would silently widen
the day the vocabulary grew. The members are derived from the surface that exists. Reads are
distinguished from writes, and the consequential writes are isolated so each has to be granted by
name: intake, deletion and withdrawal, person consent, admission, world write and operations.
Two members are not a surface of their own. ``model.invoke`` sits beside a read on every route
that may call a model, because those routes spend money and reach the network. ``tiles.materialise``
is required by no route today, deliberately: no on-demand tile route ships until this floor
exists, and when one does, declaring this permission is what meters it against
:mod:`exulanica.api.quotas`.

**Who holds what.** A bearer token holds exactly the permissions its grant in
``EXULANICA_API_TOKENS`` names. A browser session holds :data:`ACCOUNT_OWNER_PERMISSIONS`, because
a browser session exists only for an account membership and migration 0058 allows one membership
role, ``owner``. That is a declaration keyed on the role the database enforces, not a default: a
second role in 0058's check fails ``tests/test_route_permissions.py`` until it is given a grant of
its own here.

**Consent withdrawal rides with consent.** ``POST /person-subjects/{subject_id}/consents`` records
``granted``, ``revoked`` and ``withdrawn`` alike, and ``/identity/subjects/unlink`` withdraws what
``/identity/subjects/link`` confirmed. Both sit under ``consent.write``, so a credential that may
grant a person's consent may always withdraw it. ``deletion.write`` isolates the rest: deleting a
companion memory and revoking a confirmed identity or place decision.

**A refusal is recorded.** :func:`record_refusal` counts it in ``route_permission_refusal``
(migration 0061) under the caller's workspace, as the runtime role, before the refusal is
returned. That table is the alert: a credential probing routes it was not issued for leaves a
count per route rather than nothing. Adding a member to :class:`Permission` needs a migration
widening that table's check, and ``tests/test_route_permissions.py`` fails until one exists.

**The refusal is not an existence oracle.** The rule in :mod:`exulanica.api.app` is followed
exactly. A route addressed by an id answers a missing permission with the same 404
``unknown_reference`` a nonexistent id gets, because M10 scores any 403 on an id-addressed route
as a cross-tenant leak and cannot tell why it was issued. A route with no id in its path is a
collection or an action on the caller's own workspace, so there is no other tenant whose existence
could leak, and it answers ``not_authorised`` with 403. The decision is taken before any lookup,
from the route template and the token alone, so the answer is identical for a real id, a foreign
id and an invented one.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

from exulanica.api.routes import routable_paths
from exulanica.errors import ExulanicaError

if TYPE_CHECKING:
    import psycopg

__all__ = [
    "ACCOUNT_OWNER_PERMISSIONS",
    "ROUTE_RULES",
    "SELF_CHARGING_TILE_ROUTES",
    "Authentication",
    "Permission",
    "PermissionRefused",
    "Public",
    "Requires",
    "RouteDeclarationError",
    "addressed_by_id",
    "authentication_routes",
    "parse_permissions",
    "public_paths",
    "record_refusal",
    "require",
    "require_complete_declaration",
    "rule_for",
    "stale_declarations",
    "undeclared_routes",
]


class Permission(StrEnum):
    """Everything a token can be granted. Nothing outside this enum is a permission."""

    #: The recorded library: graph, evidence, geometry, formation, World Read, Selection, the
    #: identity ledger, companion memory and admitted environment resources.
    LIBRARY_READ = "library.read"
    #: Identity decisions, place bridges and companion memory writes.
    LIBRARY_WRITE = "library.write"
    #: Any route that may call a model, which spends money and reaches the network.
    MODEL_INVOKE = "model.invoke"
    #: ``POST /intake``, the only way new photographs arrive.
    INTAKE_WRITE = "intake.write"
    #: Deleting a memory and revoking a confirmed decision.
    DELETION_WRITE = "deletion.write"
    #: Reading proposed person regions.
    CONSENT_READ = "consent.read"
    #: Region edits, person subjects, consent transitions and subject links, withdrawals included.
    CONSENT_WRITE = "consent.write"
    #: Reading personal admission status.
    ADMISSION_READ = "admission.read"
    #: Personal, reconstruction and environment source admission.
    ADMISSION_WRITE = "admission.write"
    #: The authored world: styles, interactions, reviewed assets, versions and society.
    WORLD_READ = "world.read"
    #: Every change to the authored world, and recording generated content against a scene.
    WORLD_WRITE = "world.write"
    #: Derivative and reconstruction job status.
    OPERATIONS_READ = "operations.read"
    #: Retrying a reconstruction job.
    OPERATIONS_WRITE = "operations.write"
    #: Materialising a tile on demand. Metered against the workspace tile quota.
    TILES_MATERIALISE = "tiles.materialise"


#: Routes that require ``tiles.materialise`` and charge the tile quota themselves, once per tile
#: rather than once per request, with the reason each does. :func:`authorise_route` charges one
#: tile for every other route requiring that permission, before it runs; for these it charges
#: nothing, because charging twice for one delivery would spend a ceiling on nothing.
SELF_CHARGING_TILE_ROUTES: Final[Mapping[tuple[str, str], str]] = MappingProxyType(
    {
        ("GET", "/tiles"): "metadata only: listing what is stored materialises no tile",
        ("GET", "/tiles/{baked_tile_id}/bytes"): (
            "migration 0072's ledger spends one tile the first time a workspace is served one, in "
            "the same statement as the delivery row; a reload of a tile already delivered is free"
        ),
        ("POST", "/world-generation/worlds"): (
            "one request covers every tile of the world it specifies, up to the 16 by 16 the "
            "declared extent range allows, so it charges one tile per tile it covers, counted "
            "from the resolved extents before a record is made. AN OPEN QUESTION RIDES WITH "
            "THIS ENTRY: a route that BAKES a generated city does not exist yet, and when one "
            "lands it has to decide whether it charges again for a tile whose generation was "
            "already charged here. Deciding it now would be deciding it without the route"
        ),
    }
)


class RouteDeclarationError(ExulanicaError):
    """The application's routes and :data:`ROUTE_RULES` disagree, so it must not be built."""


@dataclass(frozen=True, slots=True)
class Public:
    """A route that needs no credential, and the reason it does not."""

    reason: str

    def __post_init__(self) -> None:
        if not self.reason.strip():
            raise RouteDeclarationError("a public route must say why it needs no credential")


@dataclass(frozen=True, slots=True)
class Authentication:
    """A sign-in route: it needs no prior credential, because it issues, reports or ends one.

    Distinct from :class:`Public` because these routes do handle credentials, their own: a login
    cookie, provider state and an origin check. The permission floor stays out of their way and
    they refuse for themselves.
    """

    reason: str

    def __post_init__(self) -> None:
        if not self.reason.strip():
            raise RouteDeclarationError("a sign-in route must say what it does with a credential")


@dataclass(frozen=True, slots=True)
class Requires:
    """Every permission a caller must hold, all of them, to reach a route."""

    permissions: frozenset[Permission]

    def __post_init__(self) -> None:
        if not self.permissions:
            # An empty requirement is a public route that forgot to say why.
            raise RouteDeclarationError("a route that requires nothing must be declared Public")
        for permission in self.permissions:
            if not isinstance(permission, Permission):
                raise RouteDeclarationError(f"{permission!r} is not a Permission")


def _requires(*permissions: Permission) -> Requires:
    return Requires(frozenset(permissions))


_P = Permission

#: What a browser session holds. A browser session exists only for an account membership whose
#: role is ``owner``, the one role migration 0058 allows: the person whose workspace it is. Every
#: permission except ``tiles.materialise``, which waits for the first tile route to be declared and
#: is then granted here deliberately rather than inherited.
ACCOUNT_OWNER_PERMISSIONS: Final[frozenset[Permission]] = frozenset(
    {
        _P.LIBRARY_READ,
        _P.LIBRARY_WRITE,
        _P.MODEL_INVOKE,
        _P.INTAKE_WRITE,
        _P.DELETION_WRITE,
        _P.CONSENT_READ,
        _P.CONSENT_WRITE,
        _P.ADMISSION_READ,
        _P.ADMISSION_WRITE,
        _P.WORLD_READ,
        _P.WORLD_WRITE,
        _P.OPERATIONS_READ,
        _P.OPERATIONS_WRITE,
    }
)

#: Membership roles the account schema allows, each with the grant a browser session in that role
#: holds. ``tests/test_route_permissions.py`` compares the keys with migration 0058's check.
MEMBERSHIP_ROLE_PERMISSIONS: Final[Mapping[str, frozenset[Permission]]] = MappingProxyType(
    {"owner": ACCOUNT_OWNER_PERMISSIONS}
)
_LIBRARY_READ = _requires(_P.LIBRARY_READ)
_LIBRARY_WRITE = _requires(_P.LIBRARY_WRITE)
_WORLD_READ = _requires(_P.WORLD_READ)
_WORLD_WRITE = _requires(_P.WORLD_WRITE)
_CONSENT_WRITE = _requires(_P.CONSENT_WRITE)
_DELETION = _requires(_P.DELETION_WRITE)
_ADMISSION_WRITE = _requires(_P.ADMISSION_WRITE)
_OPERATIONS_READ = _requires(_P.OPERATIONS_READ)
_TILES = _requires(_P.TILES_MATERIALISE)
_NOT_DATA = "the schema of the API, which is not data"
_APPEARANCE = "/world/versions/{version_id}/characters/{subject_kind}/{subject_id}/appearance"

#: The single declaration of what each mounted route requires. Keyed by ``(method, path)`` exactly
#: as :func:`exulanica.api.routes.routable_paths` reports them.
#:
#: **A route added here is added to ``ROUTE_PROBES`` in tests/test_api.py in the same change**, or
#: to ``PUBLIC_ROUTES`` with the reason it needs no credential. That file's sweep is what holds a
#: route to refusing an anonymous caller, refusing a bad token and never answering a stranger 403;
#: a route with its own tests and no probe is held to none of those. The tile routes were added
#: without probes on 2026-09-17 and nothing but the sweep's own coverage check noticed.
ROUTE_RULES: Final[Mapping[tuple[str, str], Public | Authentication | Requires]] = MappingProxyType(
    {
        # -- public ------------------------------------------------------------------------
        ("GET", "/healthz"): Public(
            "a liveness probe that needed a credential would go red when the credential rotated"
        ),
        ("GET", "/readyz"): Public("the same, and it reports no workspace content"),
        ("GET", "/openapi.json"): Public(_NOT_DATA),
        ("GET", "/docs"): Public(_NOT_DATA),
        ("GET", "/docs/oauth2-redirect"): Public("part of the documentation page"),
        ("GET", "/redoc"): Public(_NOT_DATA),
        # -- the sign-in surface -----------------------------------------------------------
        ("GET", "/auth/google/start"): Authentication(
            "begins Google sign-in; there is no credential yet, and it sets only a login cookie"
        ),
        ("GET", "/auth/google/callback"): Authentication(
            "completes sign-in against its own login cookie, provider state and origin check"
        ),
        ("GET", "/auth/session"): Authentication(
            "reports the browser session its own cookie names, and refuses without one"
        ),
        ("POST", "/auth/logout"): Authentication(
            "ends the browser session its own cookie names, and must work for any holder of it"
        ),
        # -- the recorded library ----------------------------------------------------------
        ("GET", "/graph"): _LIBRARY_READ,
        ("GET", "/graph/sources"): _LIBRARY_READ,
        ("GET", "/evidence"): _LIBRARY_READ,
        ("GET", "/evidence/{span_id}"): _LIBRARY_READ,
        ("GET", "/evidence/{span_id}/masked"): _LIBRARY_READ,
        ("GET", "/evidence/{span_id}/region"): _LIBRARY_READ,
        ("GET", "/formation"): _LIBRARY_READ,
        ("GET", "/formation/{batch_id}"): _LIBRARY_READ,
        ("GET", "/geometry"): _LIBRARY_READ,
        ("GET", "/geometry/{artifact_id}"): _LIBRARY_READ,
        ("GET", "/scene-geometry/{artifact_id}"): _LIBRARY_READ,
        ("GET", "/scene-segments/{scene_id}"): _LIBRARY_READ,
        ("GET", "/world-read/places/{place_id}"): _LIBRARY_READ,
        ("GET", "/world-read/scenes/{scene_id}"): _LIBRARY_READ,
        ("GET", "/world-read/scenes/{scene_id}/observations"): _LIBRARY_READ,
        ("GET", "/world-read/scenes/{scene_id}/observations/resolve"): _LIBRARY_READ,
        ("GET", "/world-read/scenes/{scene_id}/observations/summary"): _LIBRARY_READ,
        ("POST", "/selection"): _LIBRARY_READ,
        ("POST", "/selection/packet"): _LIBRARY_READ,
        ("GET", "/selection/catalogue"): _LIBRARY_READ,
        ("GET", "/selection/place-bridges"): _LIBRARY_READ,
        ("GET", "/identity/events"): _LIBRARY_READ,
        ("GET", "/companion/memory/recent"): _LIBRARY_READ,
        ("GET", "/environment-resources/sources/{admission_id}/features"): _LIBRARY_READ,
        ("GET", "/environment-resources/{kind}/{resource_id}"): _LIBRARY_READ,
        ("GET", "/environment-resources/{kind}/{resource_id}/bytes"): _LIBRARY_READ,
        # -- library writes ----------------------------------------------------------------
        ("POST", "/identity/name"): _LIBRARY_WRITE,
        ("POST", "/identity/rename"): _LIBRARY_WRITE,
        ("POST", "/identity/confirm"): _LIBRARY_WRITE,
        ("POST", "/identity/reject"): _LIBRARY_WRITE,
        ("POST", "/identity/merge"): _LIBRARY_WRITE,
        ("POST", "/identity/split"): _LIBRARY_WRITE,
        ("POST", "/identity/undo"): _LIBRARY_WRITE,
        ("POST", "/selection/place-bridges"): _LIBRARY_WRITE,
        ("POST", "/companion/memory/answers"): _LIBRARY_WRITE,
        ("POST", "/companion/memory/escapes"): _LIBRARY_WRITE,
        ("POST", "/companion/memory/answers/{answer_id}/corrections"): _LIBRARY_WRITE,
        # -- routes that may call a model --------------------------------------------------
        ("POST", "/selection/plan"): _requires(_P.LIBRARY_READ, _P.MODEL_INVOKE),
        ("POST", "/selection/ask"): _requires(_P.LIBRARY_READ, _P.MODEL_INVOKE),
        ("POST", "/selection/appearance"): _requires(_P.WORLD_READ, _P.MODEL_INVOKE),
        ("POST", "/selection/environment"): _requires(_P.WORLD_READ, _P.MODEL_INVOKE),
        # The decision provider is a model; the endpoint reaches it through
        # exulanica.api.society_decision_runtime.request_decision, and records what it proposed.
        ("POST", "/world/versions/{version_id}/society/decisions"): _requires(
            _P.WORLD_WRITE, _P.MODEL_INVOKE
        ),
        # -- intake ------------------------------------------------------------------------
        ("POST", "/intake"): _requires(_P.INTAKE_WRITE),
        # -- deletion and withdrawal -------------------------------------------------------
        ("DELETE", "/companion/memory/answers/{answer_id}"): _DELETION,
        ("POST", "/identity/revoke"): _DELETION,
        ("POST", "/selection/place-bridges/{decision_id}/revoke"): _DELETION,
        # -- person consent ----------------------------------------------------------------
        ("GET", "/person-regions/{capture_id}"): _requires(_P.CONSENT_READ),
        ("POST", "/person-regions/{capture_id}/edits"): _CONSENT_WRITE,
        ("POST", "/person-subjects"): _CONSENT_WRITE,
        ("POST", "/person-subjects/{subject_id}/consents"): _CONSENT_WRITE,
        ("POST", "/identity/subjects/link"): _CONSENT_WRITE,
        ("POST", "/identity/subjects/unlink"): _CONSENT_WRITE,
        # -- admission ---------------------------------------------------------------------
        ("GET", "/personal-admission"): _requires(_P.ADMISSION_READ),
        ("POST", "/personal-admission"): _ADMISSION_WRITE,
        ("POST", "/personal-admission/model-rights/{right_id}/withdraw"): _ADMISSION_WRITE,
        ("POST", "/operations/reconstruction-admission"): _ADMISSION_WRITE,
        ("POST", "/environment-resources/sources"): _ADMISSION_WRITE,
        ("POST", "/environment-resources/sources/{admission_id}/feature-indexes"): (
            _ADMISSION_WRITE
        ),
        # -- operations --------------------------------------------------------------------
        ("GET", "/operations/derivative-jobs"): _OPERATIONS_READ,
        ("GET", "/operations/derivative-jobs/{job_id}/events"): _OPERATIONS_READ,
        ("GET", "/operations/reconstruction-scenes"): _OPERATIONS_READ,
        ("GET", "/operations/reconstruction-scenes/{job_id}"): _OPERATIONS_READ,
        ("POST", "/operations/reconstruction-scenes/{job_id}/retry"): _requires(
            _P.OPERATIONS_WRITE
        ),
        # -- the authored world, read ------------------------------------------------------
        ("GET", "/world/assets"): _WORLD_READ,
        ("GET", "/world/assets/{asset_key}"): _WORLD_READ,
        ("GET", "/world/assets/{asset_key}/bytes"): _WORLD_READ,
        ("GET", "/world/assets/{asset_key}/licence"): _WORLD_READ,
        ("GET", "/world/source-media"): _WORLD_READ,
        ("GET", "/world/source-media/{source_id}"): _WORLD_READ,
        ("GET", "/world/styles/catalog"): _WORLD_READ,
        ("GET", "/world/styles/current"): _WORLD_READ,
        ("GET", "/world/styles/proposals/{proposal_id}"): _WORLD_READ,
        ("GET", "/world/styles/versions"): _WORLD_READ,
        ("GET", "/world/interactions/catalog"): _WORLD_READ,
        ("GET", "/world/interactions/current"): _WORLD_READ,
        ("GET", "/world/interactions/proposals/{proposal_id}"): _WORLD_READ,
        ("GET", "/world/interactions/recommendations"): _WORLD_READ,
        ("GET", "/world/interactions/versions"): _WORLD_READ,
        ("GET", "/world/versions"): _WORLD_READ,
        ("GET", "/world/versions/{version_id}"): _WORLD_READ,
        ("GET", "/world/versions/{version_id}/society"): _WORLD_READ,
        ("GET", "/world/versions/{version_id}/society/events"): _WORLD_READ,
        ("GET", "/world/versions/{version_id}/society/replay"): _WORLD_READ,
        ("GET", "/world/versions/{version_id}/society/district"): _WORLD_READ,
        ("GET", "/world/versions/{version_id}/society/control"): _WORLD_READ,
        ("GET", "/world/versions/{version_id}/society/control/events"): _WORLD_READ,
        ("GET", "/world/versions/{version_id}/society/actions"): _WORLD_READ,
        ("GET", "/world/versions/{version_id}/society/actions/{request_id}"): _WORLD_READ,
        ("GET", "/world/versions/{version_id}/society/decisions/{request_id}"): _WORLD_READ,
        ("GET", _APPEARANCE): _WORLD_READ,
        ("GET", _APPEARANCE + "/history"): _WORLD_READ,
        ("GET", _APPEARANCE + "/families"): _WORLD_READ,
        # -- asking for a generated world, and the parameters one can be asked for by -----
        # The catalog is a read of declared data and materialises nothing, so it is a world read
        # like the style catalog beside it. The generation route is metered instead: it is the
        # first route whose cost scales with what the caller asked for.
        ("GET", "/world-generation/grammars"): _WORLD_READ,
        ("POST", "/world-generation/worlds"): _TILES,
        # -- baked tiles of a generated city -----------------------------------------------
        ("GET", "/tiles"): _TILES,
        ("GET", "/tiles/{baked_tile_id}/bytes"): _TILES,
        ("GET", "/materials/makers"): _WORLD_READ,
        ("GET", "/materials/library"): _WORLD_READ,
        ("GET", "/materials/recipes"): _WORLD_READ,
        ("GET", "/materials/recipes/{recipe_id}"): _WORLD_READ,
        ("GET", "/materials/recipes/{recipe_id}/bake"): _WORLD_READ,
        ("GET", "/materials/recipes/{recipe_id}/bake/bytes"): _WORLD_READ,
        # -- the authored world, write -----------------------------------------------------
        ("POST", "/world/styles/previews"): _WORLD_WRITE,
        ("DELETE", "/world/styles/previews/{preview_id}"): _WORLD_WRITE,
        ("POST", "/world/styles/previews/{preview_id}/apply"): _WORLD_WRITE,
        ("POST", "/world/styles/rollback"): _WORLD_WRITE,
        ("POST", "/world/interactions/previews"): _WORLD_WRITE,
        ("DELETE", "/world/interactions/previews/{preview_id}"): _WORLD_WRITE,
        ("POST", "/world/interactions/previews/{preview_id}/apply"): _WORLD_WRITE,
        ("POST", "/world/interactions/rollback"): _WORLD_WRITE,
        ("POST", "/world/versions"): _WORLD_WRITE,
        ("POST", "/world/versions/bootstrap"): _WORLD_WRITE,
        ("POST", "/world/versions/{version_id}/objects"): _WORLD_WRITE,
        ("POST", "/world/versions/{version_id}/objects/undo"): _WORLD_WRITE,
        ("POST", "/world/versions/{version_id}/objects/{object_id}/move"): _WORLD_WRITE,
        ("POST", "/world/versions/{version_id}/objects/{object_id}/remove"): _WORLD_WRITE,
        ("POST", "/world/versions/{version_id}/environment-instances"): _WORLD_WRITE,
        ("POST", "/world/versions/{version_id}/environment-instances/undo"): _WORLD_WRITE,
        ("POST", "/world/versions/{version_id}/environment-instances/{instance_id}/move"): (
            _WORLD_WRITE
        ),
        ("POST", "/world/versions/{version_id}/environment-instances/{instance_id}/remove"): (
            _WORLD_WRITE
        ),
        ("POST", "/world/versions/{version_id}/society"): _WORLD_WRITE,
        ("POST", "/world/versions/{version_id}/society/steps"): _WORLD_WRITE,
        ("PUT", "/world/versions/{version_id}/society/control"): _WORLD_WRITE,
        ("POST", "/world/versions/{version_id}/society/control/steps"): _WORLD_WRITE,
        ("POST", "/world/versions/{version_id}/society/actions"): _WORLD_WRITE,
        ("PUT", _APPEARANCE): _WORLD_WRITE,
        ("POST", _APPEARANCE + "/reset"): _WORLD_WRITE,
        # A bake request is a compute amplifier, bounded per workspace by migration 0066's quota.
        ("POST", "/materials/recipes"): _WORLD_WRITE,
        ("POST", "/materials/recipes/{recipe_id}/withdraw"): _WORLD_WRITE,
        ("POST", "/materials/recipes/{recipe_id}/bake"): _WORLD_WRITE,
        ("POST", "/world-write/scenes/{scene_id}/generated"): _WORLD_WRITE,
    }
)


def rule_for(method: str, path: str | None) -> Public | Authentication | Requires | None:
    """The declaration for one matched route, or None when there is none.

    Read from the module attribute at call time rather than captured, so the one map is the one
    thing consulted. ``None`` is not a permission: every caller treats it as a refusal.
    """
    if path is None:
        return None
    return ROUTE_RULES.get((method.upper(), path))


def addressed_by_id(path: str) -> bool:
    """Whether a route names a resource by an id, which decides 404 over 403 on refusal."""
    return "{" in path


class PermissionRefused(ExulanicaError):
    """The session does not hold what the route requires, so the route never ran.

    ``status`` and ``code`` follow the rule in :mod:`exulanica.api.app`: an id-addressed route
    answers exactly as it would for an id that does not exist, and anything else is a 403. The
    detail of the 404 names no permission and no id, so it is the same string for every id.
    """

    def __init__(self, *, method: str, path: str | None, missing: frozenset[Permission]) -> None:
        self.method = method
        self.path = path
        self.missing = missing
        self.addressed_by_id = path is None or addressed_by_id(path)
        if self.addressed_by_id:
            self.status = 404
            self.code = "unknown_reference"
            detail = "nothing at this address is available to this credential"
        else:
            self.status = 403
            self.code = "not_authorised"
            if missing:
                detail = (
                    f"this credential does not hold {', '.join(sorted(missing))}, "
                    f"which {method} {path} requires"
                )
            else:
                detail = f"{method} {path} declares no permission, so nobody may call it"
        super().__init__(detail)
        self.detail = detail


def require(
    held: frozenset[Permission], method: str, path: str | None
) -> Public | Authentication | Requires:
    """Refuse unless ``held`` covers the route's declaration. Returns the declaration.

    A route with no declaration refuses everybody. That branch is unreachable in an application
    :func:`exulanica.api.app.create_app` built, because the build refuses an undeclared route, and
    it exists so that being unreachable is not what makes it safe.
    """
    rule = rule_for(method, path)
    if isinstance(rule, Public | Authentication):
        return rule
    if rule is None:
        raise PermissionRefused(method=method, path=path, missing=frozenset())
    missing = rule.permissions - held
    if missing:
        raise PermissionRefused(method=method, path=path, missing=frozenset(missing))
    return rule


def parse_permissions(raw: object, *, where: str) -> frozenset[Permission]:
    """A grant's permission list, validated, or a ``ValueError`` naming what is wrong.

    Strict on purpose, because this is the line between a credential and what it may do. The
    value must be a non-empty list of distinct strings, each a member of :class:`Permission`.
    Absence is not an empty grant and it is not a full one: a grant that does not say what it
    permits does not load.
    """
    if raw is None:
        raise ValueError(
            f"{where} has no 'permissions'. Every grant names what it may do, from: "
            f"{', '.join(sorted(Permission))}. There is no default grant."
        )
    if not isinstance(raw, list) or not raw:
        raise ValueError(f"{where}: 'permissions' must be a non-empty JSON array of strings")
    seen: set[Permission] = set()
    for item in raw:
        if not isinstance(item, str):
            raise ValueError(f"{where}: {item!r} in 'permissions' is not a string")
        try:
            permission = Permission(item)
        except ValueError:
            raise ValueError(
                f"{where}: {item!r} is not a permission. The vocabulary is closed and has no "
                f"wildcard: {', '.join(sorted(Permission))}"
            ) from None
        if permission in seen:
            raise ValueError(f"{where}: {item!r} is listed twice in 'permissions'")
        seen.add(permission)
    return frozenset(seen)


def undeclared_routes(app: object) -> list[tuple[str, str]]:
    """Mounted routes with no declaration."""
    return [key for key in routable_paths(app) if key not in ROUTE_RULES]


def stale_declarations(app: object) -> list[tuple[str, str]]:
    """Declarations for routes the application does not serve."""
    mounted = set(routable_paths(app))
    return sorted(key for key in ROUTE_RULES if key not in mounted)


def require_complete_declaration(app: object) -> int:
    """Refuse an application whose surface and :data:`ROUTE_RULES` disagree. Returns the count.

    The count is returned so a caller can assert the sweep saw the application rather than an
    empty list: a comparison over nothing agrees with everything.
    """
    swept = routable_paths(app)
    problems: list[str] = []
    if missing := [key for key in swept if key not in ROUTE_RULES]:
        problems.append(
            "these routes declare no permission, so nobody could decide who may call them: "
            + ", ".join(f"{method} {path}" for method, path in missing)
            + ". Add each to ROUTE_RULES in exulanica/api/permissions.py, as Requires(...) or "
            "as Public(reason)."
        )
    if stale := stale_declarations(app):
        problems.append(
            "these declarations name routes the application does not serve: "
            + ", ".join(f"{method} {path}" for method, path in stale)
        )
    if problems:
        raise RouteDeclarationError(" ".join(problems))
    return len(swept)


def public_paths(
    rules: Iterable[tuple[tuple[str, str], Public | Authentication | Requires]] | None = None,
) -> set[str]:
    """Every path declared public, in the shape the two older public sets use."""
    items = ROUTE_RULES.items() if rules is None else rules
    return {path for (_method, path), rule in items if isinstance(rule, Public)}


def authentication_routes() -> set[tuple[str, str]]:
    """Every route declared as the sign-in surface."""
    return {key for key, rule in ROUTE_RULES.items() if isinstance(rule, Authentication)}


def record_refusal(
    connection: psycopg.Connection,
    *,
    workspace_id: uuid.UUID,
    actor: uuid.UUID,
    refused: PermissionRefused,
) -> None:
    """Count one refusal against the caller's workspace, on a connection scoped to it.

    Only the route template is stored, never the requested URL, so nothing a caller put in a path
    reaches the table. A refusal with nothing missing is the undeclared-route branch, which a
    built application cannot reach, and the table's check would refuse its empty list, so it is
    not recorded rather than recorded as something it is not.
    """
    if refused.path is None or not refused.missing:
        return
    connection.execute(
        "insert into route_permission_refusal "
        "(workspace_id, actor, http_method, route_path, missing_permissions) "
        "values (%s, %s, %s, %s, %s) "
        "on conflict (workspace_id, actor, http_method, route_path) do update set "
        "refusals = route_permission_refusal.refusals + 1, "
        "missing_permissions = excluded.missing_permissions",
        (
            workspace_id,
            actor,
            refused.method,
            refused.path,
            sorted(str(permission) for permission in refused.missing),
        ),
    )
