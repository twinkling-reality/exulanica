"""What every route requires, declared once, and the refusal a missing grant produces.

Before this module a bearer token reached every router. Row-level security still kept one
workspace out of another's rows, but it was the only thing standing, which made a second boundary
carry a first boundary's load: a token issued for uploading photographs could also delete a
memory, withdraw a consent or rewrite the world. This is the first boundary.

**One declaration, and the router is what it is checked against.** :data:`ROUTE_RULES` maps every
mounted ``(method, path)`` to one of three declarations: :class:`Public`, carrying the reason the
route needs no credential; :class:`Authentication`, for the sign-in surface, which needs no prior
credential because it is where one is issued, checked and ended; or :class:`Requires`, naming the
permissions the route needs, every one of which a caller must hold. Nothing
here enumerates routes by reading the route modules. :func:`require_complete_declaration` compares
the map against :func:`exulanica.api.routes.routable_paths`, the one walk of the router tree this
codebase has, and :func:`exulanica.api.app.create_app` refuses to build an application whose
surface and declaration disagree in either direction. A route added anywhere under
``exulanica/api/routes/`` therefore fails every test that builds the application, with its own
name in the message, until somebody decides what it requires. A declaration for a route that no
longer exists fails the same way, because a rule about nothing is the same defect pointing the
other way.

**A permission belongs to a route, never to what a request asks for.** The floor decides from the
matched route template and the grant, before the body is read, so nothing here can see a body.
A kind of request that needs a permission its siblings do not is given a route of its own and an
entry of its own, and the shared route refuses that kind for every caller. A depth estimate from
a photograph is that case: resolving one reads the photograph's admission state, so its
composition routes require ``admission.read`` beside ``world.write`` and the generic composition
routes refuse the ``photo_point_map`` kind.

**The vocabulary is closed.** :class:`Permission` is an enum, a grant naming anything else is
refused when the token directory loads, and there is no wildcard: a wildcard would silently widen
the day the vocabulary grew. The members are derived from the surface that exists. Reads are
distinguished from writes, and the consequential writes are isolated so each has to be granted by
name: intake, deletion and withdrawal, person consent, admission, world write and operations.
Two members are not a surface of their own. ``model.invoke`` sits beside a read on every route
that may call a model, because those routes spend money and reach the network, and beside a write
on the society route that commits a world to a model: the choice of the model that decides for a
person (``POST .../society/models``). That recorded choice is the authorization for the spend it
causes, so the door's grant route asks for it too when a grant names the mind a gate's travellers
get (``POST /door/grants`` with a ``traveller``), checked by the route because the body decides it.
The host's playback asks the chosen model for a listed workspace whoever plays the world,
so a token holding ``world.write`` without ``model.invoke`` may start spending by playing a world
whose owner chose a model (``PUT .../society/control``), always within the decision contract's
bounds per world and hour and the share of the process's budget it keeps for other work.
``tiles.materialise`` meters a route against :mod:`exulanica.api.quotas` by being declared on it,
and declaring it is the only way a route is metered. Three routes hold it: the two ``/tiles``
reads, which serve bytes an offline bake already made, and ``POST /world-generation/worlds``,
which is the first route whose cost scales with what the caller asked for and therefore the first
that charges MORE than one tile.

**Who holds what.** A bearer token holds exactly the permissions its grant in
``EXULANICA_API_TOKENS`` names. A browser session holds its membership role's grant
(:data:`MEMBERSHIP_ROLE_PERMISSIONS`): :data:`ACCOUNT_OWNER_PERMISSIONS` for an ``owner``,
:data:`GUEST_PERMISSIONS` for a ``guest`` (migration 0139), because a browser session exists only
for an account membership and the migrations allow those two roles. That is a declaration keyed on
the roles the database enforces, not a default: a role added to the latest check fails
``tests/test_route_permissions.py`` until it is given a grant of its own here.

**A creator's upload needs the operator's grant as well.** Sign-in makes any Google identity the
owner of a workspace, and an owner holds ``admission.write``, so a route that admits a creator's
bytes into a workspace (:data:`CREATOR_GRANT_ROUTES`) also asks a browser session whether its
account holds the creator grant, which the operator gives and revokes with
``exulanica-creator-grant``; without it the route answers 403 ``creator_grant_required`` before
its body is read. A bearer token is the operator's own grant to a program, so the permissions it
names are enough there.

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
    "CREATOR_GRANT_ROUTES",
    "GUEST_PERMISSIONS",
    "MEMBERSHIP_ROLE_PERMISSIONS",
    "ROUTE_RULES",
    "ROUTE_RULE_SECTIONS",
    "SELF_CHARGING_TILE_ROUTES",
    "Authentication",
    "Channel",
    "CreatorGrantRequired",
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
    "require_creator",
    "route_key",
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
    #: Reading proposed person regions, and where a place's name may go.
    CONSENT_READ = "consent.read"
    #: Region edits, person subjects, consent transitions, subject links and place name
    #: decisions, withdrawals included.
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
    #: Asking a web source for reference notes, which spends the operator's source credits and binds
    #: the person asking to the source's acceptable use policy. Held by an account owner and by a
    #: token whose grant names it; never by a guest.
    REFERENCES_REQUEST = "references.request"
    #: Letting an outside program into a world: issuing, opening and revoking a door grant. It
    #: always sits beside ``world.write``, and is isolated by name because a grant hands some of
    #: a world's choices to a program its owner does not run.
    DOOR_GRANT = "door.grant"


#: Routes that require ``tiles.materialise`` and charge the tile quota themselves, once per tile
#: rather than once per request, with the reason each does. :func:`authorise_route` charges one
#: tile for every other route requiring that permission, before it runs; for these it charges
#: nothing, because charging twice for one delivery would spend a ceiling on nothing.
SELF_CHARGING_TILE_ROUTES: Final[Mapping[tuple[str, str], str]] = MappingProxyType(
    {
        ("GET", "/tiles"): "metadata only: listing what is stored materialises no tile",
        ("GET", "/tiles/traffic"): (
            "a window reads the stored tiles' containers for the records their roads state and "
            "delivers no tile, so it materialises none"
        ),
        ("GET", "/tiles/{baked_tile_id}/bytes"): (
            "migration 0072's ledger spends one tile the first time a workspace is served one, in "
            "the same statement as the delivery row; a reload of a tile already delivered is free"
        ),
        ("POST", "/world-generation/worlds"): (
            "one request covers every tile of the world it specifies, up to the 16 by 16 the "
            "declared extent range allows, so it charges one tile per tile it covers, counted "
            "from the resolved extents before a record is made. A later bake of those same "
            "tiles must declare whether it charges again for a tile already counted here."
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


@dataclass(frozen=True, slots=True)
class Channel:
    """A route an outside program reaches with a door credential, and no account ever does.

    ``credential`` names which: ``bridge``, the deployment's credential for one admitted bridge,
    which only redeems an invite; or ``grant``, a channel credential that opens one grant's
    channel. The door resolves it before the route runs (:mod:`exulanica.door.secrets`); an
    account's token or browser session is refused here exactly as an unknown credential is, and
    a door credential reaches no other route, so the two families never overlap.
    """

    credential: str
    reason: str

    def __post_init__(self) -> None:
        if self.credential not in ("bridge", "grant"):
            raise RouteDeclarationError("a channel route takes a bridge or a grant credential")
        if not self.reason.strip():
            raise RouteDeclarationError("a channel route must say what its credential opens")


def _requires(*permissions: Permission) -> Requires:
    return Requires(frozenset(permissions))


_P = Permission

#: What an owner's browser session holds: the person whose workspace it is (a guest's holds
#: :data:`GUEST_PERMISSIONS`). Every permission except ``tiles.materialise``, which is withheld and
#: is an OPEN DECISION: three routes require it, and a browser session still cannot ask for a world
#: or read a tile's bytes. Granting it lets a browser spend the workspace's tile ceiling, which is
#: why it is granted here deliberately or not at all rather than inherited. A world generated from
#: a reviewed recipe
#: (``POST /worlds/generated``) is not asked for through that door: it is bounded by the
#: world-count policy's ``generated`` limit and the recipes' stated tile counts, not by the tile
#: quota, and its page reads its own baked tiles through its version
#: (``GET /world/versions/{version_id}/tiles/{baked_tile_id}/bytes``, world.read). A browser
#: session still holds no ``tiles.materialise``.
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
        _P.REFERENCES_REQUEST,
        _P.DOOR_GRANT,
    }
)

#: What a guest's browser session holds (migration 0139): a visitor who entered with no account
#: may make a world and open it, choose and swap the models that decide for its people, start and
#: read a comparison, ask the Companion, keep and correct what it remembers, and delete what they
#: made. Nothing else: no photograph intake, no consent or admission of a source, no operations
#: read or write (capacity and installation facts are every workspace's), and no tile ceiling. A
#: guest's allowance is read from ``GET /auth/session``, so it needs no ``operations.read``.
GUEST_PERMISSIONS: Final[frozenset[Permission]] = frozenset(
    {
        _P.WORLD_READ,
        _P.WORLD_WRITE,
        _P.MODEL_INVOKE,
        _P.LIBRARY_READ,
        _P.LIBRARY_WRITE,
        _P.DELETION_WRITE,
    }
)

#: Membership roles the account schema allows, each with the grant a browser session in that role
#: holds. ``tests/test_route_permissions.py`` compares the keys with the migrations' check (0058,
#: widened by 0139).
MEMBERSHIP_ROLE_PERMISSIONS: Final[Mapping[str, frozenset[Permission]]] = MappingProxyType(
    {"owner": ACCOUNT_OWNER_PERMISSIONS, "guest": GUEST_PERMISSIONS}
)

#: Routes that admit a creator's bytes into a workspace, each with what it admits. A browser
#: session reaches one only while its account holds the operator's creator grant
#: (:func:`require_creator`), beside the permissions the route declares; a bearer token's grant
#: is enough. Each is a declared route that names no id, so its 403 says nothing about what exists
#: (:func:`require_complete_declaration` holds both).
CREATOR_GRANT_ROUTES: Final[Mapping[tuple[str, str], str]] = MappingProxyType(
    {
        ("POST", "/workspace-style-packs"): "a creator's own style pack",
        ("POST", "/workspace-assets"): "a creator's own 3D asset",
    }
)
_LIBRARY_READ = _requires(_P.LIBRARY_READ)
_LIBRARY_WRITE = _requires(_P.LIBRARY_WRITE)
_WORLD_READ = _requires(_P.WORLD_READ)
_WORLD_WRITE = _requires(_P.WORLD_WRITE)

_NOT_DATA = "the schema of the API, which is not data"
_LIVENESS = "a liveness probe that needed a credential would go red when the credential rotated"
_READINESS = "the same, and it reports no workspace content"
_SIGN_IN_START = (
    "begins Google sign-in; there is no credential yet, and it sets only a login cookie"
)
_SIGN_IN_CALLBACK = (
    "completes sign-in against its own login cookie, provider state and origin check"
)
_SIGN_IN_SESSION = "reports the browser session its own cookie names, and refuses without one"
_SIGN_IN_LOGOUT = (
    "ends the browser session its own cookie names, and must work for any holder of it"
)
_SIGN_IN_GUEST = (
    "makes a guest's account, workspace and session; there is no credential yet, and it checks "
    "its own origin, entry code and day's limit"
)

#: Every method a route can be declared under: what routable_paths reports, which leaves out the
#: HEAD and OPTIONS Starlette adds by itself.
_DECLARABLE_METHODS: Final = frozenset({"DELETE", "GET", "PATCH", "POST", "PUT"})


def _every(rule: Requires, *routes: str) -> Mapping[str, Requires]:
    """One section: the requirement, then every route that has it, one ``METHOD /path`` a line."""
    twice = sorted({route for route in routes if routes.count(route) > 1})
    if twice:
        raise RouteDeclarationError(f"listed twice in one section: {', '.join(twice)}")
    return MappingProxyType(dict.fromkeys(routes, rule))


# -- The sections of ROUTE_RULES -------------------------------------------------------------
#
# Three rules, and tests/test_route_rule_layout.py holds each of them. A section declares one
# requirement. Its routes are listed one per line, sorted by path and then method. No two sections
# declare the same requirement. So a new route has exactly one place to go, and two changes that
# add different routes touch different lines instead of the same end of the same block.

#: Routes that need no credential, each with the reason it needs none.
_PUBLIC_ROUTES: Final[Mapping[str, Public]] = MappingProxyType(
    {
        "GET /docs": Public(_NOT_DATA),
        "GET /docs/oauth2-redirect": Public("part of the documentation page"),
        "GET /healthz": Public(_LIVENESS),
        "GET /openapi.json": Public(_NOT_DATA),
        "GET /readyz": Public(_READINESS),
        "GET /redoc": Public(_NOT_DATA),
    }
)

#: The sign-in surface, each route with what it does with a credential of its own.
_SIGN_IN_ROUTES: Final[Mapping[str, Authentication]] = MappingProxyType(
    {
        "GET /auth/google/callback": Authentication(_SIGN_IN_CALLBACK),
        "GET /auth/google/start": Authentication(_SIGN_IN_START),
        "POST /auth/guest": Authentication(_SIGN_IN_GUEST),
        "POST /auth/logout": Authentication(_SIGN_IN_LOGOUT),
        "GET /auth/session": Authentication(_SIGN_IN_SESSION),
    }
)

#: The recorded library, read.
_LIBRARY_READS: Final = _every(
    _LIBRARY_READ,
    "GET /companion/memory/recent",
    "GET /environment-resources/places/{place_id}",
    "GET /environment-resources/sources/{admission_id}/features",
    "GET /environment-resources/{kind}/{resource_id}",
    "GET /environment-resources/{kind}/{resource_id}/bytes",
    "GET /evidence",
    "GET /evidence/{span_id}",
    "GET /evidence/{span_id}/masked",
    "GET /evidence/{span_id}/region",
    "GET /formation",
    "GET /formation/{batch_id}",
    "GET /geometry",
    "GET /geometry/{artifact_id}",
    "GET /graph",
    "GET /graph/sources",
    "GET /identity/events",
    "GET /scene-geometry/{artifact_id}",
    "GET /scene-segments/{scene_id}",
    "POST /selection",
    "GET /selection/catalogue",
    "POST /selection/packet",
    "GET /selection/place-bridges",
    "GET /world-read/places/{place_id}",
    "GET /world-read/scenes/{scene_id}",
    "GET /world-read/scenes/{scene_id}/observations",
    "GET /world-read/scenes/{scene_id}/observations/resolve",
    "GET /world-read/scenes/{scene_id}/observations/summary",
)

#: Identity decisions, place bridges and companion memory writes.
_LIBRARY_WRITES: Final = _every(
    _LIBRARY_WRITE,
    "POST /companion/memory/answers",
    "POST /companion/memory/answers/{answer_id}/corrections",
    "POST /companion/memory/escapes",
    "POST /identity/confirm",
    "POST /identity/merge",
    "POST /identity/name",
    "POST /identity/reject",
    "POST /identity/rename",
    "POST /identity/split",
    "POST /identity/undo",
    "POST /selection/place-bridges",
)

#: Library reads that may call a model.
_LIBRARY_READS_WITH_A_MODEL: Final = _every(
    _requires(_P.LIBRARY_READ, _P.MODEL_INVOKE),
    "POST /selection/ask",
    "POST /selection/plan",
)

#: World reads that may call a model.
_WORLD_READS_WITH_A_MODEL: Final = _every(
    _requires(_P.WORLD_READ, _P.MODEL_INVOKE),
    "POST /selection/actions",
    "POST /selection/appearance",
    "POST /selection/environment",
    "POST /worlds/specification/drafts",
)

#: World writes that commit the world to a model: a choice of the model that runs a world's
#: people commits the world's host to asking it, and a comparison started from the application,
#: of who decides for a world's people or for a town's signals, commits it to asking the models
#: compared, within the bound its owner stated. Cancelling a comparison takes the same grants as
#: starting one, so nobody else ends an owner's paid run. A reference request commits the workspace
#: to a planning and a reading call and to web searches against its credits; stopping one takes
#: the same grants. A piece request commits the workspace to GPU time against its allowance.
_WORLD_WRITES_WITH_A_MODEL: Final = _every(
    _requires(_P.WORLD_WRITE, _P.MODEL_INVOKE),
    "POST /world/piece-requests",
    "POST /world/versions/{version_id}/models/{role_key}",
    "POST /world/versions/{version_id}/society/comparisons",
    "POST /world/versions/{version_id}/society/comparisons/{comparison_id}/cancel",
    "POST /world/versions/{version_id}/society/models",
    "POST /world/versions/{version_id}/traffic/comparisons",
    "POST /world/versions/{version_id}/traffic/comparisons/{comparison_id}/cancel",
    "POST /worlds/kinds/drafts",
)

#: Asking for reference notes, and stopping a request. A request spends the operator's web source
#: credits and a planning and a reading call, so it needs a permission of its own as well as the
#: model grant; reading a request needs only world.read, and only its requester reads or stops it.
_REFERENCE_REQUESTS: Final = _every(
    _requires(_P.WORLD_WRITE, _P.MODEL_INVOKE, _P.REFERENCES_REQUEST),
    "POST /worlds/references",
    "POST /worlds/references/{reference_id}/cancel",
)

#: The only way new photographs arrive.
_INTAKE: Final = _every(
    _requires(_P.INTAKE_WRITE),
    "POST /intake",
)

#: Deleting a companion memory and revoking a confirmed identity or place decision.
_DELETIONS: Final = _every(
    _requires(_P.DELETION_WRITE),
    "DELETE /companion/memory/answers/{answer_id}",
    "POST /identity/revoke",
    "POST /selection/place-bridges/{decision_id}/revoke",
    "DELETE /world/projects/{project_id}",
    "DELETE /world/projects/{project_id}/items/{item_id}",
)

#: Reading proposed person regions, and where a place's name may go.
_CONSENT_READS: Final = _every(
    _requires(_P.CONSENT_READ),
    "GET /person-regions/{capture_id}",
    "GET /place-name-rights",
    "GET /place-name-rights/{entity_id}",
)

#: Region edits, person subjects, consent transitions, subject links and place name decisions,
#: withdrawals included.
_CONSENT_WRITES: Final = _every(
    _requires(_P.CONSENT_WRITE),
    "POST /identity/subjects/link",
    "POST /identity/subjects/unlink",
    "POST /person-regions/{capture_id}/edits",
    "POST /person-subjects",
    "POST /person-subjects/{subject_id}/consents",
    "POST /place-name-rights/{entity_id}/grants",
    "POST /place-name-rights/{entity_id}/withdrawals",
)

#: Reading personal admission status.
_ADMISSION_READS: Final = _every(
    _requires(_P.ADMISSION_READ),
    "GET /personal-admission",
)

#: Personal, reconstruction and environment source admission, and a workspace's own assets:
#: admitting one, asking for or stopping its preparation, and withdrawing it.
_ADMISSION_WRITES: Final = _every(
    _requires(_P.ADMISSION_WRITE),
    "POST /environment-resources/assets",
    "POST /environment-resources/places",
    "POST /environment-resources/sources",
    "POST /environment-resources/sources/{admission_id}/feature-indexes",
    "POST /operations/reconstruction-admission",
    "POST /personal-admission",
    "POST /personal-admission/model-rights/{right_id}/withdraw",
    "POST /workspace-assets",
    "POST /workspace-assets/{asset_id}/preparation",
    "POST /workspace-assets/{asset_id}/preparation/cancel",
    "POST /workspace-assets/{asset_id}/withdraw",
    "POST /workspace-style-packs",
    "POST /workspace-style-packs/{manifest_sha256}/publish-request",
    "POST /workspace-style-packs/{manifest_sha256}/withdraw",
)

#: Derivative and reconstruction job status, and what the workspace may still spend on hosted
#: models: a monitoring token sees spending without being able to spend.
_OPERATIONS_READS: Final = _every(
    _requires(_P.OPERATIONS_READ),
    "GET /operations/capacity",
    "GET /operations/derivative-jobs",
    "GET /operations/derivative-jobs/{job_id}",
    "GET /operations/derivative-jobs/{job_id}/events",
    "GET /operations/installation",
    "GET /operations/reconstruction-scenes",
    "GET /operations/reconstruction-scenes/{job_id}",
    "GET /spending",
)

#: Retrying a reconstruction job.
_OPERATIONS_WRITES: Final = _every(
    _requires(_P.OPERATIONS_WRITE),
    "POST /operations/reconstruction-scenes/{job_id}/retry",
)

#: The authored world, read. The generation grammar catalog is a read of declared data and
#: materialises nothing, so it is a world read like the style catalog; the material catalog and
#: recipe reads are world reads for the same reason, and so are the committed style pack library
#: and the shipped thing library.
_WORLD_READS: Final = _every(
    _WORLD_READ,
    "GET /door/bridges",
    "GET /door/grants",
    "GET /door/grants/{grant_id}",
    "GET /materials/library",
    "GET /materials/makers",
    "GET /materials/recipes",
    "GET /materials/recipes/{recipe_id}",
    "GET /materials/recipes/{recipe_id}/bake",
    "GET /materials/recipes/{recipe_id}/bake/bytes",
    "POST /selection/actions/outcome",
    "POST /selection/actions/prepare",
    "GET /things/kinds/{kind_sha256}",
    "GET /things/library",
    "GET /things/library/{content_sha256}",
    "GET /things/looks/{look_sha256}",
    "GET /things/looks/{look_sha256}/container",
    "GET /workspace-assets",
    "GET /workspace-assets/{asset_id}",
    "GET /workspace-assets/{asset_id}/prepared/bytes",
    "GET /workspace-style-packs",
    "GET /workspace-style-packs/{manifest_sha256}",
    "GET /workspace-style-packs/{manifest_sha256}/archive",
    "GET /workspace-style-packs/{manifest_sha256}/files/{content_sha256}",
    "GET /world-entries",
    "GET /world-entries/candidates",
    "GET /world-entries/{entry_id}",
    "GET /world-entries/{entry_id}/arrival/scene-geometry/{artifact_id}",
    "GET /world-generation/grammars",
    "GET /world/arrangements",
    "GET /world/assets",
    "GET /world/assets/{asset_key}",
    "GET /world/assets/{asset_key}/bytes",
    "GET /world/assets/{asset_key}/licence",
    "GET /world/behaviours",
    "GET /world/character-catalogs",
    "GET /world/character-catalogs/{catalog_sha256}",
    "GET /world/interactions/catalog",
    "GET /world/interactions/current",
    "GET /world/interactions/proposals/{proposal_id}",
    "GET /world/interactions/recommendations",
    "GET /world/interactions/versions",
    "GET /world/piece-requests",
    "GET /world/piece-requests/{piece_request_id}",
    "GET /world/projects",
    "GET /world/projects/{project_id}",
    "GET /world/projects/{project_id}/audit",
    "GET /world/projects/{project_id}/context",
    "GET /world/projects/{project_id}/items",
    "GET /world/projects/{project_id}/items/{item_id}/history",
    "GET /world/source-media",
    "GET /world/source-media/{source_id}",
    "GET /world/style-packs",
    "GET /world/style-packs/{content_sha256}",
    "GET /world/styles/catalog",
    "GET /world/styles/current",
    "GET /world/styles/previews",
    "GET /world/styles/proposals/{proposal_id}",
    "GET /world/styles/versions",
    "GET /world/versions",
    "GET /world/versions/{version_id}",
    "GET /world/versions/{version_id}/capabilities",
    "GET /world/versions/{version_id}/characters/{subject_kind}/{subject_id}/appearance",
    "GET /world/versions/{version_id}/characters/{subject_kind}/{subject_id}/appearance/families",
    "GET /world/versions/{version_id}/characters/{subject_kind}/{subject_id}/appearance/history",
    "GET /world/versions/{version_id}/characters/{subject_kind}/{subject_id}/appearance"
    "/preparations/{preparation_id}",
    "GET /world/versions/{version_id}/characters/{subject_kind}/{subject_id}/appearance"
    "/preparations/{preparation_id}/bytes",
    "GET /world/versions/{version_id}/clock",
    "GET /world/versions/{version_id}/clock/events",
    "GET /world/versions/{version_id}/clock/verify",
    "GET /world/versions/{version_id}/flight",
    "GET /world/versions/{version_id}/models",
    "GET /world/versions/{version_id}/site",
    "GET /world/versions/{version_id}/society",
    "GET /world/versions/{version_id}/society/actions",
    "GET /world/versions/{version_id}/society/actions/{request_id}",
    "GET /world/versions/{version_id}/society/comparisons",
    "GET /world/versions/{version_id}/society/comparisons/plan",
    "GET /world/versions/{version_id}/society/comparisons/{comparison_id}",
    "GET /world/versions/{version_id}/society/comparisons/{comparison_id}/runs/{run_id}",
    "GET /world/versions/{version_id}/society/comparisons/{comparison_id}/runs/{run_id}/day",
    "GET /world/versions/{version_id}/society/control",
    "GET /world/versions/{version_id}/society/control/events",
    "GET /world/versions/{version_id}/society/decisions/{request_id}",
    "GET /world/versions/{version_id}/society/district",
    "GET /world/versions/{version_id}/society/events",
    "GET /world/versions/{version_id}/society/experiments/{experiment_id}",
    "GET /world/versions/{version_id}/society/experiments/{experiment_id}/attempts/{attempt_id}",
    "GET /world/versions/{version_id}/society/inputs/{input_seq}",
    "GET /world/versions/{version_id}/society/models",
    "GET /world/versions/{version_id}/society/play/{subject_id}/turn",
    "GET /world/versions/{version_id}/society/replay",
    "GET /world/versions/{version_id}/society/things/{thing_id}",
    "GET /world/versions/{version_id}/thing-looks",
    "GET /world/versions/{version_id}/tiles/{baked_tile_id}/bytes",
    "GET /world/versions/{version_id}/traffic",
    "GET /world/versions/{version_id}/traffic/comparisons",
    "GET /world/versions/{version_id}/traffic/comparisons/plan",
    "GET /world/versions/{version_id}/traffic/comparisons/{comparison_id}",
    "GET /world/versions/{version_id}/traffic/comparisons/{comparison_id}/runs/{run_id}",
    "GET /world/versions/{version_id}/traffic/comparisons/{comparison_id}/runs/{run_id}/replay",
    "GET /worlds",
    "GET /worlds/capabilities",
    "GET /worlds/kinds",
    "GET /worlds/kinds/drafts",
    "GET /worlds/kinds/drafts/{draft_id}",
    "GET /worlds/recipes",
    "GET /worlds/references",
    "GET /worlds/references/{reference_id}",
    "GET /worlds/specification",
)

#: Metered against the workspace tile quota, by being declared here: the baked tiles of a generated
#: city, and asking for a generated world, which is the first route whose cost scales with what
#: the caller asked for.
_TILES: Final = _every(
    _requires(_P.TILES_MATERIALISE),
    "GET /tiles",
    "GET /tiles/traffic",
    "GET /tiles/{baked_tile_id}/bytes",
    "POST /world-generation/worlds",
)

#: Every change to the authored world, and recording generated content against a scene. A bake
#: request (POST /materials/recipes/{recipe_id}/bake) is a compute amplifier, bounded per workspace
#: by migration 0066's quota.
_WORLD_WRITES: Final = _every(
    _WORLD_WRITE,
    "POST /materials/recipes",
    "POST /materials/recipes/{recipe_id}/bake",
    "POST /materials/recipes/{recipe_id}/withdraw",
    "POST /world-entries",
    "POST /world-entries/starter",
    "PUT /world-entries/{entry_id}",
    "POST /world-entries/{entry_id}/source-detachments",
    "POST /world-write/scenes/{scene_id}/generated",
    "POST /world/interactions/previews",
    "DELETE /world/interactions/previews/{preview_id}",
    "POST /world/interactions/previews/{preview_id}/apply",
    "POST /world/interactions/rollback",
    "DELETE /world/piece-requests/{piece_request_id}",
    "POST /world/projects",
    "PUT /world/projects/{project_id}",
    "POST /world/projects/{project_id}/items",
    "POST /world/projects/{project_id}/items/{item_id}/corrections",
    "POST /world/projects/{project_id}/items/{item_id}/resolve",
    "POST /world/projects/{project_id}/items/{item_id}/review",
    "POST /world/projects/{project_id}/shares",
    "DELETE /world/projects/{project_id}/shares/{share_id}",
    "POST /world/styles/previews",
    "DELETE /world/styles/previews/{preview_id}",
    "POST /world/styles/previews/{preview_id}/apply",
    "POST /world/styles/rollback",
    "POST /world/versions",
    "POST /world/versions/bootstrap",
    "POST /world/versions/{version_id}/arrangements/apply",
    "POST /world/versions/{version_id}/arrangements/preview",
    "PUT /world/versions/{version_id}/characters/{subject_kind}/{subject_id}/appearance",
    "POST /world/versions/{version_id}/characters/{subject_kind}/{subject_id}/appearance"
    "/preparations",
    "POST /world/versions/{version_id}/characters/{subject_kind}/{subject_id}/appearance"
    "/preparations/{preparation_id}/cancel",
    "POST /world/versions/{version_id}/characters/{subject_kind}/{subject_id}/appearance/reset",
    "PUT /world/versions/{version_id}/clock",
    "POST /world/versions/{version_id}/compositions/apply",
    "POST /world/versions/{version_id}/compositions/preview",
    "POST /world/versions/{version_id}/environment-instances",
    "POST /world/versions/{version_id}/environment-instances/undo",
    "POST /world/versions/{version_id}/environment-instances/{instance_id}/move",
    "POST /world/versions/{version_id}/environment-instances/{instance_id}/remove",
    "POST /world/versions/{version_id}/objects",
    "POST /world/versions/{version_id}/objects/undo",
    "POST /world/versions/{version_id}/objects/undo/preview",
    "POST /world/versions/{version_id}/objects/{object_id}/behaviour",
    "POST /world/versions/{version_id}/objects/{object_id}/move",
    "POST /world/versions/{version_id}/objects/{object_id}/move/preview",
    "POST /world/versions/{version_id}/objects/{object_id}/remove",
    "POST /world/versions/{version_id}/objects/{object_id}/remove/preview",
    "POST /world/versions/{version_id}/society",
    "POST /world/versions/{version_id}/society/actions",
    "PUT /world/versions/{version_id}/society/control",
    "POST /world/versions/{version_id}/society/control/steps",
    "POST /world/versions/{version_id}/society/decisions",
    "POST /world/versions/{version_id}/society/experiments",
    "POST /world/versions/{version_id}/society/experiments/{experiment_id}/attempts",
    "POST /world/versions/{version_id}/society/play",
    "POST /world/versions/{version_id}/society/play/{subject_id}/answer",
    "POST /world/versions/{version_id}/society/play/{subject_id}/give-back",
    "POST /world/versions/{version_id}/society/presence",
    "POST /world/versions/{version_id}/society/steps",
    "POST /world/versions/{version_id}/society/things/{thing_id}/look",
    "POST /world/versions/{version_id}/things",
    "POST /world/versions/{version_id}/things/undo",
    "POST /world/versions/{version_id}/things/{thing_id}/move",
    "POST /world/versions/{version_id}/things/{thing_id}/remove",
    "POST /worlds/generated",
    "POST /worlds/kinds",
    "POST /worlds/kinds/{kind}/worlds",
)

#: World writes that read admission state. Attach and rebind resolve and pin a human review,
#: resolving a depth estimate reads the photograph's admission state: the depth right the account
#: holder granted and the review the estimate was made under, and composing the personal-source
#: world selects the photographs the account holder reviewed. The generic composition routes
#: refuse the photo_point_map kind for every caller. Detach is absent on purpose: it reads no
#: admission receipt and answers with the same entry body PUT /world-entries/{entry_id} already
#: returns to a world.write token, so admission.read would guard nothing there.
_WORLD_WRITES_READING_ADMISSION: Final = _every(
    _requires(_P.WORLD_WRITE, _P.ADMISSION_READ),
    "POST /world-entries/{entry_id}/source-attachments",
    "POST /world-entries/{entry_id}/source-rebinds",
    "POST /world/versions/{version_id}/compositions/photo-point-maps/apply",
    "POST /world/versions/{version_id}/compositions/photo-point-maps/preview",
    "POST /worlds/personal-source",
)

#: A world read that reads admission state: which photographs the account holder reviewed and may
#: compose into their personal-source world, the preview of the write above.
_WORLD_READS_READING_ADMISSION: Final = _every(
    _requires(_P.WORLD_READ, _P.ADMISSION_READ),
    "GET /worlds/personal-source",
)

#: Erasing a creature a workspace drafted from a person's words: a change to its things, so
#: ``world.write``, and the destruction of a person's content, so ``deletion.write`` as every other
#: deletion asks. Both browser roles hold both; a token granted ``world.write`` alone erases
#: nothing.
_WORLD_ERASURES: Final = _every(
    _requires(_P.WORLD_WRITE, _P.DELETION_WRITE),
    "DELETE /things/kinds/{kind_sha256}",
)

#: Issuing, opening and revoking a door grant, and sending its visitors home: a change to who may
#: decide or stand in a world, so ``world.write``, and isolated by name as ``door.grant``.
_DOOR_GRANTS: Final = _every(
    _requires(_P.WORLD_WRITE, _P.DOOR_GRANT),
    "POST /door/grants",
    "POST /door/grants/{grant_id}/channel-credentials",
    "POST /door/grants/{grant_id}/credentials/revoke",
    "POST /door/grants/{grant_id}/invites",
    "POST /door/grants/{grant_id}/revoke",
    "POST /door/grants/{grant_id}/send-away",
)

#: The one route a bridge's own deployment credential reaches.
_BRIDGE_CHANNEL: Final[Mapping[str, Channel]] = MappingProxyType(
    {
        "POST /door/invites/redeem": Channel(
            "bridge", "redeems one invite for the grant it opens, as the bridge it was issued to"
        ),
    }
)

#: The routes a channel credential reaches, each acting only on the one grant it opens.
_GRANT_CHANNEL: Final[Mapping[str, Channel]] = MappingProxyType(
    {
        "POST /door/channel/answers": Channel(
            "grant", "answers an ask of the grant its credential opens"
        ),
        "POST /door/channel/arrivals": Channel(
            "grant", "sends a visitor into the world version of the grant its credential opens"
        ),
        "POST /door/channel/departures/{departure_id}/delivered": Channel(
            "grant", "reports what a departed visitor of the grant its credential opens took home"
        ),
        "GET /door/channel/frames": Channel(
            "grant", "reads what was sent to the grant its credential opens"
        ),
        "POST /door/channel/gone": Channel(
            "grant", "says a visitor of the grant its credential opens has no player behind it"
        ),
        "POST /door/channel/hello": Channel(
            "grant", "presents an adapter and its mapping for the grant its credential opens"
        ),
        "POST /door/channel/home": Channel(
            "grant", "calls a visitor of the grant its credential opens home"
        ),
    }
)

#: Every section, in reading order. A route is declared by appearing in exactly one of them.
ROUTE_RULE_SECTIONS: Final[
    tuple[Mapping[str, Public | Authentication | Requires | Channel], ...]
] = (
    _PUBLIC_ROUTES,
    _SIGN_IN_ROUTES,
    _LIBRARY_READS,
    _LIBRARY_WRITES,
    _LIBRARY_READS_WITH_A_MODEL,
    _WORLD_READS_WITH_A_MODEL,
    _WORLD_WRITES_WITH_A_MODEL,
    _REFERENCE_REQUESTS,
    _INTAKE,
    _DELETIONS,
    _CONSENT_READS,
    _CONSENT_WRITES,
    _ADMISSION_READS,
    _ADMISSION_WRITES,
    _OPERATIONS_READS,
    _OPERATIONS_WRITES,
    _WORLD_READS,
    _TILES,
    _WORLD_WRITES,
    _WORLD_WRITES_READING_ADMISSION,
    _WORLD_READS_READING_ADMISSION,
    _WORLD_ERASURES,
    _DOOR_GRANTS,
    _BRIDGE_CHANNEL,
    _GRANT_CHANNEL,
)


def route_key(route: str) -> tuple[str, str]:
    """``"METHOD /path"`` as the ``(method, path)`` key routable_paths reports, or a refusal."""
    method, _, path = route.partition(" ")
    if method not in _DECLARABLE_METHODS or not path.startswith("/") or " " in path:
        raise RouteDeclarationError(f"{route!r} is not a route written as 'METHOD /path'")
    return method, path


def _declare(
    sections: Iterable[Mapping[str, Public | Authentication | Requires | Channel]],
) -> Mapping[tuple[str, str], Public | Authentication | Requires | Channel]:
    declared: dict[tuple[str, str], Public | Authentication | Requires | Channel] = {}
    for section in sections:
        for route, rule in section.items():
            key = route_key(route)
            if key in declared:
                raise RouteDeclarationError(f"{route} is declared in two sections")
            declared[key] = rule
    return MappingProxyType(declared)


#: The single declaration of what each mounted route requires, assembled from
#: :data:`ROUTE_RULE_SECTIONS` and keyed by ``(method, path)`` exactly as
#: :func:`exulanica.api.routes.routable_paths` reports them.
#:
#: **Every route declared here is probed by the authorisation sweep in tests/test_api.py**, which
#: holds it to refusing an anonymous caller, refusing a bad token and never answering a stranger
#: 403. The probes are derived from this map in tests/route_probes.py, so a new route is swept the
#: moment it is declared; a route whose default request would stop at validation before reaching
#: its own lookup is given a realistic body in that module's PROBE_OVERRIDES.
ROUTE_RULES: Final[Mapping[tuple[str, str], Public | Authentication | Requires | Channel]] = (
    _declare(ROUTE_RULE_SECTIONS)
)


def rule_for(method: str, path: str | None) -> Public | Authentication | Requires | Channel | None:
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
    if rule is None or isinstance(rule, Channel):
        # No account permission reaches a channel route: its credential is the door's own.
        raise PermissionRefused(method=method, path=path, missing=frozenset())
    missing = rule.permissions - held
    if missing:
        raise PermissionRefused(method=method, path=path, missing=frozenset(missing))
    return rule


class CreatorGrantRequired(ExulanicaError):
    """A browser session reached a route that admits a creator's bytes, and its account holds no
    creator grant. The route never ran and read nothing of the body. Always a 403: no such route
    names an id."""

    status = 403
    code = "creator_grant_required"


def require_creator(creator: bool | None, method: str, path: str | None) -> None:
    """Refuse a browser session whose account holds no creator grant on a creator's upload route.

    ``creator`` is the account's grant for a browser session and None for a bearer token, which
    holds what its grant names (:data:`CREATOR_GRANT_ROUTES`).
    """
    if creator is False and (method.upper(), path) in CREATOR_GRANT_ROUTES:
        raise CreatorGrantRequired(
            f"{method.upper()} {path} admits {CREATOR_GRANT_ROUTES[(method.upper(), path)]}, "
            "which a browser session may upload only while its account holds the creator grant; "
            "the operator grants it"
        )


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
    if unheld := sorted(
        key
        for key in CREATOR_GRANT_ROUTES
        if not isinstance(ROUTE_RULES.get(key), Requires) or addressed_by_id(key[1])
    ):
        problems.append(
            "these creator grant routes are not declared routes that require a permission and "
            "name no id: " + ", ".join(f"{method} {path}" for method, path in unheld)
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
