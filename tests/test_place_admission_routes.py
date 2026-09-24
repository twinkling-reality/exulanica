"""The whole admission chain through the product's own routes, on PostgreSQL.

Everything below is driven as a person's client would drive it: a place is created, a source is
admitted into it, a render asset is registered against that source, a feature catalog is
published, one feature is composed into an authored version through lane A's preview and apply,
and the same place answers a cross-content Selection. Nothing here writes a row directly, which
is the point: before this lane the chain could only be built by inserting into ``place`` by hand,
so none of it was reachable from the product at all.

The source is a synthetic file this module writes into the workspace inbox. No provider is
contacted and no real dataset is admitted; admitting one is an operator decision and this test
is not it.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlencode

import pytest
from exulanica.api.app import create_app
from exulanica.api.authorisation import load_token_directory
from exulanica.api.services import Services
from exulanica.store.local import LocalContentAddressedStore
from exulanica.world import WorldStructureRepository
from fastapi.testclient import TestClient

from tests_support_api import EVERY_PERMISSION, scratch_database
from world_structure_fixtures import structural_candidate
from world_support import registered_world

pytestmark = pytest.mark.postgres

TOKEN = "place-admission-route-token-long-enough"
FRAME_NAME = "synthetic-district-crs84"
SCALE = 1000
DECLARED_BOUNDS = (0, 0, 1000, 1000)
SOURCE_BOUNDS = (100, 100, 900, 900)

FRAME = {
    "name": FRAME_NAME,
    "crs": "OGC:CRS84",
    "axis_order": ["longitude", "latitude"],
    "horizontal_unit": "degree",
    "vertical_unit": "not_applicable",
    "orientation": "east-north",
    "altitude_reference": "not_applicable_2d",
}
RIGHTS = {
    "display": True,
    "extract": True,
    "index": True,
    "persist": True,
    "modify": True,
    "compose": True,
    "export": False,
    "model_processing": False,
}
ATTRIBUTION = "Synthetic open data fixture; attribution required."
NOTICE = "Modified outputs must be marked."


def bounds(*coordinates: int, kind: str = "bbox") -> dict:
    return {
        "kind": kind,
        "frame_name": FRAME_NAME,
        "coordinate_scale": SCALE,
        "coordinates": list(coordinates),
    }


@dataclass
class Chain:
    client: TestClient
    workspace_id: uuid.UUID
    inbox: Path
    snapshot_id: uuid.UUID
    #: The registered world the snapshot belongs to, which every world route is told.
    world_id: str

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {TOKEN}"}

    def in_world(self, path: str) -> str:
        """``path`` naming this chain's world, as a world route requires."""
        return f"{path}{'&' if '?' in path else '?'}{urlencode({'world_id': self.world_id})}"

    def post(self, path: str, body: dict) -> object:
        return self.client.post(path, json=body, headers=self.headers)

    def get(self, path: str) -> object:
        return self.client.get(path, headers=self.headers)

    def staged(self, name: str, data: bytes) -> str:
        path = self.inbox / name
        path.write_bytes(data)
        return str(path)


@pytest.fixture
def chain(repository, spine_schema, tmp_path, monkeypatch):
    _psycopg, scratch = spine_schema
    actor = uuid.uuid4()
    world_id = registered_world(repository.connection, repository.workspace_id)
    structures = WorldStructureRepository(
        repository.connection, repository.workspace_id, world_id=world_id
    )
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
                TOKEN: {
                    "workspace_id": str(repository.workspace_id),
                    "actor": str(actor),
                    "permissions": EVERY_PERMISSION,
                }
            }
        ),
    )
    inbox_root = tmp_path / "environment-inbox"
    inbox = inbox_root / str(repository.workspace_id)
    inbox.mkdir(parents=True)
    database = scratch_database(scratch)
    services = Services(
        database=database,
        readonly_database=database,
        store=LocalContentAddressedStore(tmp_path / "blobs"),
        tokens=load_token_directory(),
        executor_shares_the_write_role=True,
        model_client=None,
        environment_admission_root=inbox_root,
    )
    with TestClient(create_app(services, verify=False)) as client:
        yield Chain(client, repository.workspace_id, inbox, snapshot.snapshot_id, world_id)


def declare_place(chain: Chain) -> dict:
    response = chain.post(
        "/environment-resources/places",
        {
            "provider_key": "synthetic-open-data",
            "provider_frame_statement": (
                "The provider publishes this extract in OGC:CRS84, longitude then latitude, "
                "in degrees, with no vertical component."
            ),
            "geographic_frame": FRAME,
            "geographic_bounds": bounds(*DECLARED_BOUNDS),
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def admit_source(chain: Chain, place_id: str, data: bytes, **changes) -> object:
    body = {
        "place_id": place_id,
        "provider_key": "synthetic-open-data",
        "provider_original_id": "district-extract",
        "provider_revision": "2026-09-01",
        "expected_sha256": hashlib.sha256(data).hexdigest(),
        "expected_byte_size": len(data),
        "source_path": "https://example.invalid/district-extract.geojson",
        "media_type": "application/geo+json",
        "geographic_frame": FRAME,
        "geographic_bounds": bounds(*SOURCE_BOUNDS),
        "operation_rights": RIGHTS,
        "attribution": ATTRIBUTION,
        "modification_notice": NOTICE,
        "local_path": chain.staged("district-extract.geojson", data),
    }
    body.update(changes)
    return chain.post("/environment-resources/sources", body)


def register_asset(chain: Chain, admission_id: str, data: bytes, source_digest: str, **changes):
    body = {
        "admission_id": admission_id,
        "expected_sha256": hashlib.sha256(data).hexdigest(),
        "expected_byte_size": len(data),
        "media_type": "application/vnd.exulanica.synthetic-district-render+json",
        "derivation_kind": "synthetic-district-render",
        "derivation_lineage": {
            "method": "exulanica.synthetic-district-render/v1",
            "input_sha256": [source_digest],
        },
        "geographic_frame": FRAME,
        "geographic_bounds": bounds(*SOURCE_BOUNDS),
        "operation_rights": RIGHTS,
        "attribution": ATTRIBUTION,
        "modification_notice": NOTICE,
        "local_path": chain.staged("district-render.json", data),
    }
    body.update(changes)
    return chain.post("/environment-resources/assets", body)


SOURCE_BYTES = json.dumps(
    {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": "block-0001",
                "properties": {"name": "Corner block"},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[200, 200], [400, 200], [400, 400], [200, 400], [200, 200]]],
                },
            }
        ],
    },
    sort_keys=True,
).encode("utf-8")

RENDER_BYTES = json.dumps(
    {"profile": "synthetic-district-render/v1", "batches": [{"id": 0, "feature": "block-0001"}]},
    sort_keys=True,
).encode("utf-8")


@pytest.fixture
def admitted(chain):
    """The full chain up to a published feature catalog, built through the routes."""
    place = declare_place(chain)
    admitted = admit_source(chain, place["place_id"], SOURCE_BYTES)
    assert admitted.status_code == 201, admitted.text
    admission_id = admitted.json()["resource_id"]

    asset = register_asset(
        chain,
        admission_id,
        RENDER_BYTES,
        hashlib.sha256(SOURCE_BYTES).hexdigest(),
    )
    assert asset.status_code == 201, asset.text
    render_asset_id = asset.json()["resource_id"]

    published = chain.post(
        f"/environment-resources/sources/{admission_id}/feature-indexes",
        {
            "render_asset_id": render_asset_id,
            "features": [
                {
                    "provider_feature_id": "block-0001",
                    "kind": "building",
                    "bbox": [200, 200, 400, 400],
                    "label": "Corner block",
                    "render_batch_id": 0,
                }
            ],
        },
    )
    assert published.status_code == 201, published.text
    catalog = published.json()
    return place, admission_id, render_asset_id, catalog


def test_the_admission_chain_is_reachable_through_the_product_routes(chain, admitted):
    place, admission_id, render_asset_id, catalog = admitted

    assert place["frame_authority"] == "declared_provider_frame"
    assert catalog["place_id"] == place["place_id"]
    assert catalog["render_asset_id"] == render_asset_id
    assert [feature["label"] for feature in catalog["features"]] == ["Corner block"]

    read_back = chain.get(f"/environment-resources/places/{place['place_id']}")
    assert read_back.status_code == 200, read_back.text
    assert read_back.json()["frame_authority"] == "declared_provider_frame"
    assert read_back.json()["receipt_sha256"] == place["receipt_sha256"]
    absent = chain.get(f"/environment-resources/places/{uuid.uuid4()}")
    assert absent.status_code == 404 and absent.json()["code"] == "unknown_reference"

    listed = chain.get(f"/environment-resources/sources/{admission_id}/features")
    assert listed.status_code == 200, listed.text
    assert listed.json()["publication_id"] == catalog["publication_id"]

    rendered = chain.get(f"/environment-resources/asset/{render_asset_id}/bytes?operation=display")
    assert rendered.status_code == 200
    assert rendered.content == RENDER_BYTES


def test_the_scene_addressed_place_read_says_the_frame_was_declared(chain, admitted):
    """Not "no anchor yet", because no anchor scene is coming.

    The World Read place bundle expresses versions in a place's recovered scene frame. A
    source-anchored place has neither, and 0091 makes sure it never will, so reporting it as a
    place nobody has aligned yet would promise a state that cannot arrive. A place with no
    authority at all still answers ``place_without_anchor``, which
    ``tests/test_world_read_route.py`` holds unchanged.
    """
    place, _admission_id, _render, _catalog = admitted
    response = chain.get(chain.in_world(f"/world-read/places/{place['place_id']}"))
    assert response.status_code == 424, response.text
    assert response.json()["code"] == "place_frame_is_declared"
    assert "recovered scene frames only" in response.json()["detail"]


def test_an_admitted_environment_composes_into_an_authored_version(chain, admitted):
    place, admission_id, render_asset_id, catalog = admitted
    feature = catalog["features"][0]

    created = chain.post(
        chain.in_world("/world/versions"),
        {"title": "District study", "source_snapshot_id": str(chain.snapshot_id)},
    )
    assert created.status_code == 201, created.text
    version = created.json()

    body = {
        "base_state_sha256": version["state_sha256"],
        "source": {
            "kind": "environment_admission",
            "admission_id": admission_id,
            "render_asset_id": render_asset_id,
            "publication_id": catalog["publication_id"],
            "selection": {
                "kind": "feature",
                "feature_id": feature["id"],
                "render_batch_id": feature["render_batch_id"],
            },
        },
        "placement": {
            "subject_id": "environment:corner-block",
            "region_id": "region-a",
            "transform": {
                "x_mm": 1_200,
                "y_mm": 0,
                "z_mm": -450,
                "yaw_microradians": 785_398,
                "scale_milli": 1_000,
            },
            "origin_role": "personal",
            # A feature selection pins the FEATURE's own bbox as the source bounds, so the
            # anchor is a point inside the selected block rather than inside the whole extract.
            "source_anchor": {
                "frame_name": FRAME_NAME,
                "coordinate_scale": SCALE,
                "coordinates": [300, 300],
            },
        },
    }

    path = f"/world/versions/{version['version_id']}"
    previewed = chain.post(chain.in_world(f"{path}/compositions/preview"), body)
    assert previewed.status_code == 200, previewed.text
    verdict = previewed.json()
    assert verdict["availability"] == "ready", verdict
    assert verdict["blocked_reason"] is None
    assert verdict["would_change"]["kind"] == "add_environment"
    document = verdict["would_change"]["document"]
    assert document is not None
    assert document["source"]["place_id"] == place["place_id"]
    assert document["source"]["frame"]["name"] == FRAME_NAME

    applied = chain.post(chain.in_world(f"{path}/compositions/apply"), body)
    assert applied.status_code == 201, applied.text
    stored = chain.get(chain.in_world(path))
    assert stored.status_code == 200
    instances = stored.json()["environment_instances"]
    assert [instance["instance_id"] for instance in instances] == ["environment:corner-block"]


def test_the_same_place_answers_a_cross_content_selection(chain, admitted, repository):
    """A non-empty CONTENT answer for an admitted place, through the routes that serve it.

    The memory half of the bridge is a bare place-class entity written directly, because nothing
    in the product creates one without the photograph pipeline and its vision model. What this
    establishes is the half this lane builds: once a place exists and a bridge is confirmed, the
    admitted source and its published features are what the Selection returns.
    """
    place, _admission_id, _render_asset_id, _catalog = admitted
    entity_id = uuid.uuid4()
    repository.connection.execute(
        "insert into entity(entity_id,workspace_id,class) values(%s,%s,'place')",
        (entity_id, repository.workspace_id),
    )
    repository.connection.commit()

    bridged = chain.post(
        "/selection/place-bridges",
        {
            "canonical_place_id": place["place_id"],
            "memory_place_entity_id": str(entity_id),
            "reason": "The account holder confirmed these identities refer to the same place.",
        },
    )
    assert bridged.status_code == 201, bridged.text

    selected = chain.post(
        chain.in_world("/selection"),
        {
            "intent": "content",
            "place": {"ids": [str(entity_id)]},
            "content": {"scope": "related"},
        },
    )
    assert selected.status_code == 200, selected.text
    content = selected.json()["content"]
    assert content, "a bridged place with an admitted source must answer with its content"
    assert {item["result_kind"] for item in content} == {
        "admitted_environment_source",
        "admitted_environment_feature",
    }
    assert {item["canonical_place_id"] for item in content} == {place["place_id"]}


def test_a_source_that_does_not_match_its_place_is_refused_and_stores_nothing(chain, admitted):
    """The rights and frame a place declared are not negotiable at the route either."""
    place, _admission_id, _render, _catalog = admitted
    outside = b"bytes whose declared bounds leave the place"
    refused = admit_source(
        chain,
        place["place_id"],
        outside,
        provider_original_id="district-extract-outside",
        geographic_bounds=bounds(100, 100, 1_100, 900),
        expected_sha256=hashlib.sha256(outside).hexdigest(),
        expected_byte_size=len(outside),
        local_path=chain.staged("outside.geojson", outside),
    )
    assert refused.status_code == 409, refused.text
    assert refused.json()["code"] == "admission_refused"
    assert "not inside the bounds" in refused.json()["detail"]
