"""The HTTP contract for alternate versions, authored objects, and the reviewed asset registry.

The full add, move, remove and undo cycle runs over the wire here, and every problem code has a
test that produces it. Each invariant carries the negative control that fails if its guard is
removed.
"""

from __future__ import annotations

import itertools
import json
import uuid
from dataclasses import dataclass

import pytest
from exulanica.api.app import create_app
from exulanica.api.authorisation import load_token_directory
from exulanica.api.services import Services
from exulanica.store.local import LocalContentAddressedStore
from exulanica.world import (
    GLB_MEDIA_TYPE,
    WorldStructureRepository,
    reviewed_assets,
    seed_reviewed_assets,
)
from fastapi.testclient import TestClient

from world_structure_fixtures import structural_candidate

pytestmark = pytest.mark.postgres

TOKEN = "objects-owner-token-long-enough-for-tests"
STRANGER_TOKEN = "objects-stranger-token-long-enough-for-tests"

PARAMETERS = {
    "travel_mm": 2_000,
    "period_milliseconds": 4_000,
    "axis": "x",
    "easing": "smooth",
}


def transform(**overrides):
    values = {
        "x_mm": 1_200,
        "y_mm": 0,
        "z_mm": -450,
        "yaw_microradians": 785_398,
        "scale_milli": 1_000,
    }
    values.update(overrides)
    return values


@dataclass
class ObjectsApi:
    client: TestClient
    snapshot_id: uuid.UUID
    actor: uuid.UUID
    store: LocalContentAddressedStore

    @property
    def headers(self):
        return {"Authorization": f"Bearer {TOKEN}"}

    def get(self, path):
        return self.client.get(path, headers=self.headers)

    def post(self, path, body):
        return self.client.post(path, headers=self.headers, json=body)

    def stranger_get(self, path):
        return self.client.get(path, headers={"Authorization": f"Bearer {STRANGER_TOKEN}"})

    def stranger_post(self, path, body):
        return self.client.post(
            path, headers={"Authorization": f"Bearer {STRANGER_TOKEN}"}, json=body
        )

    def version(self, title="Lantern study"):
        response = self.post(
            "/world/versions", {"title": title, "source_snapshot_id": str(self.snapshot_id)}
        )
        assert response.status_code == 201, response.text
        return response.json()

    def add(self, version, **overrides):
        body = {
            "base_state_sha256": version["state_sha256"],
            "object_id": "object:lantern",
            "asset_key": "cc0.marker-cube",
            "region_id": "region-a",
            "transform": transform(),
            "origin_role": "fictional",
        }
        body.update(overrides)
        return self.post(f"/world/versions/{version['version_id']}/objects", body)


@pytest.fixture
def objects_api(repository, spine_schema, tmp_path, monkeypatch):
    _psycopg, scratch = spine_schema
    actor, stranger = uuid.uuid4(), uuid.uuid4()

    structures = WorldStructureRepository(repository.connection, repository.workspace_id)
    preview = structures.preview(structural_candidate(), proposed_by=actor)
    snapshot = structures.apply(
        preview.preview_id,
        base_snapshot_id=preview.base_snapshot_id,
        base_graph_sha256=preview.base_graph_sha256,
        base_reconstruction_sha256=preview.base_reconstruction_sha256,
        committed_by=actor,
    )
    repository.connection.commit()

    monkeypatch.setenv(
        "EXULANICA_API_TOKENS",
        json.dumps(
            {
                TOKEN: {"workspace_id": str(repository.workspace_id), "actor": str(actor)},
                STRANGER_TOKEN: {"workspace_id": str(stranger), "actor": str(uuid.uuid4())},
            }
        ),
    )
    from tests_support_api import scratch_database

    store = LocalContentAddressedStore(tmp_path / "blobs")
    seed_reviewed_assets(store)
    database = scratch_database(scratch)
    services = Services(
        database=database,
        readonly_database=database,
        store=store,
        tokens=load_token_directory(),
        executor_shares_the_write_role=True,
        model_client=None,
    )
    with TestClient(create_app(services, verify=False)) as client:
        yield ObjectsApi(client, snapshot.snapshot_id, actor, store)


# -- the reviewed asset registry ------------------------------------------------------------


def test_the_registry_lists_three_reviewed_cc0_assets_with_their_licence(objects_api):
    response = objects_api.get("/world/assets")
    assert response.status_code == 200
    catalog = {asset["asset_key"]: asset for asset in response.json()}
    assert set(catalog) == {"cc0.marker-cube", "cc0.marker-pillar", "cc0.marker-plate"}
    for asset in catalog.values():
        assert asset["licence_id"] == "CC0-1.0"
        assert asset["media_type"] == GLB_MEDIA_TYPE
        assert asset["availability"] == "available"
        assert len(asset["content_sha256"]) == 64
        assert len(asset["licence_sha256"]) == 64


def test_the_registry_serves_the_exact_bytes_it_names(objects_api):
    generated = {asset.asset_key: asset for asset in reviewed_assets()}
    for key, asset in generated.items():
        response = objects_api.get(f"/world/assets/{key}/bytes")
        assert response.status_code == 200
        assert response.content == asset.payload
        assert response.headers["content-type"] == GLB_MEDIA_TYPE
        assert response.headers["etag"] == f'"{asset.content_sha256}"'
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["accept-ranges"] == "none"
        assert response.content[:4] == b"glTF"


def test_the_licence_text_is_served_beside_the_bytes(objects_api):
    response = objects_api.get("/world/assets/cc0.marker-cube/licence")
    assert response.status_code == 200
    assert "CC0 1.0 Universal" in response.text
    assert "creativecommons.org/publicdomain/zero/1.0" in response.text


def test_the_registry_is_read_only(objects_api):
    """The negative control for "exposed read-only": there is no way in through this surface."""
    for method, path in (
        ("POST", "/world/assets"),
        ("PUT", "/world/assets/cc0.marker-cube"),
        ("DELETE", "/world/assets/cc0.marker-cube"),
        ("PATCH", "/world/assets/cc0.marker-cube"),
        ("DELETE", "/world/assets/cc0.marker-cube/bytes"),
    ):
        response = objects_api.client.request(method, path, headers=objects_api.headers)
        assert response.status_code == 405, (method, path, response.status_code)


def test_an_asset_whose_bytes_are_missing_reports_the_state_and_serves_no_substitute(
    objects_api, tmp_path
):
    """A reviewed row with no bytes is `unavailable_asset`, never a different mesh."""
    for path in (tmp_path / "blobs").rglob("*"):
        if path.is_file():
            path.unlink()
    listed = {a["asset_key"]: a for a in objects_api.get("/world/assets").json()}
    assert {a["availability"] for a in listed.values()} == {"unavailable_asset"}
    response = objects_api.get("/world/assets/cc0.marker-cube/bytes")
    assert response.status_code == 424
    assert response.json()["code"] == "unavailable_asset"
    assert not response.content.startswith(b"glTF")


def test_an_unknown_asset_is_an_unknown_reference(objects_api):
    for path in ("/world/assets/cc0.invented", "/world/assets/cc0.invented/bytes"):
        response = objects_api.get(path)
        assert response.status_code == 404
        assert response.json()["code"] == "unknown_reference"


# -- versions ---------------------------------------------------------------------------------


def test_a_version_is_created_read_and_listed(objects_api):
    created = objects_api.version()
    assert created["schema_version"] == 1
    assert created["origin"] == "authored"
    assert created["source_snapshot_id"] == str(objects_api.snapshot_id)
    assert created["parent_version_id"] is None
    assert created["edit_seq"] == 0
    assert created["objects"] == []
    assert created["source_invalidated"] is False
    assert created["created_by"] == str(objects_api.actor)

    read = objects_api.get(f"/world/versions/{created['version_id']}")
    assert read.status_code == 200
    assert read.json() == created

    listed = objects_api.get("/world/versions")
    assert listed.status_code == 200
    assert [v["version_id"] for v in listed.json()] == [created["version_id"]]


def test_a_version_can_branch_from_another_version(objects_api):
    parent = objects_api.version("Parent")
    parent = objects_api.add(parent).json()
    response = objects_api.post(
        "/world/versions", {"title": "Child", "parent_version_id": parent["version_id"]}
    )
    assert response.status_code == 201
    child = response.json()
    assert child["parent_version_id"] == parent["version_id"]
    assert child["source_snapshot_id"] == parent["source_snapshot_id"]
    assert [o["object_id"] for o in child["objects"]] == ["object:lantern"]


def test_a_version_naming_no_source_is_refused(objects_api):
    response = objects_api.post("/world/versions", {"title": "Nowhere"})
    assert response.status_code == 422
    assert response.json()["code"] == "invalid_object_data"


def test_an_unknown_source_snapshot_is_an_unknown_reference(objects_api):
    response = objects_api.post(
        "/world/versions", {"title": "Nowhere", "source_snapshot_id": str(uuid.uuid4())}
    )
    assert response.status_code == 404
    assert response.json()["code"] == "unknown_reference"


# -- the full add, move, remove, undo cycle ------------------------------------------------------


def test_the_whole_authored_object_cycle_over_http(objects_api):
    version = objects_api.version()

    added = objects_api.add(
        version,
        behaviour={
            "behaviour_key": "motion.bounded-path",
            "behaviour_version": 1,
            "parameters": PARAMETERS,
        },
    )
    assert added.status_code == 201, added.text
    version = added.json()
    assert version["edit_seq"] == 1
    obj = version["objects"][0]
    assert obj["object_id"] == "object:lantern"
    assert obj["removed"] is False
    assert obj["origin"] == {"kind": "authored", "role": "fictional"}
    assert obj["region_id"] == "region-a"
    assert obj["transform"]["coordinate_space"] == "region_local"
    assert obj["transform"]["coordinate_unit"] == "millimetre"
    assert obj["transform"]["x_mm"] == 1_200
    assert obj["behaviour"]["behaviour_key"] == "motion.bounded-path"
    assert obj["behaviour"]["parameters"] == PARAMETERS
    # The renderer is told what it may draw without a second call.
    assert obj["asset"]["asset_key"] == "cc0.marker-cube"
    assert obj["asset"]["availability"] == "available"
    assert obj["asset"]["licence_id"] == "CC0-1.0"

    moved = objects_api.post(
        f"/world/versions/{version['version_id']}/objects/object:lantern/move",
        {"base_state_sha256": version["state_sha256"], "transform": transform(x_mm=2_400)},
    )
    assert moved.status_code == 200, moved.text
    version = moved.json()
    assert version["objects"][0]["transform"]["x_mm"] == 2_400
    assert version["edit_seq"] == 2
    placed = version["state_sha256"]

    removed = objects_api.post(
        f"/world/versions/{version['version_id']}/objects/object:lantern/remove",
        {"base_state_sha256": version["state_sha256"]},
    )
    assert removed.status_code == 200, removed.text
    version = removed.json()
    assert version["objects"][0]["removed"] is True
    assert version["edit_seq"] == 3

    undone = objects_api.post(
        f"/world/versions/{version['version_id']}/objects/undo",
        {"base_state_sha256": version["state_sha256"]},
    )
    assert undone.status_code == 200, undone.text
    version = undone.json()
    assert version["objects"][0]["removed"] is False
    # Undo returns the delta to the exact state before the removal, digest included.
    assert version["state_sha256"] == placed
    assert version["objects"][0]["behaviour"]["parameters"] == PARAMETERS
    assert [e["kind"] for e in version["edits"]] == [
        "add_object",
        "move_object",
        "remove_object",
        "undo",
    ]
    # Every edit recorded the base it was made against, and the chain is checkable.
    for earlier, later in itertools.pairwise(version["edits"]):
        assert earlier["result_state_sha256"] == later["base_state_sha256"]
        assert later["actor"] == str(objects_api.actor)

    # And it survives a fresh read, which is what "operates on persisted state" means.
    reread = objects_api.get(f"/world/versions/{version['version_id']}").json()
    assert reread == version


# -- problem codes ------------------------------------------------------------------------------


def test_an_edit_against_a_stale_base_is_a_named_conflict(objects_api):
    version = objects_api.version()
    stale = version["state_sha256"]
    objects_api.add(version)
    response = objects_api.add(
        {"version_id": version["version_id"], "state_sha256": stale}, object_id="object:second"
    )
    assert response.status_code == 409
    assert response.json()["code"] == "stale_object_base"
    current = objects_api.get(f"/world/versions/{version['version_id']}").json()
    assert [o["object_id"] for o in current["objects"]] == ["object:lantern"]


def test_undoing_nothing_is_an_invalid_state(objects_api):
    version = objects_api.version()
    response = objects_api.post(
        f"/world/versions/{version['version_id']}/objects/undo",
        {"base_state_sha256": version["state_sha256"]},
    )
    assert response.status_code == 409
    assert response.json()["code"] == "invalid_object_state"


def test_adding_the_same_object_id_twice_is_an_invalid_state(objects_api):
    version = objects_api.version()
    version = objects_api.add(version).json()
    response = objects_api.add(version)
    assert response.status_code == 409
    assert response.json()["code"] == "invalid_object_state"


def test_an_unreviewed_asset_or_unknown_region_is_invalid_object_data(objects_api):
    version = objects_api.version()
    for overrides in ({"asset_key": "something.downloaded"}, {"region_id": "region-nowhere"}):
        response = objects_api.add(version, **overrides)
        assert response.status_code == 422, overrides
        assert response.json()["code"] == "invalid_object_data"


def test_an_unsupported_behaviour_fails_visibly(objects_api):
    """The first milestone names this as its own acceptance evidence."""
    version = objects_api.version()
    for behaviour in (
        {"behaviour_key": "motion.teleport", "behaviour_version": 1, "parameters": PARAMETERS},
        {"behaviour_key": "motion.bounded-path", "behaviour_version": 9, "parameters": PARAMETERS},
        {
            "behaviour_key": "motion.bounded-path",
            "behaviour_version": 1,
            "parameters": {**PARAMETERS, "travel_mm": 10_001},
        },
        {
            "behaviour_key": "motion.bounded-path",
            "behaviour_version": 1,
            "parameters": {**PARAMETERS, "axis": "w"},
        },
    ):
        response = objects_api.add(version, behaviour=behaviour)
        assert response.status_code == 422, behaviour
        assert response.json()["code"] == "invalid_object_data"


def test_the_transport_refuses_a_float_coordinate_before_the_digest_does(objects_api):
    version = objects_api.version()
    response = objects_api.add(version, transform=transform(x_mm=1_200.5))
    assert response.status_code == 422


def test_an_unchosen_origin_role_is_refused(objects_api):
    """No default and no inference: the person chooses, or there is no object."""
    version = objects_api.version()
    assert objects_api.add(version, origin_role="unknown").status_code == 422
    body = {
        "base_state_sha256": version["state_sha256"],
        "object_id": "object:lantern",
        "asset_key": "cc0.marker-cube",
        "region_id": "region-a",
        "transform": transform(),
    }
    assert (
        objects_api.post(f"/world/versions/{version['version_id']}/objects", body).status_code
        == 422
    )


@pytest.mark.parametrize(
    "object_id",
    ["Object:Lantern", "object lantern", "-lead", "trail-", "\u043e\u0431\u044a\u0435\u043a\u0442"],
)
def test_an_object_id_the_schema_refuses_answers_422_and_not_500(objects_api, object_id):
    """A regression. These ids passed Python validation and then violated the schema's CHECK, so
    the caller received a 500 from the integrity handler instead of the documented
    invalid_object_data. The contract now lives in one regex that both sides quote."""
    version = objects_api.version()
    response = objects_api.add(version, object_id=object_id)
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "invalid_object_data"


def test_a_single_character_object_id_is_accepted_end_to_end(objects_api):
    """The other half of the same fix: the schema used to require two characters."""
    version = objects_api.version()
    response = objects_api.add(version, object_id="a")
    assert response.status_code == 201, response.text
    assert [o["object_id"] for o in response.json()["objects"]] == ["a"]


def test_an_unknown_field_in_a_body_is_refused(objects_api):
    version = objects_api.version()
    assert objects_api.add(version, origin_kind="captured").status_code == 422


def test_an_unknown_version_or_object_is_an_unknown_reference(objects_api):
    version = objects_api.version()
    missing = objects_api.post(
        f"/world/versions/{uuid.uuid4()}/objects/undo",
        {"base_state_sha256": version["state_sha256"]},
    )
    assert missing.status_code == 404
    assert missing.json()["code"] == "unknown_reference"

    version = objects_api.add(version).json()
    response = objects_api.post(
        f"/world/versions/{version['version_id']}/objects/object:absent/move",
        {"base_state_sha256": version["state_sha256"], "transform": transform()},
    )
    assert response.status_code == 404
    assert response.json()["code"] == "unknown_reference"


# -- authorisation and isolation -----------------------------------------------------------------


def test_every_route_requires_a_bearer_token(objects_api):
    version = objects_api.version()
    unauthenticated = [
        objects_api.client.get("/world/versions"),
        objects_api.client.get("/world/assets"),
        objects_api.client.get("/world/assets/cc0.marker-cube/bytes"),
        objects_api.client.post("/world/versions", json={"title": "x"}),
        objects_api.client.post(
            f"/world/versions/{version['version_id']}/objects/undo",
            json={"base_state_sha256": version["state_sha256"]},
        ),
    ]
    for response in unauthenticated:
        assert response.status_code in {401, 403}, response.request.url


def test_another_workspace_cannot_see_or_edit_a_version(objects_api):
    version = objects_api.add(objects_api.version()).json()

    assert objects_api.stranger_get("/world/versions").json() == []
    read = objects_api.stranger_get(f"/world/versions/{version['version_id']}")
    assert read.status_code == 404
    assert read.json()["code"] == "unknown_reference"
    # Identical to a version that never existed, so nothing leaks by comparison.
    assert objects_api.stranger_get(f"/world/versions/{uuid.uuid4()}").json() == read.json()

    written = objects_api.stranger_post(
        f"/world/versions/{version['version_id']}/objects/object:lantern/remove",
        {"base_state_sha256": version["state_sha256"]},
    )
    assert written.status_code == 404
    assert (
        objects_api.get(f"/world/versions/{version['version_id']}").json()["objects"][0]["removed"]
        is False
    )


def test_the_reviewed_catalog_is_shared_because_it_is_not_tenant_data(objects_api):
    """The negative control for isolation: reviewed CC0 geometry is global on purpose, and
    reading it from another workspace is correct rather than a leak."""
    mine = objects_api.get("/world/assets").json()
    theirs = objects_api.stranger_get("/world/assets").json()
    assert mine == theirs
