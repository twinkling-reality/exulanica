"""A stranger learns nothing from an id about whether it exists in somebody else's account.

``evaluation-methodology.md`` M10 asks for more than "never 403": "Nonexistent and foreign IDs
return the identical code." ``tests/test_api.py`` holds every authenticated route to the first
half. This file holds every route whose path takes an id to the second, and to all of it: the
status, the problem code and the whole body, once each id the caller supplied is put back as its
placeholder, so a body that echoes the id it was asked about still compares equal and a body that
says anything else about it does not.

How the question is asked, and why each part is there:

*   **The routes are ROUTE_RULES' own.** :func:`route_probes.id_routes` is every declared route
    that needs a credential and takes an id in its path. Nothing here lists a route.
*   **The ids are real.** For every id a route takes, :data:`route_probes.EXISTENCE_BUILDERS`
    makes an object of that kind in the OWNER'S workspace, keyed by the id's address, and a kind
    nobody can build fails by name rather than being skipped. A nested id's builder also names
    the object it lives in, and the sweep resolves the innermost first, so the version it asks
    about is the one that holds the experiment it asks about.
*   **Every combination.** A stranger holding every permission for a workspace of its own sends
    the route's probe with each id foreign or invented, in every combination, because identity is
    a tuple: a route that looked up the version and not the object would tell a real version with
    an invented object from an invented version.
*   **The owner proves the ids are real.** The owner sends the same request and must be answered
    differently. Without that, a route that refused everybody for another reason (a validator, a
    service this application was built without, a check on the body before the id) would pass
    while saying nothing about existence.
*   **Row-level security applies.** The application connects as a provisioned runtime role that
    is neither a superuser nor exempt from row-level security, as a deployment does, so a route
    whose isolation rests on the policy rather than its own predicate is asked the question the
    deployment would be asked.

A kind every workspace reads alike, such as a reviewed asset, is declared :class:`route_probes.
Shared` with its reason, and held to it: the stranger must get exactly the owner's answer.

The same question is asked of an id a caller CHOOSES in a create request's body
(:data:`route_probes.CHOSEN_IDS`). A stranger naming the id the owner chose must be answered as a
fresh id is, in status, problem code and body shape (a creation's own new ids differ between two
creations, so values are not compared). A fresh id must be accepted, so the comparison is between
two creations rather than two refusals, and the owner naming its own id again must be refused by
name, which shows the id the stranger was given is a real one.
"""

from __future__ import annotations

import contextlib
import copy
import itertools
import json
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType

import pytest
from exulanica.api import permissions
from exulanica.api.app import create_app
from exulanica.api.authorisation import load_token_directory
from exulanica.api.dependencies import CurrentSession
from exulanica.api.permissions import Permission, Requires, route_key
from exulanica.api.routes.character_appearance import CharacterAppearanceRuntime
from exulanica.api.services import Services
from exulanica.db.roles import provision_runtime_role
from exulanica.store.local import LocalContentAddressedStore
from exulanica.store.namespaces import LocalWorkspaceStores, tile_store
from exulanica.world import TopologyContract, WorldStyleRepository
from exulanica.world.material_recipes import MaterialRuntime
from exulanica.world.society import UnavailableSocietyInput
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from character_appearance_fixtures import family
from conftest import scratch_role_database
from route_probes import (
    BUILDER_OVERRIDES,
    CHOSEN_IDS,
    EXISTENCE_BUILDERS,
    EXISTENCE_REQUESTS,
    ROUTE_PROBES,
    Chosen,
    IdAddress,
    Owned,
    Shared,
    fill,
    id_addresses,
    id_routes,
)
from test_material_recipes import CATALOG
from tests_support_api import EVERY_PERMISSION, scratch_database
from world_support import registered_world

_OWNER_TOKEN = "existence-owner-token-long-enough-to-be-accepted"
_STRANGER_TOKEN = "existence-stranger-token-long-enough-to-be-accepted"
#: The roles the application connects as: the runtime role that writes, and the one that reads.
_RUNTIME_ROLE = "exulanica_existence_suite"
_READER_ROLE = "exulanica_existence_reader"
#: How much of an answer's body a finding quotes.
_QUOTED = 240


@dataclass(frozen=True)
class Answer:
    """What one request was answered, with each id the caller supplied put back as its name."""

    status: int
    media_type: str
    body: str

    @classmethod
    def of(cls, response, supplied: Mapping[str, object]) -> Answer:
        media_type = response.headers.get("content-type", "").split(";")[0].strip()
        text = response.content.decode("utf-8", errors="replace")
        for placeholder, value in supplied.items():
            text = text.replace(str(value), "{" + placeholder + "}")
        if media_type == "application/json":
            with contextlib.suppress(ValueError):
                text = json.dumps(json.loads(text), sort_keys=True)
        return cls(response.status_code, media_type, text)

    @property
    def code(self) -> str | None:
        """The problem code of a JSON refusal, or None."""
        if self.media_type != "application/json":
            return None
        document = json.loads(self.body)
        return document.get("code") if isinstance(document, dict) else None

    @property
    def shape(self) -> object:
        """The body's structure, every value replaced by the name of its type."""

        def outline(value: object) -> object:
            if isinstance(value, dict):
                return {key: outline(item) for key, item in sorted(value.items())}
            if isinstance(value, list):
                return [outline(item) for item in value]
            return type(value).__name__

        if self.media_type != "application/json":
            return self.media_type
        return outline(json.loads(self.body))

    @property
    def stopped_at_validation(self) -> bool:
        """FastAPI's request validation answered, so the route's own lookup never ran."""
        if self.status != 422 or self.media_type != "application/json":
            return False
        return isinstance(json.loads(self.body).get("detail"), list)

    def __str__(self) -> str:
        body = self.body if len(self.body) <= _QUOTED else self.body[:_QUOTED] + "..."
        return f"{self.status} {body}"


@dataclass(frozen=True)
class Caller:
    """Somebody who sends requests, as a request builder sees them: a way to send one."""

    request: Callable[..., object]


class Existence:
    """The owner's workspace, which holds one real object of every kind a route asks about.

    Builders in ``tests/existence_builders.py`` reach it through the attributes their module
    docstring names. :meth:`real` makes each kind once per test and remembers every id a builder
    names, so a nested object and the object it lives in are asked about together.
    """

    def __init__(self, *, client, app, repository, store, tiles, actor, photo_dir, tmp_path):
        self.client = client
        self.app = app
        self.repository = repository
        self.workspace_id = repository.workspace_id
        self.store = store
        self.tiles = tiles
        self.actor = actor
        self.photo_dir = photo_dir
        self.tmp_path = tmp_path
        self.memo: dict[str, object] = {}
        self.society_inputs: dict[uuid.UUID, dict] = {}
        self._made: dict[str, str] = {}

    def request(self, method: str, path: str, **kwargs):
        """One request with the owner's token."""
        return self._send(_OWNER_TOKEN, method, path, **kwargs)

    def as_stranger(self, method: str, path: str, **kwargs):
        return self._send(_STRANGER_TOKEN, method, path, **kwargs)

    @property
    def stranger(self) -> Caller:
        """The stranger as a caller a request builder can read its own state through."""
        return Caller(self.as_stranger)

    def _send(self, token: str, method: str, path: str, **kwargs):
        headers = {"Authorization": f"Bearer {token}", **kwargs.pop("headers", {})}
        return self.client.request(method, path, headers=headers, **kwargs)

    def real(self, address: str, kind: Owned | Shared | None = None) -> str:
        """The id of this test's object at ``address``, made the first time it is asked for.

        ``kind`` is the builder a route asks for there, when it asks for a narrower kind than the
        address names (:data:`route_probes.BUILDER_OVERRIDES`); a builder that makes an object
        inside another asks for the other by its address alone.
        """
        if address not in self._made:
            kind = kind or EXISTENCE_BUILDERS.get(address)
            if kind is None:
                raise LookupError(f"no builder in EXISTENCE_BUILDERS makes an id at {address}")
            made = kind.build(self)
            named = made if isinstance(made, Mapping) else {address: made}
            assert address in named, f"the builder for {address} did not name its own id"
            for where, value in named.items():
                already = self._made.setdefault(where, str(value))
                assert already == str(value), f"{where} was made twice, as {already} and {value}"
        return self._made[address]


def _provide_society_input(existence: Existence):
    """The application's society input adapter, answering only for the owner's versions.

    A deployment's adapter reads the world the caller's workspace holds; this one hands back the
    document a builder registered for a version, and refuses any other caller as the deployment's
    refuses a version the caller's workspace does not hold.
    """

    def provide(connection, session, version_id, place_id, region_id):
        document = existence.society_inputs.get(version_id)
        if session.workspace_id != existence.workspace_id or document is None:
            raise UnavailableSocietyInput("this workspace holds no authored version by that id")
        return document

    return provide


@pytest.fixture
def existence(tmp_path, photo_dir, repository, spine_schema):
    """An application over the test schema, connected as runtime roles, with two tokens.

    The stranger's workspace owns nothing but a world of its own, registered under the id the
    owner's world has and holding a topology, because world routes decide the caller's world before
    they look at an id, and a stranger with no such world would be refused there by every id alike
    without the id being looked up.
    """
    _psycopg, scratch = spine_schema
    provision_runtime_role(repository.connection, role=_RUNTIME_ROLE)
    provision_runtime_role(repository.connection, role=_READER_ROLE, read_only=True)
    database = scratch_role_database(scratch, _RUNTIME_ROLE)
    with database.session(repository.workspace_id) as connection:
        role = connection.execute(
            "select rolsuper, rolbypassrls from pg_roles where rolname = current_user"
        ).fetchone()
        assert role == {"rolsuper": False, "rolbypassrls": False}, role
    actor, stranger = uuid.uuid4(), uuid.uuid4()
    grants = {
        _OWNER_TOKEN: {
            "workspace_id": str(repository.workspace_id),
            "actor": str(actor),
            "permissions": EVERY_PERMISSION,
        },
        _STRANGER_TOKEN: {
            "workspace_id": str(stranger),
            "actor": str(uuid.uuid4()),
            "permissions": EVERY_PERMISSION,
        },
    }
    with scratch_database(scratch).session(stranger) as connection:
        world = registered_world(connection, stranger)
        WorldStyleRepository(connection, stranger, world_id=world).register_topology(
            TopologyContract("stranger-topology", ("region-a",), world_id=world)
        )
    store = LocalContentAddressedStore(tmp_path / "blobs")
    tiles = tile_store(tmp_path / "tiles")
    services = Services(
        database=database,
        readonly_database=scratch_role_database(scratch, _READER_ROLE),
        store=store,
        tokens=load_token_directory({"EXULANICA_API_TOKENS": json.dumps(grants)}),
        executor_shares_the_write_role=False,
        model_client=None,
        environment_admission_root=tmp_path / "admission",
        tiles=tiles,
        materials=MaterialRuntime(
            catalog=CATALOG, stores=LocalWorkspaceStores(tmp_path / "materials")
        ),
        character_appearance=CharacterAppearanceRuntime(
            (family(),), lambda _connection, _session, _family: True
        ),
    )
    app = create_app(services, verify=False)
    # A 500 is an answer to compare, not an exception to stop at: a foreign id that makes the
    # server fail where an invented one does not is exactly what this file looks for.
    with TestClient(app, raise_server_exceptions=False) as client:
        owner = Existence(
            client=client,
            app=app,
            repository=repository,
            store=store,
            tiles=tiles,
            actor=actor,
            photo_dir=photo_dir,
            tmp_path=tmp_path,
        )
        app.state.society_initial_input = _provide_society_input(owner)
        app.state.society_input_authorizer = lambda _connection, _session, _document: None
        yield owner


def route_kinds(method: str, path: str) -> dict[str, Owned | Shared | None]:
    """The builder a route asks for at each id it takes: its override, else its address's."""
    overrides = BUILDER_OVERRIDES.get(f"{method} {path}", {})
    return {
        address.address: overrides.get(address.address) or EXISTENCE_BUILDERS.get(address.address)
        for address in id_addresses(path)
    }


def unbuildable(routes) -> list[str]:
    """Each id a route takes that no builder makes, as ``address (METHOD /path)``."""
    return sorted(
        {
            f"{address} ({method} {path})"
            for method, path in routes
            for address, kind in route_kinds(method, path).items()
            if kind is None
        }
    )


def existence_problems(existence: Existence, method: str, path: str, probe=None) -> list[str]:
    """Every way one route tells a stranger something about ids it does not own, as sentences.

    ``probe`` is the request to send; without one it is the route's entry in
    :data:`route_probes.EXISTENCE_REQUESTS`, made once the ids exist, else its probe.
    """
    route = f"{method} {path}"
    if missing := unbuildable([(method, path)]):
        return [f"{route} takes an id no builder in EXISTENCE_BUILDERS makes: {missing}"]
    addresses = id_addresses(path)
    kinds = route_kinds(method, path)
    real = {address.placeholder: "" for address in addresses}
    for address in reversed(addresses):
        real[address.placeholder] = existence.real(address.address, kinds[address.address])
    if probe is None:
        made = EXISTENCE_REQUESTS.get(route)
        probe = made(existence) if made is not None else ROUTE_PROBES[(method, path)]
    owned = [address for address in addresses if isinstance(kinds[address.address], Owned)]

    def ask(send, values: Mapping[str, str]) -> Answer:
        return Answer.of(send(method, fill(path, values), **copy.deepcopy(probe)), values)

    if not owned:
        stranger = ask(existence.as_stranger, real)
        owner = ask(existence.request, real)
        invented = {address.placeholder: kinds[address.address].invent() for address in addresses}
        unknown = ask(existence.as_stranger, invented)
        if stranger != owner:
            return [
                f"{route} takes only kinds declared Shared, and answers a stranger ({stranger}) "
                f"otherwise than its owner ({owner}); a kind one workspace can see and another "
                "cannot is owned, and needs an Owned builder"
            ]
        if stranger == unknown:
            return [
                f"{route} answers a real shared id as it answers an invented one ({unknown}), so "
                "nothing shows that the id it was sent is real or that the route looked it up"
            ]
        return []

    invented = {address.placeholder: kinds[address.address].invent() for address in owned}
    answers: dict[str, Answer] = {}
    for choice in itertools.product((True, False), repeat=len(owned)):
        values = dict(real)
        for address, foreign in zip(owned, choice, strict=True):
            if not foreign:
                values[address.placeholder] = invented[address.placeholder]
        label = ", ".join(
            f"{address.placeholder} {'foreign' if foreign else 'invented'}"
            for address, foreign in zip(owned, choice, strict=True)
        )
        answers[label] = ask(existence.as_stranger, values)
    problems = []
    if len(set(answers.values())) > 1:
        problems.append(
            f"{route} answers a stranger differently for a foreign id and an invented one:\n"
            + "\n".join(f"    {label}: {answer}" for label, answer in answers.items())
        )
    foreign = next(iter(answers.values()))
    if any(answer.stopped_at_validation for answer in answers.values()):
        problems.append(
            f"{route} stopped at request validation ({foreign}) before its own lookup; give it "
            "a request in PROBE_OVERRIDES that the route accepts"
        )
    if any(answer.status >= 500 for answer in answers.values()):
        problems.append(f"{route} failed on a stranger's request: {foreign}")
    owner = ask(existence.request, real)
    if owner == foreign:
        problems.append(
            f"{route} answers its owner exactly as it answers a stranger ({owner}), so nothing "
            "shows that the ids it was sent are real or that the route looked them up"
        )
    return problems


def chosen_id_problems(existence: Existence, route: str, chosen: Chosen) -> list[str]:
    """Every way a create route tells a stranger another workspace chose an id, as sentences."""
    method, path = route_key(route)
    owners = str(chosen.owned(existence))
    fresh = str(uuid.uuid4())

    def ask(caller, value: str) -> Answer:
        response = caller.request(method, path, **chosen.request(caller, value))
        return Answer.of(response, {chosen.field: value})

    foreign = ask(existence.stranger, owners)
    invented = ask(existence.stranger, fresh)
    problems = []
    if (foreign.status, foreign.code, foreign.shape) != (
        invented.status,
        invented.code,
        invented.shape,
    ):
        problems.append(
            f"{route} answers a stranger naming the {chosen.field} another workspace chose "
            f"otherwise than a fresh one:\n    foreign: {foreign}\n    invented: {invented}"
        )
    if not 200 <= invented.status < 300:
        problems.append(
            f"{route} refused a stranger's fresh {chosen.field} ({invented}), so the answers "
            "compared are two refusals and say nothing about the id"
        )
    reused = ask(existence, owners)
    if not (400 <= reused.status < 500 and reused.code):
        problems.append(
            f"{route} answered the owner naming its own {chosen.field} again with {reused}, "
            "which is not a refusal by name"
        )
    return problems


# -- without a database ---------------------------------------------------------------------------


def test_the_sweep_sees_the_id_routes_by_name():
    """The guard on the guard: the derived list holds the routes a reader would name."""
    routes = id_routes()
    for key in (
        ("GET", "/evidence/{span_id}"),
        ("POST", "/person-regions/{capture_id}/edits"),
        ("GET", "/world/versions/{version_id}/society/actions/{request_id}"),
        ("GET", "/tiles/{baked_tile_id}/bytes"),
    ):
        assert key in routes, key
    assert all(id_addresses(path) for _method, path in routes)
    assert ("GET", "/graph") not in routes


def test_every_id_a_route_takes_has_a_builder():
    assert unbuildable(id_routes()) == [], (
        "a route takes an id no builder in tests/route_probes.py EXISTENCE_BUILDERS can make"
    )


def test_a_route_with_an_id_nobody_can_build_is_named():
    """Positive control for the check above: a route taking a new kind of id is named, not
    skipped."""
    planted = [("GET", "/planted/{widget_id}/parts/{part_id}")]
    assert unbuildable(planted) == [
        "/planted/{widget_id} (GET /planted/{widget_id}/parts/{part_id})",
        "/planted/{widget_id}/parts/{part_id} (GET /planted/{widget_id}/parts/{part_id})",
    ]


def test_every_builder_is_for_an_id_some_route_takes():
    """A builder for an address no route has any more is a kind asked about by nothing."""
    taken = {address.address for _method, path in id_routes() for address in id_addresses(path)}
    assert sorted(set(EXISTENCE_BUILDERS) - taken) == []


def test_every_chosen_id_names_a_field_its_create_route_takes():
    """The stale-entry check for CHOSEN_IDS, read from each route's own request schema."""
    from exulanica.api.surface import routing_only_application

    spec = routing_only_application().openapi()
    routes = list(CHOSEN_IDS)
    assert routes == sorted(routes, key=lambda route: route_key(route)[::-1])
    for route, chosen in CHOSEN_IDS.items():
        method, path = route_key(route)
        assert isinstance(permissions.ROUTE_RULES.get((method, path)), Requires), route
        body = spec["paths"][path][method.lower()]["requestBody"]["content"]["application/json"]
        schema = spec["components"]["schemas"][body["schema"]["$ref"].split("/")[-1]]
        assert chosen.field in schema["properties"], (route, chosen.field)


@pytest.mark.parametrize("table", ["BUILDER_OVERRIDES", "EXISTENCE_REQUESTS"])
def test_every_route_entry_names_an_id_route_and_stays_sorted(table):
    """The stale-entry check for the two per-route tables, and the order two changes share."""
    entries = {"BUILDER_OVERRIDES": BUILDER_OVERRIDES, "EXISTENCE_REQUESTS": EXISTENCE_REQUESTS}
    assert list(EXISTENCE_BUILDERS) == sorted(EXISTENCE_BUILDERS), "sorted by address"
    routes = list(entries[table])
    assert routes == sorted(routes, key=lambda route: route_key(route)[::-1])
    for route in routes:
        assert route_key(route) in id_routes(), f"{table} names {route}, which takes no id"
    for route, overrides in BUILDER_OVERRIDES.items():
        taken = {address.address for address in id_addresses(route_key(route)[1])}
        assert set(overrides) <= taken, route


def test_an_address_names_its_kind_and_the_kinds_outside_it():
    assert id_addresses("/world/versions/{version_id}/objects/{object_id}/move") == (
        IdAddress("version_id", "/world/versions/{version_id}"),
        IdAddress("object_id", "/world/versions/{version_id}/objects/{object_id}"),
    )
    # A closed-set parameter is not an id and names no kind of its own.
    assert id_addresses("/environment-resources/{kind}/{resource_id}/bytes") == (
        IdAddress("resource_id", "/environment-resources/{kind}/{resource_id}"),
    )


# -- the sweep ------------------------------------------------------------------------------------


@pytest.mark.parametrize(("method", "path"), id_routes())
def test_a_stranger_cannot_tell_a_foreign_id_from_an_invented_one(existence, method, path):
    problems = existence_problems(existence, method, path)
    assert problems == [], "\n".join(problems)


@pytest.mark.parametrize("route", sorted(CHOSEN_IDS))
def test_a_stranger_cannot_tell_an_id_another_workspace_chose_from_a_fresh_one(existence, route):
    problems = chosen_id_problems(existence, route, CHOSEN_IDS[route])
    assert problems == [], "\n".join(problems)


#: The planted route the positive control mounts. Its address is the evidence span's, so the
#: span builder makes the real id it is asked about.
_PLANTED = "/evidence/{span_id}/planted-oracle"


#: What the planted route answers for an id that exists nowhere.
_NOWHERE = (404, {"code": "unknown_reference", "detail": "no such evidence"})


def _plant(existence: Existence, monkeypatch, foreign: tuple[int, dict]) -> tuple[str, str]:
    """Mount a route that looks a span up in every workspace, and declare it.

    It answers ``foreign`` for a span another workspace holds and :data:`_NOWHERE` for a span
    nobody holds, reading through the administrative connection, which row-level security does
    not bind, the way a lookup that forgot its workspace would.
    """

    def planted(span_id: uuid.UUID, session: CurrentSession):
        row = existence.repository.connection.execute(
            "select workspace_id from evidence_span where span_id = %s", (span_id,)
        ).fetchone()
        if row is None:
            return JSONResponse(_NOWHERE[1], _NOWHERE[0])
        if row["workspace_id"] != session.workspace_id:
            return JSONResponse(foreign[1], foreign[0])
        return {"span_id": str(span_id)}

    existence.app.add_api_route(_PLANTED, planted, methods=["GET"])
    rule = Requires(frozenset({Permission.LIBRARY_READ}))
    declared = MappingProxyType({**permissions.ROUTE_RULES, ("GET", _PLANTED): rule})
    monkeypatch.setattr(permissions, "ROUTE_RULES", declared)
    assert ("GET", _PLANTED) in id_routes(declared), "a declared route is swept"
    return "GET", _PLANTED


@pytest.mark.parametrize(
    "foreign",
    [
        pytest.param((403, {"code": "not_authorised", "detail": "not yours"}), id="status"),
        pytest.param(
            (404, {"code": "unknown_reference", "detail": "this evidence is somebody else's"}),
            id="detail",
        ),
    ],
)
def test_a_route_that_tells_a_foreign_id_from_an_invented_one_fails(
    existence, monkeypatch, foreign
):
    """Positive controls: the oracle M10 names, planted, is reported with both answers, whether
    the status says it or only the detail does."""
    method, path = _plant(existence, monkeypatch, foreign)
    problems = existence_problems(existence, method, path, {})
    assert len(problems) == 1, problems
    assert f"span_id foreign: {foreign[0]} " in problems[0], problems[0]
    assert f"span_id invented: {_NOWHERE[0]} " in problems[0], problems[0]


def test_the_same_route_answering_both_alike_passes(existence, monkeypatch):
    """The controls' other arm, so what they report is the difference and not the planting."""
    method, path = _plant(existence, monkeypatch, _NOWHERE)
    assert existence_problems(existence, method, path, {}) == []


#: The create route the chosen-id controls mount. It records nothing; it answers from what already
#: exists, which is all the check reads.
_PLANTED_CREATE = "/planted-proposals"


def _plant_create(existence: Existence, monkeypatch, *, every_workspace: bool) -> Chosen:
    """Mount a create route refusing a proposal id already used, in every workspace or the caller's.

    Looking in every workspace is the fault 0102 removed from three tables: the refusal it gives a
    stranger for another workspace's id is what a fresh id never gets.
    """

    def planted(body: dict, session: CurrentSession):
        where = "" if every_workspace else " and workspace_id = %s"
        found = existence.repository.connection.execute(
            "select 1 from world_style_proposal where proposal_id = %s" + where,
            (body["proposal_id"],)
            if every_workspace
            else (body["proposal_id"], session.workspace_id),
        ).fetchone()
        if found is not None:
            return JSONResponse({"code": "proposal_id_used", "detail": "already used"}, 409)
        return JSONResponse({"proposal_id": body["proposal_id"]}, 201)

    existence.app.add_api_route(_PLANTED_CREATE, planted, methods=["POST"])
    rule = Requires(frozenset({Permission.WORLD_WRITE}))
    declared = MappingProxyType({**permissions.ROUTE_RULES, ("POST", _PLANTED_CREATE): rule})
    monkeypatch.setattr(permissions, "ROUTE_RULES", declared)
    return Chosen(
        "proposal_id",
        CHOSEN_IDS["POST /world/styles/previews"].owned,
        lambda _caller, value: {"json": {"proposal_id": value}},
    )


def test_a_create_route_refusing_another_workspaces_id_fails(existence, monkeypatch):
    """Positive control: the fault, planted, is reported with both answers."""
    chosen = _plant_create(existence, monkeypatch, every_workspace=True)
    problems = chosen_id_problems(existence, f"POST {_PLANTED_CREATE}", chosen)
    assert len(problems) == 1, problems
    assert "foreign: 409" in problems[0] and "invented: 201" in problems[0], problems[0]


def test_the_same_create_route_looking_only_in_the_callers_workspace_passes(existence, monkeypatch):
    """The control's other arm, so what it reports is the lookup and not the planting."""
    chosen = _plant_create(existence, monkeypatch, every_workspace=False)
    assert chosen_id_problems(existence, f"POST {_PLANTED_CREATE}", chosen) == []
