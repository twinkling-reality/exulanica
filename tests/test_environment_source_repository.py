from __future__ import annotations

import hashlib
import uuid

import pytest
from exulanica.environment import (
    DerivedEnvironmentAsset,
    EnvironmentOperation,
    EnvironmentOperationDenied,
    EnvironmentRepository,
    EnvironmentResourceWithdrawn,
    GeographicBounds,
    GeographicFrame,
    OperationRights,
    SourceAdmission,
    SourceDigestMismatch,
    UnknownEnvironmentResource,
)
from exulanica.errors import BlobNotFoundError
from exulanica.evidence.blob import BlobId
from exulanica.store.base import PurgeAuthorization, privileged_purger
from exulanica.store.local import LocalContentAddressedStore


def _rights(**changes: bool) -> OperationRights:
    values = {
        "display": True,
        "extract": True,
        "index": True,
        "persist": True,
        "modify": True,
        "compose": True,
        "export": False,
        "model_processing": False,
    }
    values.update(changes)
    return OperationRights.model_validate(values)


def _frame() -> GeographicFrame:
    return GeographicFrame(
        name="plateau-epsg-6697",
        crs="EPSG:6697",
        axis_order=("east", "north", "height"),
        horizontal_unit="metre",
        vertical_unit="metre",
        orientation="right-handed",
        altitude_reference="JGD2011 vertical datum",
    )


def _bounds() -> GeographicBounds:
    return GeographicBounds(
        kind="bbox",
        frame_name="plateau-epsg-6697",
        coordinate_scale=1000,
        coordinates=(139000000, 35000000, 0, 140000000, 36000000, 100000),
    )


@pytest.fixture
def environment(repository, tmp_path):
    place_id = uuid.uuid4()
    repository.connection.execute(
        "insert into place(workspace_id,place_id) values(%s,%s)",
        (repository.workspace_id, place_id),
    )
    store = LocalContentAddressedStore(tmp_path / "environment-blobs")
    source_bytes = b"small synthetic CityGML archive fixture"
    path = tmp_path / "source.zip"
    path.write_bytes(source_bytes)
    source = SourceAdmission(
        place_id=place_id,
        provider_key="plateau",
        provider_original_id="shibuya-2023-citygml-v3",
        provider_revision="2023",
        expected_sha256=hashlib.sha256(source_bytes).hexdigest(),
        expected_byte_size=len(source_bytes),
        source_path="https://example.invalid/official-source.zip",
        member_path="udx/bldg/53393567.gml",
        media_type="application/zip",
        geographic_frame=_frame(),
        geographic_bounds=_bounds(),
        operation_rights=_rights(),
        attribution="Project PLATEAU; source attribution required.",
        modification_notice="Modified outputs must be marked.",
        local_path=path,
    )
    repo = EnvironmentRepository(repository.connection, repository.workspace_id, store)
    repo.admit_source(source, actor=uuid.uuid4())
    return repo, source, source_bytes, store, tmp_path


def test_admission_and_derived_asset_preserve_identity_and_verified_bytes(environment):
    repo, source, source_bytes, _store, tmp_path = environment
    metadata = repo.read_metadata("source", source.admission_id, EnvironmentOperation.DISPLAY)
    assert metadata.receipt["provider"] == {
        "key": "plateau",
        "original_id": "shibuya-2023-citygml-v3",
        "revision": "2023",
    }
    assert metadata.receipt["member_path"] == "udx/bldg/53393567.gml"
    assert (
        repo.read_bytes("source", source.admission_id, EnvironmentOperation.DISPLAY)
        == source_bytes
    )

    content = b"synthetic textured mesh derived from exact source"
    path = tmp_path / "mesh.glb"
    path.write_bytes(content)
    asset = DerivedEnvironmentAsset(
        admission_id=source.admission_id,
        expected_sha256=hashlib.sha256(content).hexdigest(),
        expected_byte_size=len(content),
        source_member_path="udx/bldg/53393567.gml#gml-id-1",
        media_type="model/gltf-binary",
        derivation_kind="citygml-building-to-glb",
        derivation_lineage={
            "method": "fixture-converter/v1",
            "input_sha256": [source.expected_sha256],
        },
        geographic_frame=_frame(),
        geographic_bounds=_bounds(),
        operation_rights=_rights(),
        attribution="Project PLATEAU; source attribution required.",
        modification_notice="Converted and modified fixture.",
        local_path=path,
    )
    saved = repo.register_derived(asset, actor=uuid.uuid4())
    assert saved.receipt["source_sha256"] == source.expected_sha256
    assert saved.receipt["derivation_lineage"]["input_sha256"] == [source.expected_sha256]
    assert repo.read_bytes("asset", asset.asset_id, EnvironmentOperation.COMPOSE) == content


def test_digest_mismatch_is_rejected_before_metadata_commit(repository, tmp_path):
    place_id = uuid.uuid4()
    repository.connection.execute(
        "insert into place(workspace_id,place_id) values(%s,%s)",
        (repository.workspace_id, place_id),
    )
    path = tmp_path / "wrong.zip"
    path.write_bytes(b"wrong")
    source = SourceAdmission(
        place_id=place_id,
        provider_key="provider",
        provider_original_id="original",
        provider_revision="revision",
        expected_sha256="0" * 64,
        expected_byte_size=5,
        source_path="local-declaration",
        media_type="application/zip",
        geographic_frame=_frame(),
        geographic_bounds=_bounds(),
        operation_rights=_rights(),
        attribution="attribution",
        modification_notice="modified",
        local_path=path,
    )
    repo = EnvironmentRepository(
        repository.connection,
        repository.workspace_id,
        LocalContentAddressedStore(tmp_path / "mismatch-store"),
    )
    with pytest.raises(SourceDigestMismatch):
        repo.admit_source(source, actor=uuid.uuid4())
    assert repository.connection.execute(
        "select count(*) n from environment_source_admission where workspace_id=%s",
        (repository.workspace_id,),
    ).fetchone()["n"] == 0


def test_denied_operation_missing_bytes_and_withdrawal_fail_closed(environment):
    repo, source, _data, store, _tmp_path = environment
    with pytest.raises(EnvironmentOperationDenied):
        repo.read_metadata("source", source.admission_id, EnvironmentOperation.EXPORT)
    with pytest.raises(EnvironmentOperationDenied):
        repo.read_bytes("source", source.admission_id, EnvironmentOperation.MODEL_PROCESSING)

    privileged_purger(
        store,
        PurgeAuthorization(tombstone_id="test", actor="test", reason="missing byte control"),
    ).purge(BlobId.from_hex(source.expected_sha256))
    with pytest.raises(BlobNotFoundError):
        repo.read_bytes("source", source.admission_id, EnvironmentOperation.DISPLAY)

    repo.withdraw("source", source.admission_id)
    with pytest.raises(EnvironmentResourceWithdrawn):
        repo.read_metadata("source", source.admission_id, EnvironmentOperation.DISPLAY)


def test_cross_workspace_resource_and_place_references_do_not_leak(environment):
    repo, source, _data, store, _tmp_path = environment
    foreign = EnvironmentRepository(repo.connection, uuid.uuid4(), store)
    with pytest.raises(UnknownEnvironmentResource) as real:
        foreign.read_metadata("source", source.admission_id, EnvironmentOperation.DISPLAY)
    with pytest.raises(UnknownEnvironmentResource) as invented:
        foreign.read_metadata("source", uuid.uuid4(), EnvironmentOperation.DISPLAY)
    assert str(real.value) == str(invented.value)

    foreign_place = source.model_copy(
        update={
            "admission_id": uuid.uuid4(),
            "provider_original_id": "foreign-place-probe",
        }
    )
    absent_place = foreign_place.model_copy(
        update={
            "admission_id": uuid.uuid4(),
            "place_id": uuid.uuid4(),
            "provider_original_id": "absent-place-probe",
        }
    )
    with pytest.raises(UnknownEnvironmentResource) as real_place:
        foreign.admit_source(foreign_place, actor=uuid.uuid4())
    with pytest.raises(UnknownEnvironmentResource) as invented_place:
        foreign.admit_source(absent_place, actor=uuid.uuid4())
    assert str(real_place.value) == str(invented_place.value)
