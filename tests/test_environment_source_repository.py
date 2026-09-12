from __future__ import annotations

import hashlib
import uuid

import psycopg
import pytest
from exulanica.environment import (
    MAX_ENVIRONMENT_PAYLOAD_BYTES,
    DerivedEnvironmentAsset,
    EnvironmentOperation,
    EnvironmentOperationDenied,
    EnvironmentPayloadTooLarge,
    EnvironmentRepository,
    EnvironmentResourceWithdrawn,
    GeographicBounds,
    GeographicFrame,
    OperationRights,
    SourceAdmission,
    SourceDigestMismatch,
    UnknownEnvironmentResource,
    derived_receipt,
)
from exulanica.errors import BlobNotFoundError, IntegrityError
from exulanica.evidence.blob import BlobId
from exulanica.store.base import PurgeAuthorization, privileged_purger
from exulanica.store.local import LocalContentAddressedStore
from psycopg.types.json import Jsonb


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
        repo.read_bytes("source", source.admission_id, EnvironmentOperation.DISPLAY).data
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
    assert repo.read_bytes("asset", asset.asset_id, EnvironmentOperation.COMPOSE).data == content

    escalated = _rights(export=True).model_dump(mode="json")
    with pytest.raises(psycopg.errors.CheckViolation):
        repo.connection.execute(
            "update environment_source_admission set operation_rights=%s "
            "where workspace_id=%s and admission_id=%s",
            (Jsonb(escalated), repo.workspace_id, source.admission_id),
        )
    with pytest.raises(psycopg.errors.CheckViolation):
        repo.connection.execute(
            "update derived_environment_asset set operation_rights=%s "
            "where workspace_id=%s and asset_id=%s",
            (Jsonb(escalated), repo.workspace_id, asset.asset_id),
        )
    assert repo.read_metadata(
        "source", source.admission_id, EnvironmentOperation.DISPLAY
    ).operation_rights["export"] is False
    with pytest.raises(EnvironmentOperationDenied):
        repo.read_metadata("asset", asset.asset_id, EnvironmentOperation.EXPORT)


def test_database_refuses_a_child_of_a_withdrawn_parent(environment):
    repo, source, _source_bytes, store, tmp_path = environment
    parent_data = b"parent"
    parent_path = tmp_path / "parent.glb"
    parent_path.write_bytes(parent_data)
    parent = DerivedEnvironmentAsset(
        admission_id=source.admission_id,
        expected_sha256=hashlib.sha256(parent_data).hexdigest(),
        expected_byte_size=len(parent_data),
        media_type="model/gltf-binary",
        derivation_kind="parent",
        derivation_lineage={"method": "fixture/v1", "input_sha256": [source.expected_sha256]},
        geographic_frame=_frame(),
        geographic_bounds=_bounds(),
        operation_rights=_rights(),
        attribution="attribution",
        modification_notice="modified",
        local_path=parent_path,
    )
    repo.register_derived(parent, actor=uuid.uuid4())
    repo.withdraw("asset", parent.asset_id)

    child_data = b"child"
    child_path = tmp_path / "child.glb"
    child_path.write_bytes(child_data)
    child = DerivedEnvironmentAsset(
        admission_id=source.admission_id,
        parent_asset_id=parent.asset_id,
        expected_sha256=hashlib.sha256(child_data).hexdigest(),
        expected_byte_size=len(child_data),
        media_type="model/gltf-binary",
        derivation_kind="child",
        derivation_lineage={"method": "fixture/v1", "input_sha256": [parent.expected_sha256]},
        geographic_frame=_frame(),
        geographic_bounds=_bounds(),
        operation_rights=_rights(),
        attribution="attribution",
        modification_notice="modified",
        local_path=child_path,
    )
    stored = store.put_file(child_path)
    record, encoded, receipt_sha256 = derived_receipt(
        child, source_sha256=source.expected_sha256
    )
    with pytest.raises(psycopg.errors.CheckViolation, match="parent"):
        repo.connection.execute(
            """
            insert into derived_environment_asset(
              workspace_id,asset_id,admission_id,parent_asset_id,source_sha256,content_sha256,
              media_type,byte_size,derivation_kind,derivation_lineage,geographic_frame,
              geographic_bounds,operation_rights,attribution,modification_notice,receipt_record,
              receipt_canonical,receipt_sha256,created_by)
            values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (
                repo.workspace_id,
                child.asset_id,
                child.admission_id,
                child.parent_asset_id,
                bytes.fromhex(source.expected_sha256),
                stored.blob_id.digest,
                child.media_type,
                stored.byte_size,
                child.derivation_kind,
                Jsonb(child.derivation_lineage),
                Jsonb(child.geographic_frame.model_dump(mode="json")),
                Jsonb(child.geographic_bounds.model_dump(mode="json")),
                Jsonb(child.operation_rights.model_dump(mode="json")),
                child.attribution,
                child.modification_notice,
                Jsonb(record),
                encoded,
                receipt_sha256,
                uuid.uuid4(),
            ),
        )


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


def test_oversized_file_is_refused_before_hashing(repository, tmp_path, monkeypatch):
    path = tmp_path / "oversized.bin"
    with path.open("wb") as handle:
        handle.truncate(MAX_ENVIRONMENT_PAYLOAD_BYTES + 1)
    repo = EnvironmentRepository(
        repository.connection,
        repository.workspace_id,
        LocalContentAddressedStore(tmp_path / "oversized-store"),
    )
    monkeypatch.setattr(
        BlobId,
        "of_file",
        lambda _path: (_ for _ in ()).throw(AssertionError("oversized file was hashed")),
    )
    with pytest.raises(EnvironmentPayloadTooLarge):
        repo._store_exact(path, "0" * 64, MAX_ENVIRONMENT_PAYLOAD_BYTES + 1)


def test_oversized_database_row_is_refused_before_store_read(monkeypatch):
    class NoReadStore:
        def get(self, _blob):
            raise AssertionError("oversized row reached the store")

    repo = object.__new__(EnvironmentRepository)
    repo.store = NoReadStore()
    monkeypatch.setattr(
        repo,
        "_authorized_row",
        lambda *_args: {"byte_size": MAX_ENVIRONMENT_PAYLOAD_BYTES + 1},
    )
    with pytest.raises(IntegrityError, match="buffered reads"):
        repo.read_bytes("source", uuid.uuid4(), EnvironmentOperation.DISPLAY)
