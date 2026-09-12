from __future__ import annotations

import hashlib
import uuid

import psycopg
import pytest
from exulanica.environment import (
    DerivedEnvironmentAsset,
    EnvironmentFeatureInput,
    EnvironmentFeatureKind,
    EnvironmentRepository,
    EnvironmentResourceWithdrawn,
    FeatureIndexPublication,
    GeographicBounds,
    GeographicFrame,
    OperationRights,
    SourceAdmission,
    UnknownEnvironmentResource,
)
from exulanica.errors import IntegrityError
from exulanica.evidence.blob import BlobId
from exulanica.store.local import LocalContentAddressedStore


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


def _frame() -> GeographicFrame:
    return GeographicFrame(
        name="grid",
        crs="EPSG:6697",
        axis_order=("east", "north", "height"),
        horizontal_unit="metre",
        vertical_unit="metre",
        orientation="right-handed",
        altitude_reference="JGD2011",
    )


def _bounds() -> GeographicBounds:
    return GeographicBounds(
        kind="bbox",
        frame_name="grid",
        coordinate_scale=1000,
        coordinates=(0, 0, 0, 10000, 10000, 10000),
    )


@pytest.fixture
def indexed_environment(repository, tmp_path):
    place_id = uuid.uuid4()
    repository.connection.execute(
        "insert into place(workspace_id,place_id) values(%s,%s)",
        (repository.workspace_id, place_id),
    )
    store = LocalContentAddressedStore(tmp_path / "feature-index-store")
    repo = EnvironmentRepository(repository.connection, repository.workspace_id, store)
    source_bytes = b"feature source"
    source_path = tmp_path / "source.gml"
    source_path.write_bytes(source_bytes)
    source = SourceAdmission(
        place_id=place_id,
        provider_key="plateau",
        provider_original_id="shibuya",
        provider_revision="2023",
        expected_sha256=hashlib.sha256(source_bytes).hexdigest(),
        expected_byte_size=len(source_bytes),
        source_path="fixture/source.gml",
        media_type="application/gml+xml",
        geographic_frame=_frame(),
        geographic_bounds=_bounds(),
        operation_rights=_rights(),
        attribution="fixture attribution",
        modification_notice="fixture source unchanged",
        local_path=source_path,
    )
    repo.admit_source(source, actor=uuid.uuid4())
    render_bytes = b"render glb"
    render_path = tmp_path / "render.glb"
    render_path.write_bytes(render_bytes)
    render = DerivedEnvironmentAsset(
        admission_id=source.admission_id,
        expected_sha256=hashlib.sha256(render_bytes).hexdigest(),
        expected_byte_size=len(render_bytes),
        media_type="model/gltf-binary",
        derivation_kind="citygml-to-glb",
        derivation_lineage={
            "method": "fixture-converter/v1",
            "input_sha256": [source.expected_sha256],
        },
        geographic_frame=_frame(),
        geographic_bounds=_bounds(),
        operation_rights=_rights(),
        attribution="fixture attribution",
        modification_notice="converted fixture",
        local_path=render_path,
    )
    repo.register_derived(render, actor=uuid.uuid4())
    return repo, source, render, store


def _publication(render_id: uuid.UUID, label: str) -> FeatureIndexPublication:
    return FeatureIndexPublication(
        render_asset_id=render_id,
        features=(
            EnvironmentFeatureInput(
                provider_feature_id=f"gml-{label.lower()}",
                kind="building",
                bbox=(0, 0, 10, 10),
                label=label,
            ),
            EnvironmentFeatureInput(
                provider_feature_id="gml-water",
                kind="water",
                bbox=(20, 20, 30, 30),
                label="Canal",
            ),
        ),
    )


def test_publication_stores_one_catalog_asset_and_current_filters_exactly(indexed_environment):
    repo, source, render, _store = indexed_environment
    first = repo.publish_feature_index(
        source.admission_id, _publication(render.asset_id, "Hall"), actor=uuid.uuid4()
    )
    second = repo.publish_feature_index(
        source.admission_id, _publication(render.asset_id, "Tower"), actor=uuid.uuid4()
    )
    assert first.publication_id != second.publication_id
    assert second.receipt["index_asset_id"] == str(second.index_asset_id)
    assert second.receipt["render_asset_id"] == str(render.asset_id)
    assert repo.read_features(source.admission_id).publication_id == second.publication_id
    selected = repo.read_features(
        source.admission_id,
        kind=EnvironmentFeatureKind.BUILDING,
        bbox=(0, 0, 10, 10),
        label="Tower",
    )
    assert [feature["label"] for feature in selected.features] == ["Tower"]
    assert repo.read_features(source.admission_id, label="tower").features == ()
    assert (
        repo.connection.execute(
            "select count(*) n from derived_environment_asset "
            "where workspace_id=%s and derivation_kind='environment-feature-index'",
            (repo.workspace_id,),
        ).fetchone()["n"]
        == 2
    )
    assert not repo.connection.execute(
        "select 1 from information_schema.tables "
        "where table_schema=current_schema() and table_name='environment_feature'"
    ).fetchone()
    with pytest.raises(psycopg.errors.CheckViolation, match="immutable"):
        repo.connection.execute(
            "update environment_feature_index_publication set published_by=%s "
            "where workspace_id=%s and publication_id=%s",
            (uuid.uuid4(), repo.workspace_id, second.publication_id),
        )
    with pytest.raises(psycopg.errors.CheckViolation, match="immutable"):
        repo.connection.execute(
            "delete from environment_feature_index_publication "
            "where workspace_id=%s and publication_id=%s",
            (repo.workspace_id, second.publication_id),
        )


@pytest.mark.parametrize("withdrawn", ["source", "index", "render"])
def test_source_index_and_render_withdrawal_fail_closed(indexed_environment, withdrawn):
    repo, source, render, _store = indexed_environment
    published = repo.publish_feature_index(
        source.admission_id, _publication(render.asset_id, "Hall"), actor=uuid.uuid4()
    )
    resource_id = {
        "source": source.admission_id,
        "index": published.index_asset_id,
        "render": render.asset_id,
    }[withdrawn]
    repo.withdraw("source" if withdrawn == "source" else "asset", resource_id)
    with pytest.raises(EnvironmentResourceWithdrawn):
        repo.read_features(source.admission_id)


def test_catalog_byte_corruption_and_cross_workspace_reads_fail_closed(
    indexed_environment, tmp_path
):
    repo, source, render, store = indexed_environment
    published = repo.publish_feature_index(
        source.admission_id, _publication(render.asset_id, "Hall"), actor=uuid.uuid4()
    )
    foreign = EnvironmentRepository(
        repo.connection,
        uuid.uuid4(),
        LocalContentAddressedStore(tmp_path / "foreign-store"),
    )
    with pytest.raises(UnknownEnvironmentResource) as real:
        foreign.read_features(source.admission_id)
    with pytest.raises(UnknownEnvironmentResource) as absent:
        foreign.read_features(uuid.uuid4())
    assert str(real.value) == str(absent.value)
    repo = EnvironmentRepository(repo.connection, repo.workspace_id, store)

    row = repo.connection.execute(
        "select index_sha256 from environment_feature_index_publication "
        "where workspace_id=%s and publication_id=%s",
        (repo.workspace_id, published.publication_id),
    ).fetchone()
    path = store.root / store.key_for(BlobId(row["index_sha256"]))
    path.chmod(0o644)
    data = path.read_bytes()
    path.write_bytes(data[:-1] + bytes([data[-1] ^ 1]))
    with pytest.raises(IntegrityError):
        repo.read_features(source.admission_id)
