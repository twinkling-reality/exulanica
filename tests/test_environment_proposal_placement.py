"""The placement an environment proposal describes: the building's id, its anchor, and the request.

``POST /selection/environment`` proposes placing the NYC Open Data building a person selected. The
proposal names the instance by the building's DOITT id, anchors it at the centre of the building's
admitted bounding box, and carries the region, transform and origin the request gave, each field
in its own place. ``tests/test_world_environment_composition_postgres.py`` holds the proposal's
source fields; the route test here holds the rest of the document for the fixture building there,
``doitt_id:1`` with the box (0, 0, 0) to (100, 100, 100), and the tests with no database hold the
anchor's rounding and the placement's fields for boxes that fixture does not have.
"""

from __future__ import annotations

import json
import uuid

import pytest
from exulanica.api.app import create_app
from exulanica.api.authorisation import load_token_directory
from exulanica.api.services import Services
from exulanica.environment import EnvironmentFeatureCatalog
from exulanica.environment.feature_placement import nyc_instance_id, selected_feature_placement
from exulanica.models.budget import BudgetGuard
from exulanica.models.client import ModelClient
from exulanica.models.transport import HttpResponse
from fastapi.testclient import TestClient

from conftest import TEST_CEILING_USD, TEST_MAX_CALLS
from model_fakes import FakeTransport, chat_body
from test_world_environment_composition_postgres import composed
from tests_support_api import EVERY_PERMISSION, scratch_database

__all__ = ["composed"]

TRANSFORM = {"x_mm": 10, "y_mm": 5, "z_mm": 20, "yaw_microradians": 2000, "scale_milli": 1000}


def _catalog() -> EnvironmentFeatureCatalog:
    return EnvironmentFeatureCatalog(
        publication_id=uuid.UUID(int=1),
        admission_id=uuid.UUID(int=2),
        provider_key="nyc-open-data",
        place_id=uuid.UUID(int=3),
        index_asset_id=uuid.UUID(int=4),
        render_asset_id=uuid.UUID(int=5),
        geographic_frame={"name": "nyc-grid"},
        coordinate_scale=1000,
        receipt={},
        receipt_sha256="0" * 64,
        features=(),
    )


def _placement(bbox: tuple[int, ...]):
    return selected_feature_placement(
        _catalog(),
        instance_id="nyc-open-data:doitt_id-9",
        feature_id="f" * 32,
        render_batch_id=3,
        frame_name="nyc-grid",
        bbox=bbox,
        region_id="region-a",
        transform=tuple(TRANSFORM.values()),
        origin_role="fictional",
    )


def test_a_building_is_named_by_its_doitt_id():
    assert nyc_instance_id("doitt_id:1234") == "nyc-open-data:doitt_id-1234"


@pytest.mark.parametrize(
    ("bbox", "anchor"),
    [
        ((0, 0, 11, 21), (6, 11)),
        ((-11, -21, 0, 0), (-5, -10)),
        ((0, 0, 0, 10, 20, 31), (5, 10, 16)),
    ],
)
def test_the_anchor_is_the_boxs_centre_rounded_up(bbox, anchor):
    """Each coordinate is the midpoint of the box's minimum and maximum, a half rounded up."""
    source_anchor = _placement(bbox).source_anchor
    assert (source_anchor.frame_name, source_anchor.coordinate_scale) == ("nyc-grid", 1000)
    assert source_anchor.coordinates == anchor


def test_the_placement_carries_the_selection_the_catalog_and_the_request():
    placement = _placement((0, 0, 0, 10, 20, 30))
    assert placement.instance_id == "nyc-open-data:doitt_id-9"
    assert (placement.admission_id, placement.render_asset_id, placement.publication_id) == (
        uuid.UUID(int=2),
        uuid.UUID(int=5),
        uuid.UUID(int=1),
    )
    assert (placement.selection.kind, placement.selection.feature_id) == ("feature", "f" * 32)
    assert placement.selection.render_batch_id == 3
    assert placement.region_id == "region-a"
    assert {name: getattr(placement.transform, name) for name in TRANSFORM} == TRANSFORM
    assert (placement.origin.kind, placement.origin.role) == ("authored", "fictional")


@pytest.mark.postgres
def test_a_place_proposal_names_anchors_and_places_the_selected_building(
    composed, spine_schema, monkeypatch
):
    token = "environment-placement-owner-token"
    monkeypatch.setenv(
        "EXULANICA_API_TOKENS",
        json.dumps(
            {
                token: {
                    "workspace_id": str(composed.worlds.workspace_id),
                    "actor": str(uuid.uuid4()),
                    "permissions": EVERY_PERMISSION,
                }
            }
        ),
    )
    composed.worlds.connection.commit()
    transport = FakeTransport(
        [
            HttpResponse(
                status_code=200,
                text=json.dumps(chat_body(json.dumps({"operation": "place_selected_feature"}))),
            )
        ]
    )
    _psycopg, scratch = spine_schema
    database = scratch_database(scratch)
    services = Services(
        database=database,
        readonly_database=database,
        store=composed.store,
        tokens=load_token_directory(),
        executor_shares_the_write_role=True,
        model_client=ModelClient(
            api_key="test-key-not-real",
            transport=transport,
            budget=BudgetGuard(ceiling_usd=TEST_CEILING_USD, max_calls=TEST_MAX_CALLS),
        ),
    )
    body = {
        "utterance": "place this building",
        "version_id": str(composed.version.version_id),
        "base_state_sha256": composed.version.state_sha256,
        "admission_id": str(composed.source.admission_id),
        "selected_feature_id": composed.feature_id,
        "region_id": "region-a",
        "transform": TRANSFORM,
        "origin_role": "fictional",
    }
    with TestClient(create_app(services, verify=False)) as client:
        response = client.post(
            "/selection/environment",
            headers={"Authorization": f"Bearer {token}"},
            params={"world_id": composed.worlds.world_id},
            json=body,
        )
    assert response.status_code == 200, response.text
    proposal = response.json()["proposal"]
    assert proposal["instance_id"] == "nyc-open-data:doitt_id-1"
    assert proposal["source_anchor_frame_name"] == "nyc-grid"
    assert proposal["source_anchor_coordinates"] == [50, 50, 50]
    assert proposal["region_id"] == "region-a"
    assert proposal["transform"] == TRANSFORM
    assert proposal["origin_role"] == "fictional"
    assert transport.call_count == 1
