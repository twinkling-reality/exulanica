"""Which reviewed assets a person may place, read from the kind each asset declares.

``world_reviewed_asset`` holds every reviewed container a catalog publishes: the generated marker
meshes a person places as authored objects, and the bodies, worn parts and material packs the
character catalog composes into people. The object chooser reads ``GET /world/assets``; without a
declared kind on the row, publishing the character catalog put every one of its containers in that
chooser as something to place.

These tests publish the character catalog through its own publish step,
``scripts/prepare_character_people.py``'s ``import_catalog``, into the test database and store,
and read the result through the routes a client uses. Migration 0101, which declares the kind of
every row that existed before it, has its own tests in
``tests/test_reviewed_asset_kind_migration.py``.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

import psycopg
import pytest
from exulanica.evidence.blob import BlobId
from exulanica.world.asset_import import import_reviewed_asset
from exulanica.world.asset_kinds import ASSET_KINDS, PLACEABLE_KINDS, AssetKind
from exulanica.world.assets import reviewed_assets
from exulanica.world.composition_preview import BLOCKED_REASONS
from exulanica.world.errors import AssetNotPlaceable

import test_world_objects_api as helpers
from test_reviewed_asset_import import imported_fixture

objects_api = helpers.objects_api
pytestmark = pytest.mark.postgres

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import prepare_character_people as people  # noqa: E402

MARKERS = {asset.asset_key for asset in reviewed_assets()}
CATALOG = json.loads((ROOT / "assets/characters/catalog.json").read_text())
CONTAINERS = {asset["assetKey"]: asset for asset in people.iter_assets(CATALOG)}
BODY = CONTAINERS["makehuman.people.feminine.base.v2"]


@pytest.fixture
def published_people(objects_api, repository):
    """The committed character catalog, published the way a deployment publishes it.

    ``world_reviewed_asset`` is preserved between tests, so every row this publishes is deleted
    on teardown, before the connection it writes through closes.
    """
    connection = repository.connection
    try:
        with connection.transaction():
            count = people.import_catalog(connection, objects_api.store, CATALOG)
        connection.commit()
        yield count
    finally:
        with connection.transaction():
            connection.execute(
                "delete from world_reviewed_asset where asset_key = any(%s)", (list(CONTAINERS),)
            )
        connection.commit()


def body(version, *, asset_key, subject_id="object:placed"):
    """A composition request placing one reviewed asset, as the object panel sends it."""
    return {
        "base_state_sha256": version["state_sha256"],
        "source": {"kind": "reviewed_asset", "asset_key": asset_key},
        "placement": {
            "subject_id": subject_id,
            "region_id": "region-a",
            "transform": helpers.transform(),
            "origin_role": "fictional",
        },
    }


def compose(api, version, step, request):
    return api.post(f"/world/versions/{version['version_id']}/compositions/{step}", request)


def read(api, version):
    response = api.get(f"/world/versions/{version['version_id']}")
    assert response.status_code == 200, response.text
    return response.json()


def test_the_listing_a_client_chooses_an_object_from_names_no_character_container(
    objects_api, published_people
):
    assert published_people == len(CONTAINERS) > 0
    # Positive control: the containers are published, present and served by key, which is how
    # the character renderer reaches them.
    for key in (next(iter(CONTAINERS)), sorted(CONTAINERS)[-1]):
        read_one = objects_api.get(f"/world/assets/{key}")
        assert read_one.status_code == 200, read_one.text
        assert read_one.json()["availability"] == "available"
        assert objects_api.get(f"/world/assets/{key}/bytes").status_code == 200

    listed = objects_api.get("/world/assets")
    assert listed.status_code == 200, listed.text
    keys = {row["asset_key"] for row in listed.json()}
    assert not keys & set(CONTAINERS), sorted(keys & set(CONTAINERS))[:5]
    assert keys == MARKERS
    assert {row["placeable"] for row in listed.json()} == {True}


def test_every_published_asset_carries_the_kind_its_catalog_declares(
    objects_api, repository, published_people
):
    """The parity between the stored kind and the catalogs that publish into the registry."""
    stored = {
        row["asset_key"]: row
        for row in repository.connection.execute(
            "select asset_key, content_sha256, kind from world_reviewed_asset"
        ).fetchall()
    }
    # The generated markers are objects, exactly as exulanica.world.assets declares them.
    for asset in reviewed_assets():
        row = stored[asset.asset_key]
        assert (row["content_sha256"], row["kind"]) == (asset.content_sha256, asset.kind.value)
        assert objects_api.get(f"/world/assets/{asset.asset_key}").json()["placeable"] is True
    # Every container the character catalog names is a component, and says so when read by key.
    for key, container in CONTAINERS.items():
        row = stored[key]
        assert (row["content_sha256"], row["kind"]) == (container["contentSha256"], "component")
        assert objects_api.get(f"/world/assets/{key}").json()["placeable"] is False
    assert set(stored) == MARKERS | set(CONTAINERS)


def test_the_schema_admits_exactly_the_registered_kinds(repository):
    connection = repository.connection
    definition = connection.execute(
        "select pg_get_constraintdef(oid) as text from pg_constraint "
        "where conname = 'world_reviewed_asset_kind_check'"
    ).fetchone()
    assert definition is not None, "no kind check on world_reviewed_asset"
    assert set(re.findall(r"'([a-z_]+)'", definition["text"])) == {kind.value for kind in AssetKind}
    assert set(ASSET_KINDS) == set(AssetKind)
    assert (
        {kind for kind, declared in ASSET_KINDS.items() if declared.placeable}
        == {AssetKind.OBJECT}
        == PLACEABLE_KINDS
    )

    def insert(kind):
        connection.execute(
            "insert into world_reviewed_asset (asset_key, title, summary, media_type, "
            "  content_sha256, byte_size, licence_id, licence_sha256, kind) values "
            "('test.kind-check', 'Kind check', 'Kind check', 'model/gltf-binary', %s, 1, "
            "  'CC0-1.0', %s, %s)",
            ("e" * 64, "f" * 64, kind),
        )

    # Positive control: a registered kind is accepted, so the refusals below are the kind's.
    with pytest.raises(RuntimeError, match="accepted"), connection.transaction():
        insert("component")
        raise RuntimeError("accepted, and rolled back")
    with pytest.raises(psycopg.errors.CheckViolation, match="kind"), connection.transaction():
        insert("prop")
    with pytest.raises(psycopg.errors.NotNullViolation, match="kind"), connection.transaction():
        insert(None)


def test_a_new_object_of_a_component_is_refused_by_name_on_every_route(
    objects_api, published_people
):
    version = objects_api.version()
    direct = objects_api.add(version, asset_sha256=BODY["contentSha256"])
    assert direct.status_code == 422, direct.text
    assert direct.json()["code"] == "invalid_object_data"
    assert direct.json()["detail"].startswith(
        f"{BODY['assetKey']} is not an object a person can place"
    )

    request = body(version, asset_key=BODY["assetKey"])
    verdict = compose(objects_api, version, "preview", request)
    assert verdict.status_code == 200, verdict.text
    assert verdict.json()["blocked_reason"] == "asset_not_placeable"
    assert BODY["assetKey"] in verdict.json()["blocked_detail"]
    applied = compose(objects_api, version, "apply", request)
    assert applied.status_code == 409, applied.text
    assert applied.json() == {"code": "composition_blocked", "detail": "asset_not_placeable"}
    assert read(objects_api, version) == version

    # Positive control: the same request naming an object composes, so the refusal is the kind's.
    marker = body(version, asset_key="cc0.marker-cube")
    assert compose(objects_api, version, "preview", marker).json()["blocked_reason"] is None
    assert objects_api.add(version, object_id="object:cube").status_code == 201


def test_a_component_is_refused_for_what_it_is_before_its_bytes_are_looked_at(
    objects_api, published_people
):
    """Restoring missing bytes is not the recovery for a component, so it is not the answer."""
    store = objects_api.store
    (store.root / store.key_for(BlobId.from_hex(BODY["contentSha256"]))).unlink()
    assert objects_api.get(f"/world/assets/{BODY['assetKey']}").json()["availability"] == (
        "unavailable_asset"
    )
    version = objects_api.version()
    direct = objects_api.add(version, asset_sha256=BODY["contentSha256"])
    assert (direct.status_code, direct.json()["code"]) == (422, "invalid_object_data")
    verdict = compose(objects_api, version, "preview", body(version, asset_key=BODY["assetKey"]))
    assert verdict.json()["blocked_reason"] == "asset_not_placeable"
    assert verdict.json()["source"]["bytes"] == "unavailable"


def test_a_component_refused_inside_a_write_keeps_its_own_code():
    """The exception table names the subclass before the class it refines."""
    from exulanica.world import composition_preview

    assert "asset_not_placeable" in BLOCKED_REASONS
    for table in (
        composition_preview._OBJECT_PLACEMENT_REFUSALS,
        composition_preview._OBJECT_WRITE_REFUSALS,
    ):
        assert composition_preview._reason(AssetNotPlaceable("x"), table) == ("asset_not_placeable")


def test_a_version_that_already_holds_a_component_keeps_it_and_keeps_editing(
    objects_api, repository
):
    """A component placed before kinds were declared is kept; only placing it again is refused.

    The asset is published as an object, placed, and then declared a component, which is the
    state migration 0101 leaves a version in when it declares the kind of a container that was
    already placed. Reading, composing, an unrelated addition, and moving, removing and undoing the
    held object all behave as before.
    """
    connection = repository.connection
    manifest, payload, licence = imported_fixture()
    payload = payload.replace(b"exulanica-reviewed-asset/1", b"exulanica-reviewed-asset/3")
    manifest = manifest.model_copy(
        update={
            "asset_key": "test.placed-before-kinds",
            "content_sha256": hashlib.sha256(payload).hexdigest(),
        }
    )
    with connection.transaction():
        import_reviewed_asset(
            connection, objects_api.store, manifest, payload, licence, kind=AssetKind.OBJECT
        )
    try:
        version = objects_api.add(
            objects_api.version(), object_id="object:held", asset_sha256=manifest.content_sha256
        ).json()
        with connection.transaction():
            connection.execute(
                "update world_reviewed_asset set kind = 'component' where asset_key = %s",
                (manifest.asset_key,),
            )

        held = read(objects_api, version)
        assert held["state_sha256"] == version["state_sha256"]
        [kept] = held["objects"]
        assert kept["object_id"] == "object:held"
        assert kept["asset"]["placeable"] is False
        assert kept["asset"]["availability"] == "available"
        assert manifest.asset_key not in {
            row["asset_key"] for row in objects_api.get("/world/assets").json()
        }

        ready = compose(objects_api, held, "preview", body(held, asset_key="cc0.marker-cube"))
        assert ready.json()["availability"] == "ready", ready.text
        added = objects_api.add(held, object_id="object:cube")
        assert added.status_code == 201, added.text

        path = f"/world/versions/{version['version_id']}/objects/object:held"
        moved = objects_api.post(
            f"{path}/move",
            {
                "base_state_sha256": added.json()["state_sha256"],
                "transform": helpers.transform(x_mm=99),
            },
        )
        assert moved.status_code == 200, moved.text
        removed = objects_api.post(
            f"{path}/remove", {"base_state_sha256": moved.json()["state_sha256"]}
        )
        assert removed.status_code == 200, removed.text
        undone = objects_api.post(
            f"/world/versions/{version['version_id']}/objects/undo",
            {"base_state_sha256": removed.json()["state_sha256"]},
        )
        assert undone.status_code == 200, undone.text
        restored = {obj["object_id"]: obj for obj in undone.json()["objects"]}
        assert restored["object:held"]["removed"] is False
        assert restored["object:held"]["transform"]["x_mm"] == 99

        # What is refused is placing it again, by name, on both routes.
        again = objects_api.add(
            undone.json(), object_id="object:again", asset_sha256=manifest.content_sha256
        )
        assert again.status_code == 422, again.text
        assert manifest.asset_key in again.json()["detail"]
        refused = compose(
            objects_api,
            undone.json(),
            "preview",
            body(undone.json(), asset_key=manifest.asset_key, subject_id="object:again"),
        )
        assert refused.json()["blocked_reason"] == "asset_not_placeable"
    finally:
        with connection.transaction():
            connection.execute(
                "delete from world_alternate_object where asset_sha256 = %s",
                (manifest.content_sha256,),
            )
            connection.execute(
                "delete from world_reviewed_asset where asset_key = %s", (manifest.asset_key,)
            )


def test_nothing_this_file_published_is_left_in_the_reviewed_registry(repository):
    """The registry is preserved between tests, so a leak here would be another file's failure.

    Source order puts this after every test that publishes, so a leak fails in this file.
    """
    published = [*CONTAINERS, "test.placed-before-kinds", "test.kind-check"]
    left = repository.connection.execute(
        "select asset_key from world_reviewed_asset where asset_key = any(%s)", (published,)
    ).fetchall()
    assert [row["asset_key"] for row in left] == []
