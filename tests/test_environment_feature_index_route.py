from __future__ import annotations

import hashlib
import uuid

from exulanica.environment import (
    DerivedEnvironmentAsset,
    EnvironmentRepository,
    FeatureIndexPublication,
    GeographicBounds,
    GeographicFrame,
    OperationRights,
    SourceAdmission,
)

from test_api import deployment as deployment


def _rights() -> OperationRights:
    return OperationRights(
        display=True,
        extract=True,
        index=True,
        persist=True,
        modify=True,
        compose=True,
        export=False,
        model_processing=False,
    )


def _setup(deployment, repository, tmp_path):
    frame = GeographicFrame(
        name="grid",
        crs="EPSG:6697",
        axis_order=("east", "north", "height"),
        horizontal_unit="metre",
        vertical_unit="metre",
        orientation="right-handed",
        altitude_reference="JGD2011",
    )
    bounds = GeographicBounds(
        kind="bbox",
        frame_name="grid",
        coordinate_scale=1000,
        coordinates=(0, 0, 0, 100, 100, 100),
    )
    place_id = uuid.uuid4()
    repository.connection.execute(
        "insert into place(workspace_id,place_id) values(%s,%s)",
        (repository.workspace_id, place_id),
    )
    source_data = b"route feature source"
    source_path = tmp_path / "route-feature-source.gml"
    source_path.write_bytes(source_data)
    source = SourceAdmission(
        place_id=place_id,
        provider_key="provider",
        provider_original_id="city",
        provider_revision="1",
        expected_sha256=hashlib.sha256(source_data).hexdigest(),
        expected_byte_size=len(source_data),
        source_path="fixture.gml",
        media_type="application/gml+xml",
        geographic_frame=frame,
        geographic_bounds=bounds,
        operation_rights=_rights(),
        attribution="fixture",
        modification_notice="unchanged",
        local_path=source_path,
    )
    repo = EnvironmentRepository(repository.connection, repository.workspace_id, deployment.store)
    repo.admit_source(source, actor=uuid.uuid4())
    render_data = b"route render"
    render_path = tmp_path / "route-render.glb"
    render_path.write_bytes(render_data)
    render = DerivedEnvironmentAsset(
        admission_id=source.admission_id,
        expected_sha256=hashlib.sha256(render_data).hexdigest(),
        expected_byte_size=len(render_data),
        media_type="model/gltf-binary",
        derivation_kind="fixture",
        derivation_lineage={
            "method": "fixture/v1",
            "input_sha256": [source.expected_sha256],
        },
        geographic_frame=frame,
        geographic_bounds=bounds,
        operation_rights=_rights(),
        attribution="fixture",
        modification_notice="converted",
        local_path=render_path,
    )
    repo.register_derived(render, actor=uuid.uuid4())
    return repo, source, render


def test_route_publishes_and_filters_the_current_catalog(deployment, repository, tmp_path):
    _repo, source, render = _setup(deployment, repository, tmp_path)
    body = {
        "render_asset_id": str(render.asset_id),
        "features": [
            {
                "provider_feature_id": "b-2",
                "kind": "water",
                "bbox": [20, 20, 0, 30, 30, 10],
                "label": "Canal",
                "render_batch_id": 2,
            },
            {
                "provider_feature_id": "b-1",
                "kind": "building",
                "bbox": [0, 0, 0, 10, 10, 10],
                "label": "Hall",
                "render_batch_id": 1,
            },
        ],
    }
    published = deployment.as_owner(
        "POST",
        f"/environment-resources/sources/{source.admission_id}/feature-indexes",
        json=body,
    )
    assert published.status_code == 201, published.text
    result = deployment.as_owner(
        "GET",
        f"/environment-resources/sources/{source.admission_id}/features",
        params=[
            ("kind", "building"),
            ("bbox", "0"),
            ("bbox", "0"),
            ("bbox", "0"),
            ("bbox", "5"),
            ("bbox", "5"),
            ("bbox", "5"),
            ("label", "Hall"),
        ],
    )
    assert result.status_code == 200, result.text
    assert [feature["label"] for feature in result.json()["features"]] == ["Hall"]
    assert result.json()["place_id"] == str(source.place_id)
    assert result.json()["geographic_frame"]["name"] == "grid"
    assert result.json()["coordinate_scale"] == 1000
    assert result.json()["features"][0]["render_batch_id"] == 1
    assert result.headers["cache-control"] == "private, no-store"

    wrong_dimensions = deployment.as_owner(
        "GET",
        f"/environment-resources/sources/{source.admission_id}/features",
        params=[("bbox", "0"), ("bbox", "0"), ("bbox", "10"), ("bbox", "10")],
    )
    assert wrong_dimensions.status_code == 422
    assert wrong_dimensions.json()["code"] == "invalid_filter"


def test_route_hides_foreign_indexes_and_reports_withdrawal(deployment, repository, tmp_path):
    repo, source, render = _setup(deployment, repository, tmp_path)
    published = repo.publish_feature_index(
        source.admission_id,
        FeatureIndexPublication(
            render_asset_id=render.asset_id,
            features=(
                {
                    "provider_feature_id": "feature",
                    "kind": "terrain",
                    "bbox": [0, 0, 0, 10, 10, 10],
                },
            ),
        ),
        actor=uuid.uuid4(),
    )
    route = f"/environment-resources/sources/{source.admission_id}/features"
    real = deployment.as_stranger("GET", route)
    absent = deployment.as_stranger(
        "GET", f"/environment-resources/sources/{uuid.uuid4()}/features"
    )
    assert real.status_code == absent.status_code == 404
    assert real.json() == absent.json()

    repo.withdraw("asset", published.index_asset_id)
    withdrawn = deployment.as_owner("GET", route)
    assert withdrawn.status_code == 410
    assert withdrawn.json()["code"] == "withdrawn"
