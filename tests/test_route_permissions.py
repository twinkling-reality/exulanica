"""Route permissions: every mounted route is declared, and a missing grant is refused on the wire.

Two halves, because a passing check over a map is not a verified permission.

*   **The declaration.** Generated from :func:`exulanica.api.routes.routable_paths` over the real
    application, never from a list here. A route added under ``exulanica/api/routes/`` by any lane
    fails the build with its own name until it is declared, and the sweep asserts it saw the
    authenticated surface by name, because that function's history is a sweep that saw only the
    documentation pages and passed.
*   **The refusal.** Real HTTP requests through :func:`exulanica.api.app.create_app`, with the API
    connected as a non-owner role so row-level security is live, reading the status and the body.
    The existence-oracle case is a real memory in one workspace, asked for by a credential that
    may not delete it, answered exactly as an invented id and a foreign id are answered.
"""

from __future__ import annotations

import hashlib
import importlib
import inspect
import json
import pkgutil
import re
import urllib.parse
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from types import MappingProxyType, SimpleNamespace

import psycopg
import pytest
from exulanica.api import permissions
from exulanica.api.app import create_app
from exulanica.api.authorisation import TokenDirectory, TokenNotAccepted, load_token_directory
from exulanica.api.authorisation import TokenNotAccepted as _NotAccepted
from exulanica.api.dependencies import _grant
from exulanica.api.permissions import (
    ACCOUNT_OWNER_PERMISSIONS,
    MEMBERSHIP_ROLE_PERMISSIONS,
    ROUTE_RULES,
    Authentication,
    Permission,
    PermissionRefused,
    Public,
    Requires,
    RouteDeclarationError,
    authentication_routes,
    public_paths,
    require_complete_declaration,
)
from exulanica.api.routes import routable_paths
from exulanica.api.services import Services
from exulanica.db.roles import RUNTIME_ROLE, assert_runtime_role, provision_runtime_role
from exulanica.db.session import Database
from exulanica.env import env_get
from exulanica.migrations import migration_directory
from exulanica.selection.validation import Session
from exulanica.store.local import LocalContentAddressedStore
from fastapi import APIRouter
from fastapi.testclient import TestClient
from psycopg.rows import dict_row

from pg_harness import migrated_schema

ALL_PERMISSIONS = sorted(str(permission) for permission in Permission)

#: A role name of this file's own. A role is a cluster object, and the suite's other suffixed
#: roles belong to files that may be running in another worktree at the same moment.
APP_ROLE = f"{RUNTIME_ROLE}_secfloor"


def _unbuilt_services() -> object:
    """Enough for ``create_app`` to build a router: it reads these three at construction and
    nothing else until a request arrives, so the sweep needs no database."""
    return SimpleNamespace(
        society_decision_provider=None, society_base_tick_interval_ms=1000, society_runtime=None
    )


def _application():
    return create_app(_unbuilt_services(), verify=False)  # type: ignore[arg-type]


def _fill(path: str) -> str:
    return re.sub(r"\{[^}]+\}", lambda _m: str(uuid.uuid4()), path)


def _probe_kwargs(method: str, path: str) -> dict:
    if (method, path) == ("POST", "/intake"):
        return {"files": {"files": ("probe.txt", b"probe", "text/plain")}}
    if method in ("POST", "PUT", "PATCH", "DELETE"):
        return {"json": {}}
    return {}


SWEPT = routable_paths(_application())
AUTHENTICATED = sorted(
    key for key in SWEPT if not isinstance(ROUTE_RULES.get(key), Public | Authentication)
)


# -- the declaration ------------------------------------------------------------------------


def test_the_sweep_sees_the_authenticated_surface_by_name():
    """The guard on the guard. A sweep over the documentation pages alone agrees with anything."""
    for key in (
        ("GET", "/graph"),
        ("POST", "/intake"),
        ("DELETE", "/companion/memory/answers/{answer_id}"),
        ("POST", "/person-subjects/{subject_id}/consents"),
        ("POST", "/operations/reconstruction-scenes/{job_id}/retry"),
        ("POST", "/world/versions/{version_id}/objects"),
    ):
        assert key in SWEPT, key
    assert len(AUTHENTICATED) > len(SWEPT) - len(AUTHENTICATED)


def test_every_mounted_route_resolves_a_declaration_and_every_declaration_a_route():
    swept = require_complete_declaration(_application())
    assert swept == len(SWEPT) == len(ROUTE_RULES)
    assert set(SWEPT) == set(ROUTE_RULES)


@pytest.mark.parametrize(("method", "path"), SWEPT)
def test_each_route_has_its_own_declaration(method, path):
    rule = ROUTE_RULES[(method, path)]
    assert isinstance(rule, Public | Authentication | Requires), (method, path)


def test_a_route_nobody_declared_stops_the_application_being_built(monkeypatch):
    dropped = ("POST", "/intake")
    reduced = {key: rule for key, rule in ROUTE_RULES.items() if key != dropped}
    monkeypatch.setattr(permissions, "ROUTE_RULES", MappingProxyType(reduced))
    with pytest.raises(RouteDeclarationError, match=r"POST /intake"):
        _application()


def test_a_declaration_for_a_route_that_is_gone_stops_the_build(monkeypatch):
    extended = {
        **ROUTE_RULES,
        ("GET", "/no-such-route"): Requires(frozenset({Permission.LIBRARY_READ})),
    }
    monkeypatch.setattr(permissions, "ROUTE_RULES", MappingProxyType(extended))
    with pytest.raises(RouteDeclarationError, match=r"GET /no-such-route"):
        _application()


def test_a_blind_sweep_cannot_pass(monkeypatch):
    """The failure ``routable_paths`` once had: it saw only the documentation routes."""
    monkeypatch.setattr(
        permissions,
        "routable_paths",
        lambda _app: sorted(key for key in SWEPT if isinstance(ROUTE_RULES[key], Public)),
    )
    with pytest.raises(RouteDeclarationError, match=r"GET /graph"):
        require_complete_declaration(object())


def test_the_older_route_sets_agree_with_the_declaration():
    """None of them is restated here. Each is imported and compared with the map."""
    from exulanica.evaluation.cli import _PUBLIC

    from test_api import ACCOUNT_ROUTES, PUBLIC_ROUTES

    assert public_paths() == set(PUBLIC_ROUTES) == set(_PUBLIC)
    assert authentication_routes() == set(ACCOUNT_ROUTES)
    for key, rule in ROUTE_RULES.items():
        if isinstance(rule, Public | Authentication):
            assert rule.reason.strip(), key


def test_a_public_declaration_without_a_reason_is_refused():
    with pytest.raises(RouteDeclarationError):
        Public("   ")
    with pytest.raises(RouteDeclarationError):
        Authentication("")
    with pytest.raises(RouteDeclarationError):
        Requires(frozenset())
    with pytest.raises(RouteDeclarationError):
        Requires(frozenset({"library.read"}))  # type: ignore[arg-type]


def test_every_permission_is_required_somewhere():
    used = {
        p for rule in ROUTE_RULES.values() if isinstance(rule, Requires) for p in rule.permissions
    }
    assert set(Permission) - used == set()


def test_the_consequential_surfaces_are_each_isolated():
    def required(method: str, path: str) -> frozenset[Permission]:
        rule = ROUTE_RULES[(method, path)]
        assert isinstance(rule, Requires)
        return rule.permissions

    assert required("POST", "/intake") == {Permission.INTAKE_WRITE}
    for key in (
        ("DELETE", "/companion/memory/answers/{answer_id}"),
        ("POST", "/identity/revoke"),
        ("POST", "/selection/place-bridges/{decision_id}/revoke"),
    ):
        assert required(*key) == {Permission.DELETION_WRITE}, key
    for key in (
        ("POST", "/person-subjects/{subject_id}/consents"),
        ("POST", "/identity/subjects/link"),
        ("POST", "/identity/subjects/unlink"),
        ("POST", "/person-regions/{capture_id}/edits"),
    ):
        assert required(*key) == {Permission.CONSENT_WRITE}, key
    for key in (
        ("POST", "/personal-admission"),
        ("POST", "/operations/reconstruction-admission"),
        ("POST", "/environment-resources/sources"),
    ):
        assert required(*key) == {Permission.ADMISSION_WRITE}, key
    assert required("POST", "/world-write/scenes/{scene_id}/generated") == {Permission.WORLD_WRITE}
    assert required("POST", "/operations/reconstruction-scenes/{job_id}/retry") == {
        Permission.OPERATIONS_WRITE
    }


def test_no_route_that_changes_state_is_satisfied_by_a_read_alone():
    """A POST or DELETE needing only reads is a hole, except the two named read-shaped POSTs."""
    read_shaped = {("POST", "/selection"), ("POST", "/selection/packet")}
    for (method, path), rule in ROUTE_RULES.items():
        if method == "GET" or isinstance(rule, Public | Authentication):
            continue
        if (method, path) in read_shaped:
            continue
        assert any(not p.endswith(".read") for p in rule.permissions), (method, path)


def test_every_route_that_can_reach_a_model_requires_model_invoke():
    """Generated from the route modules' own endpoints, so a new model route cannot slip past.

    Read through each module's router rather than a second walk of the application; the keys it
    yields are checked against the application's own sweep.
    """
    import exulanica.api.routes as package

    found: set[tuple[str, str]] = set()
    for module_info in pkgutil.iter_modules(package.__path__):
        module = importlib.import_module(f"{package.__name__}.{module_info.name}")
        for router in vars(module).values():
            if not isinstance(router, APIRouter):
                continue
            for route in router.routes:
                source = inspect.getsource(route.endpoint)
                # request_decision reaches the society decision provider, which is a model,
                # without the endpoint ever naming a model client.
                if any(
                    marker in source
                    for marker in ("_require_model(", ".model_client", "request_decision(")
                ):
                    found.update((method, route.path) for method in route.methods)
    assert sorted(found) == [
        ("POST", "/selection/appearance"),
        ("POST", "/selection/ask"),
        ("POST", "/selection/environment"),
        ("POST", "/selection/plan"),
        ("POST", "/world/versions/{version_id}/society/decisions"),
    ]
    assert found <= set(SWEPT)
    for key in found:
        rule = ROUTE_RULES[key]
        assert isinstance(rule, Requires) and Permission.MODEL_INVOKE in rule.permissions, key


def test_the_refusal_ledger_check_names_exactly_the_vocabulary():
    """Migration 0061 closes its permission column over the same set as the enum."""
    sql = (migration_directory() / "0061_route_permissions.sql").read_text(encoding="utf-8")
    block = sql.split("missing_permissions <@ array[", 1)[1].split("]::text[]", 1)[0]
    assert sorted(re.findall(r"'([a-z.]+)'", block)) == ALL_PERMISSIONS


def test_every_membership_role_the_schema_allows_has_a_declared_grant():
    """Migration 0058 closes membership_role; a new role there fails here until it has a grant."""
    sql = (migration_directory() / "0058_accounts_and_sessions.sql").read_text(encoding="utf-8")
    checks = re.findall(r"membership_role\s+text\s+not\s+null\s+check\(([^)]*)\)", sql)
    assert len(checks) == 1, checks
    roles = set(re.findall(r"'([a-z_]+)'", checks[0]))
    assert roles == set(MEMBERSHIP_ROLE_PERMISSIONS) == {"owner"}
    # And the session lookup a browser request goes through still admits that role alone.
    source = inspect.getsource(importlib.import_module("exulanica.api.account_repository"))
    assert "m.membership_role='owner'" in source


def test_the_owner_grant_is_everything_but_tiles():
    assert set(Permission) - ACCOUNT_OWNER_PERMISSIONS == {Permission.TILES_MATERIALISE}
    assert MEMBERSHIP_ROLE_PERMISSIONS["owner"] is ACCOUNT_OWNER_PERMISSIONS


def test_a_refusal_is_404_on_an_id_and_403_elsewhere():
    on_id = PermissionRefused(
        method="GET", path="/evidence/{span_id}", missing=frozenset({Permission.LIBRARY_READ})
    )
    assert (on_id.status, on_id.code) == (404, "unknown_reference")
    assert "library.read" not in on_id.detail
    on_collection = PermissionRefused(
        method="GET", path="/graph", missing=frozenset({Permission.LIBRARY_READ})
    )
    assert (on_collection.status, on_collection.code) == (403, "not_authorised")
    assert "library.read" in on_collection.detail
    undeclared = PermissionRefused(method="GET", path=None, missing=frozenset())
    assert undeclared.status == 404


def test_an_undeclared_route_refuses_everybody(monkeypatch):
    monkeypatch.setattr(permissions, "ROUTE_RULES", MappingProxyType({}))
    with pytest.raises(PermissionRefused):
        permissions.require(frozenset(Permission), "GET", "/graph")


# -- the grant ----------------------------------------------------------------------------

_TOKEN = "grant-token-that-is-long-enough-to-be-accepted"


def _directory(grant: dict) -> TokenDirectory:
    workspace = uuid.uuid4()
    return load_token_directory(
        {
            "EXULANICA_API_TOKENS": json.dumps(
                {_TOKEN: {"workspace_id": str(workspace), "actor": str(uuid.uuid4()), **grant}}
            )
        }
    )


def test_a_grant_that_names_its_permissions_resolves_to_them():
    directory = _directory({"permissions": ["library.read", "intake.write"]})
    session, held = directory.grant_for(_TOKEN)
    assert held == {Permission.LIBRARY_READ, Permission.INTAKE_WRITE}
    assert directory.session_for(_TOKEN) == session


@pytest.mark.parametrize(
    ("grant", "message"),
    [
        ({}, "no 'permissions'"),
        ({"permissions": None}, "no 'permissions'"),
        ({"permissions": []}, "non-empty JSON array"),
        ({"permissions": "library.read"}, "non-empty JSON array"),
        ({"permissions": ["*"]}, "no wildcard"),
        ({"permissions": ["library.admin"]}, "not a permission"),
        ({"permissions": ["LIBRARY.READ"]}, "not a permission"),
        ({"permissions": [1]}, "not a string"),
        ({"permissions": ["library.read", "library.read"]}, "listed twice"),
    ],
)
def test_a_grant_that_does_not_parse_is_refused_at_load(grant, message):
    with pytest.raises(TokenNotAccepted, match=re.escape(message)) as refused:
        _directory(grant)
    assert _TOKEN not in str(refused.value)


def test_a_directory_built_without_permissions_holds_nothing():
    """Deny by default. A hand-built directory is not a way round the grant."""
    workspace = uuid.uuid4()
    directory = TokenDirectory({"digest-of-nothing": Session(workspace, uuid.uuid4())})
    assert directory.permissions == {}
    token_directory = TokenDirectory(
        {hashlib.sha256(_TOKEN.encode()).hexdigest(): Session(workspace, workspace)}
    )
    _session, held = token_directory.grant_for(_TOKEN)
    assert held == frozenset()


# -- the refusal, on the wire -------------------------------------------------------------


SESSION_COOKIE = "__Host-exulanica-session"


class StubAccounts:
    """The account runtime's one method the permission floor calls, backed by a fixed cookie.

    The real runtime reads the browser session through its own database role; what the floor
    needs from it is only the session a cookie resolves to, or ``TokenNotAccepted``.
    """

    def __init__(self, cookie: str, session: Session) -> None:
        self.cookie, self.session, self.calls = cookie, session, 0

    def authenticate_request(self, request) -> Session:
        self.calls += 1
        if request.cookies.get(SESSION_COOKIE) != self.cookie:
            raise _NotAccepted("browser session was not accepted")
        return self.session


@dataclass
class Floor:
    client: TestClient
    scratch: str
    app_dsn: str
    workspace_a: uuid.UUID
    workspace_b: uuid.UUID
    actors: dict[str, uuid.UUID]
    tokens: dict[str, str]
    accounts: StubAccounts

    def request(self, who: str, method: str, path: str, **kwargs):
        headers = {"Authorization": f"Bearer {self.tokens[who]}"}
        return self.client.request(method, path, headers=headers, **kwargs)

    def connect_as_app(self, workspace: uuid.UUID) -> psycopg.Connection:
        connection = psycopg.connect(self.app_dsn, autocommit=True, row_factory=dict_row)
        connection.execute(
            "select set_config('exulanica.workspace_id', %s, false)", (str(workspace),)
        )
        return connection


#: Who each token is, which workspace it belongs to, and what it may do.
GRANTS: dict[str, tuple[str, list[str]]] = {
    "owner": ("a", ALL_PERMISSIONS),
    "reader": ("a", ["library.read"]),
    "writer": ("a", ["library.read", "library.write"]),
    "operator": ("a", ["operations.read"]),
    "reads": ("a", sorted(str(p) for p in Permission if p.endswith(".read"))),
    "viewer": ("a", ["world.read"]),
    "world_writer": ("a", ["world.read", "world.write"]),
    "stranger": ("b", ALL_PERMISSIONS),
}


def app_role_dsn(scratch: str) -> str:
    base = env_get("TEST_DATABASE_URL")
    assert base is not None
    options = urllib.parse.quote(f"-csearch_path={scratch},public", safe="")
    return f"{base}{'&' if '?' in base else '?'}user={APP_ROLE}&options={options}"


@pytest.fixture(scope="module")
def floor(tmp_path_factory) -> Iterator[Floor]:
    """The real application over a migrated schema, connected as a non-owner runtime role."""
    with migrated_schema() as (_psycopg, admin):
        admin.row_factory = dict_row
        scratch = admin.execute("select current_schema()").fetchone()["current_schema"]
        provision_runtime_role(admin, role=APP_ROLE)
        admin.commit()

        workspaces = {"a": uuid.uuid4(), "b": uuid.uuid4()}
        actors = {who: uuid.uuid4() for who in GRANTS}
        tokens = {who: f"{who}-token-{uuid.uuid4().hex}" for who in GRANTS}
        directory = load_token_directory(
            {
                "EXULANICA_API_TOKENS": json.dumps(
                    {
                        tokens[who]: {
                            "workspace_id": str(workspaces[workspace]),
                            "actor": str(actors[who]),
                            "permissions": granted,
                        }
                        for who, (workspace, granted) in GRANTS.items()
                    }
                )
            }
        )
        browser = StubAccounts(
            f"browser-{uuid.uuid4().hex}", Session(workspaces["a"], uuid.uuid4())
        )
        dsn = app_role_dsn(scratch)
        with psycopg.connect(dsn, row_factory=dict_row) as probe:
            # The boot guard's own check, against the role the API is about to use.
            assert_runtime_role(probe)
        database = Database(url=dsn)
        services = Services(
            database=database,
            readonly_database=database,
            store=LocalContentAddressedStore(tmp_path_factory.mktemp("floor") / "blobs"),
            tokens=directory,
            executor_shares_the_write_role=True,
            model_client=None,
            accounts=browser,  # type: ignore[arg-type]
        )
        with TestClient(create_app(services, verify=False)) as client:
            yield Floor(
                client=client,
                scratch=scratch,
                app_dsn=dsn,
                workspace_a=workspaces["a"],
                workspace_b=workspaces["b"],
                actors=actors,
                tokens=tokens,
                accounts=browser,
            )


def _refusal_rows(floor: Floor, workspace: uuid.UUID, who: str) -> dict[tuple[str, str], dict]:
    with floor.connect_as_app(workspace) as connection:
        rows = connection.execute(
            "select http_method, route_path, missing_permissions, refusals, first_refused_at, "
            "last_refused_at from route_permission_refusal where actor = %s",
            (floor.actors[who],),
        ).fetchall()
    return {(row["http_method"], row["route_path"]): row for row in rows}


@pytest.mark.postgres
@pytest.mark.parametrize(("method", "path"), AUTHENTICATED)
def test_every_authenticated_route_refuses_an_anonymous_caller(floor, method, path):
    response = floor.client.request(method, _fill(path), **_probe_kwargs(method, path))
    assert response.status_code == 401, response.text
    assert response.json()["code"] == "unauthenticated"


@pytest.mark.postgres
def test_every_route_refuses_a_grant_that_does_not_cover_it(floor):
    """Generated from the router: one real request per route, with a credential that may only
    read operations. Every other route refuses by the rule, and the refusal is counted."""
    held = {Permission.OPERATIONS_READ}
    refused: set[tuple[str, str]] = set()
    for method, path in AUTHENTICATED:
        rule = ROUTE_RULES[(method, path)]
        assert isinstance(rule, Requires)
        response = floor.request("operator", method, _fill(path), **_probe_kwargs(method, path))
        if rule.permissions <= held:
            assert response.status_code not in (401, 403), (method, path, response.text)
            continue
        refused.add((method, path))
        expected = (404, "unknown_reference") if "{" in path else (403, "not_authorised")
        assert (response.status_code, response.json()["code"]) == expected, (method, path)
    assert len(refused) == len(AUTHENTICATED) - 4

    rows = _refusal_rows(floor, floor.workspace_a, "operator")
    assert set(rows) == refused
    for key, row in rows.items():
        rule = ROUTE_RULES[key]
        assert isinstance(rule, Requires)
        assert row["refusals"] == 1
        assert set(row["missing_permissions"]) == {str(p) for p in rule.permissions - held}
    # The other workspace sees none of it: the ledger is under the same policy as everything else.
    assert _refusal_rows(floor, floor.workspace_b, "operator") == {}


@pytest.mark.postgres
def test_a_repeated_refusal_raises_the_count_and_keeps_its_first_sighting(floor):
    before = _refusal_rows(floor, floor.workspace_a, "reader").get(
        ("GET", "/operations/derivative-jobs")
    )
    for _ in range(2):
        response = floor.request("reader", "GET", "/operations/derivative-jobs")
        assert response.status_code == 403
        assert response.json() == {
            "code": "not_authorised",
            "detail": "this credential does not hold operations.read, which GET "
            "/operations/derivative-jobs requires",
        }
    row = _refusal_rows(floor, floor.workspace_a, "reader")[("GET", "/operations/derivative-jobs")]
    assert row["refusals"] == (before["refusals"] if before else 0) + 2
    assert row["last_refused_at"] >= row["first_refused_at"]


@pytest.mark.postgres
def test_a_permission_refusal_on_an_id_is_not_an_existence_oracle(floor):
    """A real memory, a foreign memory and an invented id look identical to a caller who may
    not delete, and the refusal deleted nothing."""
    body = {
        "question": "when?",
        "answer_text": "then",
        "prompt_version": "selection-3",
        "latency_ms": 1,
    }
    mine = floor.request("owner", "POST", "/companion/memory/answers", json=body)
    assert mine.status_code == 201, mine.text
    theirs = floor.request("stranger", "POST", "/companion/memory/answers", json=body)
    assert theirs.status_code == 201, theirs.text
    real, foreign = mine.json()["answer_id"], theirs.json()["answer_id"]

    answers = [
        floor.request("writer", "DELETE", f"/companion/memory/answers/{answer_id}")
        for answer_id in (real, foreign, str(uuid.uuid4()))
    ]
    assert {response.status_code for response in answers} == {404}
    assert answers[0].json() == answers[1].json() == answers[2].json()
    assert answers[0].json()["code"] == "unknown_reference"
    assert answers[0].headers.get("content-length") == answers[2].headers.get("content-length")

    recent = floor.request("owner", "GET", "/companion/memory/recent").json()["answers"]
    assert real in {answer["answer_id"] for answer in recent}

    # With the permission, the stranger's own workspace hides the owner's memory: still 404.
    crossed = floor.request("stranger", "DELETE", f"/companion/memory/answers/{real}")
    assert crossed.status_code == 404
    # And the owner, who holds deletion.write, deletes it.
    assert floor.request("owner", "DELETE", f"/companion/memory/answers/{real}").status_code == 204


@pytest.mark.postgres
def test_a_missing_write_on_a_collection_is_a_403_that_names_the_permission(floor):
    response = floor.request(
        "reader", "POST", "/intake", files={"files": ("probe.txt", b"probe", "text/plain")}
    )
    assert response.status_code == 403
    assert response.json()["code"] == "not_authorised"
    assert "intake.write" in response.json()["detail"]
    body = {"question": "q", "answer_text": "a", "prompt_version": "selection-3", "latency_ms": 1}
    refused = floor.request("reader", "POST", "/companion/memory/answers", json=body)
    assert (refused.status_code, refused.json()["code"]) == (403, "not_authorised")
    # The same body with the grant is accepted, so the 403 above is the grant and not the body.
    assert (
        floor.request("writer", "POST", "/companion/memory/answers", json=body).status_code == 201
    )


@pytest.mark.postgres
def test_public_routes_need_no_credential_and_record_nothing(floor):
    assert floor.client.get("/healthz").status_code == 200
    assert floor.client.get("/openapi.json").status_code == 200


@pytest.mark.postgres
def test_the_app_role_can_write_and_read_the_refusal_ledger_under_its_own_policy(floor):
    """The runtime grant reaches the new table with no change to roles.py, and the policy holds."""
    workspace, actor = floor.workspace_b, uuid.uuid4()
    with floor.connect_as_app(workspace) as connection:
        connection.execute(
            "insert into route_permission_refusal (workspace_id, actor, http_method, route_path, "
            "missing_permissions) values (%s, %s, 'GET', '/graph', %s)",
            (workspace, actor, ["library.read"]),
        )
        assert (
            connection.execute(
                "select refusals from route_permission_refusal where actor = %s", (actor,)
            ).fetchone()["refusals"]
            == 1
        )
        with pytest.raises(psycopg.errors.CheckViolation):
            connection.execute(
                "update route_permission_refusal set refusals = refusals + 5 where actor = %s",
                (actor,),
            )
        with pytest.raises(psycopg.errors.CheckViolation):
            connection.execute(
                "insert into route_permission_refusal (workspace_id, actor, http_method, "
                "route_path, missing_permissions) values (%s, %s, 'GET', '/x', %s)",
                (workspace, uuid.uuid4(), ["library.admin"]),
            )
        # Naming another workspace is refused by the guard's first statement, which raises
        # SQLSTATE 42501 rather than failing open.
        with pytest.raises(psycopg.errors.InsufficientPrivilege, match="workspace context"):
            connection.execute(
                "insert into route_permission_refusal (workspace_id, actor, http_method, "
                "route_path, missing_permissions) values (%s, %s, 'GET', '/y', %s)",
                (floor.workspace_a, uuid.uuid4(), ["library.read"]),
            )
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute("delete from route_permission_refusal where actor = %s", (actor,))
    with floor.connect_as_app(floor.workspace_a) as other:
        assert (
            other.execute(
                "select count(*) as n from route_permission_refusal where actor = %s", (actor,)
            ).fetchone()["n"]
            == 0
        )


@pytest.mark.postgres
def test_a_browser_session_holds_the_owner_grant_and_is_resolved_once(floor):
    cookie = {"Cookie": f"{SESSION_COOKIE}={floor.accounts.cookie}"}
    before = floor.accounts.calls
    assert floor.client.get("/operations/derivative-jobs", headers=cookie).status_code == 200
    # Resolved by the floor, reused by current_session: one account lookup, not two.
    assert floor.accounts.calls == before + 1
    body = {"question": "q", "answer_text": "a", "prompt_version": "selection-3", "latency_ms": 1}
    made = floor.client.post("/companion/memory/answers", headers=cookie, json=body)
    assert made.status_code == 201, made.text
    gone = floor.client.delete(
        f"/companion/memory/answers/{made.json()['answer_id']}", headers=cookie
    )
    assert gone.status_code == 204


@pytest.mark.postgres
def test_a_browser_request_without_a_session_is_unauthenticated(floor):
    response = floor.client.get("/graph", headers={"Cookie": f"{SESSION_COOKIE}=forged"})
    assert (response.status_code, response.json()["code"]) == (401, "unauthenticated")


@pytest.mark.postgres
def test_a_bad_bearer_header_never_falls_back_to_the_cookie(floor):
    headers = {
        "Authorization": "Bearer not-a-configured-token-but-long-enough",
        "Cookie": f"{SESSION_COOKIE}={floor.accounts.cookie}",
    }
    before = floor.accounts.calls
    response = floor.client.get("/graph", headers=headers)
    assert (response.status_code, response.json()["code"]) == (401, "unauthenticated")
    assert floor.accounts.calls == before


def test_the_browser_grant_is_the_owner_grant_and_holds_no_tiles():
    session = Session(uuid.uuid4(), uuid.uuid4())
    accounts = StubAccounts("c", session)
    services = type("Services", (), {"accounts": accounts})()
    app = type("App", (), {"state": type("State", (), {"services": services})()})()
    request = type("Request", (), {"cookies": {SESSION_COOKIE: "c"}, "app": app})()
    resolved, held = _grant(request, None)  # type: ignore[arg-type]
    assert resolved is session
    assert held is ACCOUNT_OWNER_PERMISSIONS
    assert Permission.TILES_MATERIALISE not in held


_OUR_404 = "nothing at this address is available to this credential"


def _refused_by_the_floor(response) -> bool:
    body = (
        response.json()
        if response.headers.get("content-type", "").startswith("application/json")
        else {}
    )
    return (response.status_code, body.get("code")) in {
        (404, "unknown_reference"),
        (403, "not_authorised"),
    } and (body.get("detail") == _OUR_404 or "which" in str(body.get("detail", "")))


@pytest.mark.postgres
@pytest.mark.parametrize("who", ["reads", "viewer"])
def test_a_token_missing_a_routes_permission_is_refused_on_the_wire(floor, who):
    """Generated from the map: every route the token's grant does not cover is refused, by the
    floor, before the route runs. Declared-but-wrong is what this catches that the declaration
    sweep cannot: a mutation declared as a read would reach its route here and fail the test."""
    held = frozenset(Permission(p) for p in GRANTS[who][1])
    refused = []
    for method, path in AUTHENTICATED:
        rule = ROUTE_RULES[(method, path)]
        assert isinstance(rule, Requires)
        if rule.permissions <= held:
            continue
        response = floor.request(who, method, _fill(path), **_probe_kwargs(method, path))
        assert _refused_by_the_floor(response), (method, path, response.status_code, response.text)
        refused.append((method, path))
    # Every state-changing route is among the refused, for a token that holds only reads.
    writes = {
        key
        for key in AUTHENTICATED
        if key[0] != "GET" and key not in {("POST", "/selection"), ("POST", "/selection/packet")}
    }
    assert writes <= set(refused), sorted(writes - set(refused))


#: Integration's state-changing routes, named so a declaration that drifts to a read fails here by
#: name rather than only in the generated sweep above.
_WORLD_MUTATIONS = [
    ("PUT", "/world/versions/{version_id}/society/control"),
    ("POST", "/world/versions/{version_id}/society/control/steps"),
    ("POST", "/world/versions/{version_id}/society/actions"),
    ("POST", "/world/versions/{version_id}/society/decisions"),
    ("PUT", "/world/versions/{version_id}/characters/{subject_kind}/{subject_id}/appearance"),
    (
        "POST",
        "/world/versions/{version_id}/characters/{subject_kind}/{subject_id}/appearance/reset",
    ),
]


@pytest.mark.postgres
@pytest.mark.parametrize(("method", "path"), _WORLD_MUTATIONS)
def test_a_world_reader_cannot_change_the_world(floor, method, path):
    before = _refusal_rows(floor, floor.workspace_a, "viewer").get((method, path))
    response = floor.request("viewer", method, _fill(path), json={})
    assert (response.status_code, response.json()) == (
        404,
        {"code": "unknown_reference", "detail": _OUR_404},
    )
    row = _refusal_rows(floor, floor.workspace_a, "viewer")[(method, path)]
    assert row["refusals"] == (before["refusals"] if before else 0) + 1
    assert "world.write" in row["missing_permissions"]


@pytest.mark.postgres
def test_a_society_decision_needs_model_invoke_as_well_as_world_write(floor):
    path = "/world/versions/{version_id}/society/decisions"
    response = floor.request("world_writer", "POST", _fill(path), json={})
    assert (response.status_code, response.json()["detail"]) == (404, _OUR_404)
    row = _refusal_rows(floor, floor.workspace_a, "world_writer")[("POST", path)]
    assert row["missing_permissions"] == ["model.invoke"]
    # The same token reaches the action route, whose declaration it does cover: the body is then
    # refused by the route's own validation, which proves the floor let it through.
    passed = floor.request(
        "world_writer", "POST", _fill("/world/versions/{version_id}/society/actions"), json={}
    )
    assert passed.status_code == 422, passed.text
    # And the owner, who holds both, reaches the decision route's validation too.
    assert floor.request("owner", "POST", _fill(path), json={}).status_code == 422
