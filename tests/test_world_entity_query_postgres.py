"""Current-look queries use real scoped worlds and reauthorize after container reads."""

import dataclasses
import hashlib
import uuid
from copy import deepcopy
from pathlib import Path

import pytest
from exulanica.api.routes import world_entity_query as route
from exulanica.store.configured import local_content_stores
from exulanica.world.thing_store import ThingStore
from fastapi.testclient import TestClient

import test_society_made_kinds_postgres as made
import test_subject_offer_postgres as subjects
import test_thing_card_postgres as cards
import test_world_inventory_postgres as inventory_tests
from test_appearance_colour import _constant
from test_society_saved_world_api import OWNER, routes
from test_world_entity_query import BODY

saved_world = made.saved_world
saved_world_app = made.saved_world_app
world_app = made.world_app
kept = made.kept
pytestmark = pytest.mark.postgres


@pytest.fixture
def query_world(world_app, kept, tmp_path, spine_schema):
    world, make_app, _, _ = world_app
    with TestClient(make_app()) as client:
        snapshot = made._society(client, world, kept)
        stores = local_content_stores(tmp_path / "query-content")
        stores.looks.for_workspace(world["workspace"]).put_bytes(kept.sketch_container)
        client.app.state.services = dataclasses.replace(
            client.app.state.services, content_stores=stores
        )
        inventory_tests._reader(world, client, spine_schema)
        subject = next(
            p for p in snapshot["state"]["inhabitants"] if p.get("placed_id") == made.CREATURE
        )
        variants = []
        for name, rgb in (("red", (1, 0, 0, 1)), ("green", (0, 1, 0, 1))):
            data = _constant(rgb).build()
            document = deepcopy(dict(kept.sketch.document))
            document.update(
                look="query-" + name,
                label="query " + name,
                container={
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "bytes": len(data),
                    "media_type": "model/gltf-binary",
                },
            )
            with client.app.state.services.database.session(world["workspace"]) as connection:
                look = (
                    ThingStore(
                        connection,
                        world["workspace"],
                        stores.looks.for_workspace(world["workspace"]),
                    )
                    .admit_look(
                        document, data, created_by=world["session"].actor, admit=lambda _: None
                    )
                    .look
                )
            variants.append(look)
        yield world, client, subject, variants, kept


def _read(world, client, headers=OWNER, version=None, world_id=None, body=BODY):
    scope, path, _ = routes(world)
    if version is not None:
        path = f"/world/versions/{version}"
    if world_id is not None:
        scope["world_id"] = world_id
    return client.post(path + "/inventory/query", params=scope, headers=headers, json=body)


def _choose(world, client, subject, look):
    response = cards._swap(
        client, world, subject["id"], {"source": "workspace", "sha256": look.sha256}
    )
    assert response.status_code == 200, response.text
    return response.json()


def _row(response):
    assert response.status_code == 200, response.text
    return next(
        row
        for row in response.json()["entities"]
        if row["reference"] == {"source": "authored-thing", "id": made.CREATURE}
    )


def test_current_selection_matches_actual_container_without_mutation_and_with_read_only_grant(
    query_world, monkeypatch
):
    world, client, subject, (red, green), _ = query_world
    reader, _, stranger, ungranted = subjects._setup_grants(world, client, monkeypatch)
    card = _choose(world, client, subject, red)
    inventory_tests._forbid_work(monkeypatch)
    counts = inventory_tests._counts(world)
    response = _read(world, client, reader)
    row = _row(response)
    assert response.headers["Cache-Control"] == "private, no-store"
    assert row["state"] == "match"
    assert row["appearance"]["look_sha256"] == card["look"]["sha256"] == red.sha256
    assert row["aliases"] == [{"source": "society-being", "id": subject["id"]}]
    assert inventory_tests._counts(world) == counts
    assert cards._card(client, world, subject["id"]).json() == card
    shipped = next(
        one
        for one in response.json()["entities"]
        if one["reference"] == {"source": "authored-thing", "id": "sword"}
    )
    shipped_subject = next(
        alias["id"] for alias in shipped["aliases"] if alias["source"] == "society-thing"
    )
    shipped_card = cards._card(client, world, shipped_subject).json()
    assert shipped["appearance"]["look_sha256"] == shipped_card["look"]["sha256"]
    swapped = _choose(world, client, subject, green)
    assert swapped["society"] == card["society"] and swapped["where"] == card["where"]
    assert _row(_read(world, client))["state"] == "no_match"
    unknown = _read(world, client, version=uuid.uuid4())
    foreign = _read(world, client, stranger)
    assert foreign.status_code == unknown.status_code == 404
    assert _read(world, client, world_id="world:missing").status_code == 404
    assert _read(world, client, ungranted).status_code == 404


def test_withdrawal_during_byte_read_does_not_publish_old_facts_then_matches_card_fallback(
    query_world, monkeypatch
):
    world, client, subject, (red, green), _ = query_world
    _choose(world, client, subject, green)
    _choose(world, client, subject, red)
    original = route.appearance_bytes
    changed = False

    def withdraw(appearance, services, workspace):
        nonlocal changed
        data = original(appearance, services, workspace)
        if appearance.look_sha256 == red.sha256 and not changed:
            changed = True
            with services.database.session(workspace) as connection:
                ThingStore(connection, workspace, None).withdraw_look(
                    red.look,
                    red.version,
                    "query withdrawal test",
                    withdrawn_by=world["session"].actor,
                )
        return data

    monkeypatch.setattr(route, "appearance_bytes", withdraw)
    row = _row(_read(world, client))
    assert changed
    assert (row["state"], row["reason"], row["appearance"], row["match_basis"]) == (
        "unknown",
        "appearance_changed",
        None,
        [],
    )
    fallback = cards._card(client, world, subject["id"]).json()
    assert fallback["look"]["sha256"] == green.sha256
    row = _row(_read(world, client))
    assert row["state"] == "no_match" and row["appearance"]["look_sha256"] == green.sha256


def test_source_withdrawal_during_byte_read_suppresses_society_identity_and_colour(
    query_world, monkeypatch
):
    world, client, subject, (red, _), _ = query_world
    _choose(world, client, subject, red)
    original = route.appearance_bytes
    changed = False

    def withdraw(appearance, services, workspace):
        nonlocal changed
        data = original(appearance, services, workspace)
        if not changed:
            changed = True
            cards._refusing(client, lambda _: True)
        return data

    monkeypatch.setattr(route, "appearance_bytes", withdraw)
    response = _read(world, client)
    row = _row(response)
    view = response.json()
    assert view["read"]["society"] is None
    assert all(
        not one["aliases"] and one["reference"]["source"] not in {"society-being", "society-thing"}
        for one in view["entities"]
    )
    assert row["state"] == "unknown" and row["appearance"] is None and row["match_basis"] == []
    assert {
        source["state"]
        for source in view["coverage"]["sources"]
        if source["source"].startswith("society.")
    } == {"unavailable"}


def test_erased_kind_after_byte_read_loses_appearance_even_when_container_is_retained(
    query_world, monkeypatch
):
    world, client, subject, (red, _), kept = query_world
    _choose(world, client, subject, red)
    original = route.appearance_bytes
    changed = False

    def erase(appearance, services, workspace):
        nonlocal changed
        data = original(appearance, services, workspace)
        if appearance.look_sha256 == red.sha256 and not changed:
            changed = True
            with services.database.session(workspace) as connection:
                ThingStore(connection, workspace, None).erase_creature(
                    kept.kind.sha256, erased_by=world["session"].actor, by_owner=True
                )
        return data

    monkeypatch.setattr(route, "appearance_bytes", erase)
    response = _read(world, client)
    assert response.status_code == 200, response.text
    assert changed
    assert all(
        one["appearance"] is None or one["appearance"]["look_sha256"] != red.sha256
        for one in response.json()["entities"]
    )
    assert not any(
        one["state"] == "match"
        and {"source": "society-being", "id": subject["id"]} in one["aliases"]
        for one in response.json()["entities"]
    )


def test_withdrawn_default_with_no_choice_leaves_card_and_query_without_a_look(query_world):
    world, client, subject, _, kept = query_world
    services = client.app.state.services
    with services.database.session(world["workspace"]) as connection:
        ThingStore(connection, world["workspace"], None).withdraw_look(
            kept.sketch.look,
            kept.sketch.version,
            "default withdrawn",
            withdrawn_by=world["session"].actor,
        )
    card = cards._card(client, world, subject["id"])
    assert card.status_code == 200, card.text
    assert card.json()["look"] is None
    row = _row(_read(world, client))
    assert (row["state"], row["reason"], row["appearance"], row["match_basis"]) == (
        "unknown",
        "look_unavailable",
        None,
        [],
    )


def test_retained_yellow_and_pink_containers_follow_selection_without_changing_kind(query_world):
    world, client, subject, _, kept = query_world
    services = client.app.state.services
    base = Path(__file__).resolve().parents[1] / "assets/things/pond-duck"
    looks = []
    original_hashes = {}
    for name, relative in (("yellow", "yellow-v1/body.glb"), ("pink", "pink-look-v1/body.glb")):
        path = base / relative
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        original_hashes[path] = digest
        document = deepcopy(dict(kept.sketch.document))
        document.update(
            look="query-retained-" + name,
            label="retained " + name,
            container={"sha256": digest, "bytes": len(data), "media_type": "model/gltf-binary"},
        )
        with services.database.session(world["workspace"]) as connection:
            looks.append(
                ThingStore(
                    connection,
                    world["workspace"],
                    services.content_stores.looks.for_workspace(world["workspace"]),
                )
                .admit_look(document, data, created_by=world["session"].actor, admit=lambda _: None)
                .look
            )
    body = deepcopy(BODY)
    body["predicate"]["colour"]["srgb8"] = [242, 200, 74]
    yellow = _choose(world, client, subject, looks[0])
    assert _row(_read(world, client, body=body))["state"] == "match"
    pink = _choose(world, client, subject, looks[1])
    assert _row(_read(world, client, body=body))["state"] == "no_match"
    assert (pink["kind"], pink["society"], pink["where"]) == (
        yellow["kind"],
        yellow["society"],
        yellow["where"],
    )
    assert all(
        hashlib.sha256(path.read_bytes()).hexdigest() == digest
        for path, digest in original_hashes.items()
    )
