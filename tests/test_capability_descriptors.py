"""A capability descriptor states nothing its route, its permission or its schema does not.

The capability reads (:mod:`exulanica.api.routes.capabilities`) serve each operation as the route
that performs it, the permissions that route declares, and the body fields that carry its base and
its retry key. These checks run every adapter over worlds of each kind without a database and hold
every descriptor to the application's own router, :data:`~exulanica.api.permissions.ROUTE_RULES`
and OpenAPI document, so a route renamed, a permission changed or a body field dropped fails here by
name. They also hold the adapters and :data:`~exulanica.api.routes.capabilities.NOT_PROJECTED` to
every mutating route of a version, the way the route probes hold ROUTE_RULES to the router.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from exulanica.api import capabilities
from exulanica.api.permissions import ROUTE_RULES, Permission, Requires
from exulanica.api.role_hosts import ROLE_HOSTS, choice_status
from exulanica.api.routes import capabilities as reads
from exulanica.api.routes.society_models import CHOICE_CONFLICTS
from exulanica.api.routes.world_models import choose_world_model
from exulanica.api.routes.world_objects import add_authored_object
from exulanica.api.surface import routing_only_application
from exulanica.selection.validation import Session
from exulanica.world.decision_roles import decision_roles
from exulanica.world.object_repository import SourceFacts
from exulanica.world.society_engines import society_engine
from exulanica.world.society_grounds import created_engine, society_grounds
from exulanica.world.traffic_episodes import TrafficRefused
from exulanica.world.worlds import WORLD_KINDS, world_kind

APP = routing_only_application()
ROUTES = capabilities.surface(APP)
DOCUMENT = APP.openapi()
SCHEMAS = DOCUMENT["components"]["schemas"]
EVERYTHING = frozenset(Permission)
_VERSION_PREFIX = "/world/versions/{version_id}/"
#: The operations whose route holds model.invoke only to decide who may act and that call no
#: model, so they are described as spending nothing. Each is a reviewed exception, added here
#: together with a test that it calls no model.
NARROWED_SPENDS: frozenset[str] = frozenset(
    {
        # tests/test_comparison_cancel_postgres.py: a cancel closes a waiting start with no
        # request sent, and a host it stops sends nothing after its minute in flight.
        "POST /world/versions/{version_id}/society/comparisons/{comparison_id}/cancel",
    }
)


class _NoRows:
    """A connection whose every query finds nothing: a version with no society in it."""

    def execute(self, *_args: Any, **_kwargs: Any) -> _NoRows:
        return self

    def fetchone(self) -> None:
        return None

    def fetchall(self) -> list[Any]:
        return []


def _services(**changes: Any) -> SimpleNamespace:
    values: dict[str, Any] = {
        "store": None,
        "character_appearance": object(),
        "model_host_refusal": lambda _workspace, _role: "models_not_run_here",
        "comparison_refusal": lambda _workspace: "comparisons_not_set_up",
    }
    return SimpleNamespace(**(values | changes))


def _context(
    ground_key: str,
    *,
    society: str | None = None,
    invalidated: bool = False,
    held: frozenset[Permission] = EVERYTHING,
    **services: Any,
) -> capabilities.VersionContext:
    ground = next(item for item in society_grounds() if item.key == ground_key)
    kind = {
        "authored_starter": "authored-starter",
        "made_world": "personal-source",
        "generated_town": "generated",
    }[ground_key]
    services_used = _services(**services)
    app = SimpleNamespace(
        state=SimpleNamespace(society_initial_input=object(), services=services_used)
    )
    row = None if society is None else {"society_id": uuid.uuid4(), "engine_version": society}
    return capabilities.VersionContext(
        request=SimpleNamespace(app=app),  # type: ignore[arg-type]
        connection=_NoRows(),  # type: ignore[arg-type]
        session=Session(uuid.uuid4(), uuid.uuid4()),
        services=services_used,  # type: ignore[arg-type]
        held=held,
        world_id=f"world:test:{ground_key}",
        kind=world_kind(kind),
        version_id=uuid.uuid4(),
        source=SourceFacts(
            snapshot_id=uuid.uuid4(),
            composer_key=ground.composer_key,
            region_ids=frozenset({"region:a"}),
            invalidated=invalidated,
        ),
        ground=ground,
        society=row,
        engine=society_engine(society if society is not None else created_engine(ground)),
    )


@pytest.fixture(autouse=True)
def _no_roads(monkeypatch):
    """Roads are compiled from a saved snapshot's records, which no database here holds."""

    def refused(*_args: Any) -> None:
        raise TrafficRefused("roads_not_stated", "no records in a test without a database")

    monkeypatch.setattr(reads, "saved_world_roads", refused)


def _operations(context: capabilities.VersionContext) -> list[capabilities.Operation]:
    return [operation for adapter in reads.VERSION_ADAPTERS for operation in adapter(context)]


def _described(context: capabilities.VersionContext) -> list[dict[str, Any]]:
    return [capabilities.describe(op, ROUTES, context.held) for op in _operations(context)]


CASES = [
    ("authored_starter", None),
    ("authored_starter", "exulanica-society/v2"),
    ("made_world", "exulanica-society/v2"),
    ("generated_town", None),
    ("generated_town", "exulanica-society/v5"),
]


def _properties(component: str | None) -> set[str]:
    return set() if component is None else set(SCHEMAS[component].get("properties", {}))


def _route(key: str) -> tuple[str, str]:
    method, path = key.split(" ", 1)
    return method, path


@pytest.mark.parametrize(("ground", "society"), CASES)
def test_every_descriptor_is_its_routes_own(ground, society):
    for described in _described(_context(ground, society=society)):
        method, path = _route(described["operation"])
        rule = ROUTE_RULES[(method, path)]
        assert isinstance(rule, Requires), described["operation"]
        assert described["requires"] == sorted(str(p) for p in rule.permissions)
        assert described["spends"] == (
            Permission.MODEL_INVOKE in rule.permissions
            and described["operation"] not in NARROWED_SPENDS
        )
        operation = DOCUMENT["paths"][path][method.lower()]
        assert (described["input"] is None) == ("requestBody" not in operation), described
        inputs = _properties(described["input"])
        for base in described["base"]:
            assert base["field"] in inputs, (described["operation"], base)
            assert _route(base["read"])[0] == "GET", base
        if described["idempotency"] is not None:
            assert described["idempotency"] in inputs, described["operation"]
        if described["preview"] is not None and described["preview"]["token"] is not None:
            assert described["preview"]["token"] in inputs, described["operation"]
        for read in described["options"]:
            assert _route(read)[0] == "GET", (described["operation"], read)
        if described["subjects"] is not None:
            assert _route(described["subjects"]["read"])[0] == "GET", described
        if described["state"] == "available":
            assert described["code"] is None
        else:
            assert described["code"], described


def test_a_base_token_names_a_field_its_typed_read_answers_with():
    """Where the read that returns a base token declares its answer, the token is a field of it."""
    for ground, society in CASES:
        for described in _described(_context(ground, society=society)):
            for base in described["base"]:
                method, path = _route(base["read"])
                answers = DOCUMENT["paths"][path][method.lower()]["responses"]["200"]
                schema = answers.get("content", {}).get("application/json", {}).get("schema", {})
                reference = schema.get("$ref")
                if reference is not None:
                    typed = SCHEMAS[reference.rsplit("/", 1)[-1]]["properties"]
                    assert base["value"] in typed, (described["operation"], base)


def test_every_mutating_route_of_a_version_is_projected_or_named_as_not():
    projected: set[tuple[str, str]] = set()
    for ground, society in CASES:
        for described in _described(_context(ground, society=society)):
            projected.add(_route(described["operation"]))
            # A route named as another's preview is discovered through that operation.
            if described["preview"] is not None:
                projected.add(_route(described["preview"]["operation"]))
    mutating = {
        (method, path)
        for method, path in ROUTE_RULES
        if path.startswith(_VERSION_PREFIX) and method != "GET"
    }
    named = set(reads.NOT_PROJECTED)
    assert named <= set(ROUTE_RULES), sorted(named - set(ROUTE_RULES))
    assert not (named & projected), sorted(named & projected)
    assert mutating <= projected | named, sorted(mutating - projected - named)
    for reason in reads.NOT_PROJECTED.values():
        assert reason.strip()


def test_every_kind_of_world_has_one_way_to_be_made():
    assert set(reads.CREATORS) == {kind.name for kind in WORLD_KINDS}


def _state(context: capabilities.VersionContext, operation: str) -> tuple[str, str | None]:
    found = [
        (d["state"], d["code"])
        for d in _described(context)
        if d["operation"] == operation and "role_key" not in d["bind"]
    ]
    assert len(found) == 1, (operation, found)
    return found[0]


def test_a_town_states_what_its_engine_and_ground_never_do():
    town = _context("generated_town", society="exulanica-society/v5")
    assert _state(town, "POST /world/versions/{version_id}/arrangements/preview") == (
        "unsupported",
        "arrangement_needs_authored_ground",
    )
    assert _state(town, "POST /world/versions/{version_id}/society/presence") == (
        "unsupported",
        "engine_keeps_its_people",
    )
    assert _state(town, "POST /world/versions/{version_id}/society/actions") == (
        "unsupported",
        "engine_takes_no_directed_actions",
    )
    placed = next(
        d for d in _described(town) if d["operation"] == "POST /world/versions/{version_id}/objects"
    )
    assert placed["effects"] == [
        {"on": "society", "state": "unsupported", "code": "authored_affordance_unreachable"}
    ]
    # Before its society is brought, a town already says what its engine will never do.
    empty = _context("generated_town")
    assert _state(empty, "POST /world/versions/{version_id}/society/presence")[0] == "unsupported"
    assert _state(empty, "PUT /world/versions/{version_id}/society/control") == (
        "unavailable",
        "society_unavailable",
    )


def test_a_starter_world_states_its_lattice_and_its_missing_society():
    starter = _context("authored_starter")
    assert _state(starter, "POST /world/versions/{version_id}/arrangements/apply") == (
        "available",
        None,
    )
    assert _state(starter, "POST /world/versions/{version_id}/society/presence") == (
        "unavailable",
        "society_unavailable",
    )
    placed = next(
        d
        for d in _described(starter)
        if d["operation"] == "POST /world/versions/{version_id}/objects"
    )
    assert placed["effects"] == [{"on": "society", "state": "available", "code": None}]
    assert _state(starter, "GET /world/versions/{version_id}/traffic") == (
        "unavailable",
        "roads_not_stated",
    )


def test_an_invalidated_source_refuses_each_edit_by_its_own_code():
    stale = _context("made_world", society="exulanica-society/v2", invalidated=True)
    assert _state(stale, "POST /world/versions/{version_id}/objects") == (
        "unavailable",
        "invalidated_source_version",
    )
    # Arrangements and compositions name the same state by the code their own refusals carry.
    assert _state(stale, "POST /world/versions/{version_id}/arrangements/apply") == (
        "unavailable",
        "source_invalidated",
    )
    assert _state(stale, "POST /world/versions/{version_id}/compositions/apply") == (
        "unavailable",
        "source_invalidated",
    )


def test_a_grant_without_a_write_is_told_so_and_the_state_is_unchanged():
    reader = _context("authored_starter", held=frozenset({Permission.WORLD_READ}))
    for described in _described(reader):
        writes = {"world.write", "model.invoke", "admission.read"} & set(described["requires"])
        assert described["permitted"] == (not writes), described["operation"]
    assert _state(reader, "POST /world/versions/{version_id}/objects") == ("available", None)


def test_every_registered_role_has_a_host_and_a_choice_descriptor():
    assert {role.subject for role in decision_roles()} <= set(ROLE_HOSTS)
    town = _context("generated_town", society="exulanica-society/v5")
    roles = {
        d["bind"]["role_key"]: d
        for d in _described(town)
        if d["operation"] == "POST /world/versions/{version_id}/models/{role_key}"
    }
    assert set(roles) == {role.key for role in decision_roles()}
    for described in roles.values():
        assert described["spends"] and described["idempotency"] == "idempotency_key"
        assert described["options"] == ["GET /world/versions/{version_id}/models"]


def test_a_choice_is_refused_with_the_status_its_code_has_on_every_route():
    # The people's own route answers these statuses; the world's models route now agrees.
    for code in CHOICE_CONFLICTS:
        assert choice_status(code) == 409
    for code in (
        "model_not_declared",
        "model_not_offered",
        "model_not_askable",
        "person_named_twice",
        "person_not_in_this_world",
        "subject_chosen_under_another_role",
        "too_many_model_people",
        "too_many_model_signals",
        "signal_not_in_world",
        "one_signal_per_choice",
        "person_id_invalid",
    ):
        assert choice_status(code) == 422, code
    assert choice_status("roads_unavailable") == 409
    for code in ("traffic_controller_unavailable", "traffic_worker_unavailable"):
        assert choice_status(code) == 503


def test_an_available_state_never_carries_a_code_and_a_refusal_always_does():
    with pytest.raises(ValueError):
        capabilities.Availability("available", "something")
    for state in ("unavailable", "unsupported"):
        with pytest.raises(ValueError):
            capabilities.Availability(state)  # type: ignore[arg-type]
    assert capabilities.unknown().code is None


def test_spending_is_narrowed_only_where_it_is_reviewed():
    narrowed = {
        capabilities.describe(operation, ROUTES, EVERYTHING)["operation"]
        for ground, society in CASES
        for operation in _operations(_context(ground, society=society))
        if operation.spends is False
    }
    assert narrowed == NARROWED_SPENDS


def test_spending_is_never_widened_and_is_narrowed_only_under_model_invoke():
    with pytest.raises(ValueError, match="never widen"):
        capabilities.Operation(
            add_authored_object,
            capabilities.AVAILABLE,
            "version",
            spends=True,  # type: ignore[arg-type]
        )
    placed = capabilities.Operation(
        add_authored_object, capabilities.AVAILABLE, "version", spends=False
    )
    with pytest.raises(ValueError, match="no spending to narrow"):
        capabilities.describe(placed, ROUTES, EVERYTHING)
    # Narrowing changes what the operation says it spends, never who may perform it.
    chosen = capabilities.Operation(
        choose_world_model,
        capabilities.AVAILABLE,
        "person",
        {"version_id": str(uuid.uuid4()), "role_key": "society_decision"},
        spends=False,
    )
    described = capabilities.describe(chosen, ROUTES, EVERYTHING)
    assert described["spends"] is False
    assert "model.invoke" in described["requires"] and described["permitted"]


def test_an_endpoint_that_serves_no_route_is_refused_by_name():
    with pytest.raises(LookupError, match="serves 0 routes"):
        ROUTES.route(test_an_endpoint_that_serves_no_route_is_refused_by_name)


def test_no_operation_is_listed_twice_for_one_subject():
    for ground, society in CASES:
        described = _described(_context(ground, society=society))
        keys = [(d["operation"], tuple(sorted(d["bind"].items()))) for d in described]
        assert len(keys) == len(set(keys)), (ground, society)
