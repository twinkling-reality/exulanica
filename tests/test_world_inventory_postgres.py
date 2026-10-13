"""World overview uses SELECT-only authored reads and restricted runtime society read locks."""

import dataclasses
import uuid

import pytest
from exulanica.api.routes import world_inventory, world_kinds
from exulanica.db.roles import provision_runtime_role
from psycopg import sql

import test_subject_offer_postgres as subjects
import test_thing_card_postgres as cards
import test_world_models_route as model_routes
import test_world_traffic_route as traffic
from conftest import scratch_role_database
from test_society_made_world import made as imported_made  # noqa: F401
from test_society_saved_world_api import OWNER, routes

_presets_try_every_candidate = traffic._presets_try_every_candidate
saved_world = cards.saved_world
app = cards.app
pytestmark = pytest.mark.postgres


def _read(client, world, headers=OWNER, version_id=None, world_id=None):
    scope, version, _ = routes(world)
    if world_id is not None:
        scope["world_id"] = world_id
    if version_id is not None:
        version = f"/world/versions/{version_id}"
    return client.get(version + "/inventory", headers=headers, params=scope)


def _reader(world, client, spine_schema):
    role = "exulanica_inventory_reader_suite"
    provision_runtime_role(world["connection"], role=role, read_only=True)
    world["connection"].commit()
    database = scratch_role_database(spine_schema[1], role)
    with database.session(world["workspace"]) as connection:
        assert connection.execute(
            "select rolsuper,rolbypassrls from pg_roles where rolname=current_user"
        ).fetchone() == {"rolsuper": False, "rolbypassrls": False}
        assert not connection.execute(
            "select has_table_privilege(current_user,'world_society','INSERT') as allowed"
        ).fetchone()["allowed"]
    client.app.state.services = dataclasses.replace(
        client.app.state.services,
        readonly_database=database,
        executor_shares_the_write_role=False,
    )


def _counts(world):
    tables = (
        "job",
        "world_draft_request",
        "spending_reservation",
        "world_society_event",
        "world_society_model_choice",
        "world_society_control",
        "world_traffic_signal_choice",
    )
    with world["connection"].transaction():
        return {
            table: world["connection"]
            .execute(sql.SQL("select count(*) as n from {}").format(sql.Identifier(table)))
            .fetchone()["n"]
            for table in tables
        }


def _forbid_work(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("inventory must not start drawing or model work")

    monkeypatch.setattr(world_kinds, "kind_worker", forbidden)
    from exulanica.models.client import ModelClient

    monkeypatch.setattr(ModelClient, "chat", forbidden)
    monkeypatch.setattr(ModelClient, "choose", forbidden)
    monkeypatch.setattr(ModelClient, "structured", forbidden)


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_read_role_lists_actual_population_things_and_preserves_native_roles(
    app, spine_schema, monkeypatch
):
    world, client = app
    snapshot = cards._society(client, world)
    _reader(world, client, spine_schema)
    reader, colleague, stranger, ungranted = subjects._setup_grants(world, client, monkeypatch)
    scope, version, _ = routes(world)
    native = client.get(version + "/models", headers=OWNER, params=scope)
    role = next(role for role in native.json()["roles"] if role["subject"] == "person")
    knight = next(
        row for row in snapshot["state"]["inhabitants"] if row.get("placed_id") == "knight"
    )
    model = role["view"]["models"][0]
    chosen = client.post(
        version + "/models/" + role["key"],
        headers=OWNER,
        params=scope,
        json={
            "idempotency_key": str(uuid.uuid4()),
            "subjects": [knight["id"]],
            "model": {"provider": model["provider"], "model_id": model["model_id"]},
        },
    )
    assert chosen.status_code == 200, chosen.text
    _forbid_work(monkeypatch)
    counts = _counts(world)
    response = _read(client, world, reader)
    assert response.status_code == 200, response.text
    assert response.headers["Cache-Control"] == "private, no-store"
    view = response.json()
    assert view["profile"] == "exulanica.world-inventory/v1"
    for collection, source in (("inhabitants", "society-being"), ("things", "society-thing")):
        identities = {
            ref["id"]
            for row in view["entities"]
            for ref in [row["reference"], *row["aliases"]]
            if ref["source"] == source
        }
        assert identities == {row["id"] for row in snapshot["state"][collection]}
        if collection == "inhabitants":
            for person in snapshot["state"][collection]:
                assert person["display_name"].strip()
                entity = next(
                    row
                    for row in view["entities"]
                    if any(
                        ref == {"source": source, "id": person["id"]}
                        for ref in [row["reference"], *row["aliases"]]
                    )
                )
                assert entity["label"] == person["display_name"]
    for entity in view["entities"]:
        if entity["detail"] is not None:
            detail = entity["detail"]
            path = detail["route"].split(" ", 1)[1].format(**detail["bind"])
            answer = client.get(path, params=detail["query"], headers=reader)
            assert answer.status_code == 200, answer.text
    scope, version, _ = routes(world)
    native = client.get(version + "/models", headers=reader, params=scope)
    assert native.status_code == 200, native.text
    assert view["roles"] == native.json()["roles"]
    assert _counts(world) == counts
    choice = next(
        row
        for row in next(role for role in view["roles"] if role["subject"] == "person")["view"][
            "choices"
        ]
        if row["subject_id"] == knight["id"]
    )
    assert choice["decider"]["kind"] == "model"
    assert choice["model"]["model_id"] == model["model_id"]
    plan = subjects._prepare(client, world, {"operation": "play_being", "subject_id": knight["id"]})
    played = subjects._send(client, plan["steps"][0])
    assert played.status_code == 201, played.text
    counts = _counts(world)
    after = _read(client, world, colleague)
    assert after.status_code == 200, after.text
    native = client.get(version + "/models", headers=colleague, params=scope)
    assert after.json()["roles"] == native.json()["roles"]
    choices = next(role for role in after.json()["roles"] if role["subject"] == "person")["view"][
        "choices"
    ]
    own = next(row for row in choices if row["subject_id"] == knight["id"])
    assert own["decider"]["kind"] == "person"
    assert str(world["session"].actor) not in str(own)
    assert _counts(world) == counts
    assert _read(client, world, ungranted).status_code == 404
    foreign = _read(client, world, stranger)
    invented = _read(client, world, stranger, version_id=uuid.uuid4())
    assert foreign.status_code == invented.status_code == 404
    assert foreign.json() == invented.json()


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_absent_society_and_final_authorization_refusal_do_not_expose_population(
    app, spine_schema, monkeypatch
):
    world, client = app
    _reader(world, client, spine_schema)
    empty = _read(client, world)
    assert empty.status_code == 200, empty.text
    assert {
        row["state"] for row in empty.json()["coverage"] if row["source"].startswith("society.")
    } == {"absent"}
    cards._society(client, world)
    original = world_inventory.world_models_document

    def withdraw_after_roles(*args, **kwargs):
        result = original(*args, **kwargs)
        assert any(role.get("view") is not None for role in result["roles"])
        cards._refusing(client, lambda _document: True)
        return result

    monkeypatch.setattr(world_inventory, "world_models_document", withdraw_after_roles)
    counts = _counts(world)
    refused = _read(client, world)
    assert refused.status_code == 200, refused.text
    view = refused.json()
    assert view["read"]["society"] is None
    assert {row["state"] for row in view["coverage"] if row["source"].startswith("society.")} == {
        "unavailable"
    }
    assert all(
        not row["aliases"] and not row["role_instances"] and row["detail"] is None
        for row in view["entities"]
    )
    assert all(role["view"] is None for role in view["roles"] if role["subject"] == "person")
    assert all(
        role["capability"]["state"] != "available"
        for role in view["roles"]
        if role["subject"] == "person"
    )
    assert _counts(world) == counts


def test_actual_signal_catalog_and_pending_choice_use_native_semantics(request, monkeypatch):
    api = request.getfixturevalue("imported_made")
    traffic._identity(monkeypatch, model_routes._signalled())
    entry = traffic._made(api, "Inventory signal world")
    base = f"/world/versions/{entry['authored_version_id']}"
    query = f"?world_id={entry['world_id']}"
    native = api.get(base + "/models" + query)
    assert native.status_code == 200, native.text
    signal = next(role for role in native.json()["roles"] if role["subject"] == "signal")
    assert signal["available"] and signal["subjects"]
    model = signal["models"][0]
    chosen = api.post(
        base + "/models/" + signal["key"] + query,
        {
            "idempotency_key": str(uuid.uuid4()),
            "subjects": [signal["subjects"][0]["signal_id"]],
            "model": {"provider": model["provider"], "model_id": model["model_id"]},
        },
    )
    assert chosen.status_code == 200, chosen.text
    _forbid_work(monkeypatch)
    response = api.get(base + "/inventory" + query)
    assert response.status_code == 200, response.text
    result = response.json()
    systems = [row for row in result["entities"] if row["category"] == "system"]
    assert {row["reference"]["id"] for row in systems} == {
        row["signal_id"] for row in signal["subjects"]
    }
    read = next(role for role in result["roles"] if role["subject"] == "signal")
    assert read["choices"][0]["status"] == "pending"
    assert read["choices"][0]["active_second"] is None
    assert all(row["reference"]["source"] == "role-subject" for row in systems)
    assert (
        next(row for row in result["coverage"] if row["source"] == "generated_semantics")["state"]
        == "not_enumerated"
    )
