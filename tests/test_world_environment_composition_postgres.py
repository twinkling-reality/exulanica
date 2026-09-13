from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, replace

import pytest
from exulanica.api.app import create_app
from exulanica.api.authorisation import load_token_directory
from exulanica.api.services import Services
from exulanica.environment import (
    DerivedEnvironmentAsset,
    EnvironmentFeatureInput,
    EnvironmentRepository,
    FeatureIndexPublication,
    GeographicBounds,
    GeographicFrame,
    OperationRights,
    SourceAdmission,
)
from exulanica.evidence.blob import BlobId
from exulanica.ingest.spine.scope import WorkspaceScope
from exulanica.store.local import LocalContentAddressedStore
from exulanica.world import (
    EnvironmentBindingDrift,
    EnvironmentCompositionDenied,
    EnvironmentPlacement,
    EnvironmentSelection,
    EnvironmentSourceWithdrawn,
    InvalidEnvironmentData,
    ObjectOrigin,
    SourceAnchor,
    StaleObjectBase,
    Transform,
    UnknownWorldResource,
    WorldObjectRepository,
    WorldStructureRepository,
)
from fastapi.testclient import TestClient

from pg_harness import open_scratch_connection
from tests_support_api import scratch_database
from world_structure_fixtures import structural_candidate

pytestmark = pytest.mark.postgres


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
        name="nyc-grid",
        crs="EPSG:6539",
        axis_order=("east", "north", "height"),
        horizontal_unit="metre",
        vertical_unit="metre",
        orientation="right-handed",
        altitude_reference="NAVD88",
    )


def _bounds() -> GeographicBounds:
    return GeographicBounds(
        kind="bbox",
        frame_name="nyc-grid",
        coordinate_scale=1000,
        coordinates=(0, 0, 0, 100_000, 100_000, 10_000),
    )


def _transform(x_mm: int = 0) -> Transform:
    return Transform(x_mm, 0, 0, 0, 1000)


@dataclass
class Composed:
    environments: EnvironmentRepository
    worlds: WorldObjectRepository
    source: SourceAdmission
    render: DerivedEnvironmentAsset
    publication: object
    feature_id: str
    version: object
    store: LocalContentAddressedStore

    def placement(
        self,
        instance_id: str,
        *,
        feature: bool = False,
        publication_id: uuid.UUID | None = None,
    ) -> EnvironmentPlacement:
        return EnvironmentPlacement(
            instance_id=instance_id,
            admission_id=self.source.admission_id,
            render_asset_id=self.render.asset_id,
            publication_id=(
                publication_id
                if publication_id is not None
                else (self.publication.publication_id if feature else None)
            ),
            selection=EnvironmentSelection(
                "feature" if feature else "whole_asset",
                self.feature_id if feature else None,
                7 if feature else None,
            ),
            source_anchor=SourceAnchor("nyc-grid", 1000, (10, 20, 0)),
            region_id="region-a",
            transform=_transform(),
            origin=ObjectOrigin("authored", "fictional"),
        )


@pytest.fixture
def composed(repository, tmp_path) -> Composed:
    actor = uuid.uuid4()
    structures = WorldStructureRepository(repository.connection, repository.workspace_id)
    preview = structures.preview(structural_candidate(), proposed_by=actor)
    snapshot = structures.apply(
        preview.preview_id,
        base_snapshot_id=preview.base_snapshot_id,
        base_graph_sha256=preview.base_graph_sha256,
        base_reconstruction_sha256=preview.base_reconstruction_sha256,
        committed_by=actor,
    )
    place_id = uuid.uuid4()
    repository.connection.execute(
        "insert into place(workspace_id,place_id) values(%s,%s)",
        (repository.workspace_id, place_id),
    )
    store = LocalContentAddressedStore(tmp_path / "environment-composition-store")
    environments = EnvironmentRepository(repository.connection, repository.workspace_id, store)
    source_bytes = b"exact admitted NYC source"
    source_path = tmp_path / "source.bin"
    source_path.write_bytes(source_bytes)
    source = SourceAdmission(
        place_id=place_id,
        provider_key="fixture-nyc",
        provider_original_id="corridor",
        provider_revision="2026-09-12",
        expected_sha256=hashlib.sha256(source_bytes).hexdigest(),
        expected_byte_size=len(source_bytes),
        source_path="fixture/source.bin",
        media_type="application/octet-stream",
        geographic_frame=_frame(),
        geographic_bounds=_bounds(),
        operation_rights=_rights(),
        attribution="Synthetic fixture",
        modification_notice="Synthetic fixture is unchanged",
        local_path=source_path,
    )
    environments.admit_source(source, actor=actor)
    render_bytes = b"exact bounded render asset"
    render_path = tmp_path / "render.glb"
    render_path.write_bytes(render_bytes)
    render = DerivedEnvironmentAsset(
        admission_id=source.admission_id,
        expected_sha256=hashlib.sha256(render_bytes).hexdigest(),
        expected_byte_size=len(render_bytes),
        media_type="model/gltf-binary",
        derivation_kind="fixture-render",
        derivation_lineage={"method": "fixture/v1", "input_sha256": [source.expected_sha256]},
        geographic_frame=_frame(),
        geographic_bounds=_bounds(),
        operation_rights=_rights(),
        attribution="Synthetic fixture",
        modification_notice="Synthetic render fixture",
        local_path=render_path,
    )
    environments.register_derived(render, actor=actor)
    publication = environments.publish_feature_index(
        source.admission_id,
        FeatureIndexPublication(
            render_asset_id=render.asset_id,
            features=(
                EnvironmentFeatureInput(
                    provider_feature_id="building-1",
                    kind="building",
                    bbox=(0, 0, 0, 100, 100, 100),
                    label="Fixture building",
                    render_batch_id=7,
                ),
            ),
        ),
        actor=actor,
    )
    feature_id = publication.features[0]["id"]
    worlds = WorldObjectRepository(
        repository.connection, repository.workspace_id, store=store
    )
    version = worlds.create_version(
        source_snapshot_id=snapshot.snapshot_id,
        title="Environment study",
        created_by=actor,
    )
    return Composed(environments, worlds, source, render, publication, feature_id, version, store)


def _add(composed: Composed, placement: EnvironmentPlacement):
    composed.version = composed.worlds.add_environment(
        composed.version.version_id,
        placement,
        base_state_sha256=composed.version.state_sha256,
        actor=uuid.uuid4(),
    )
    return composed.version


def test_whole_asset_and_feature_placements_are_pinned_sorted_and_reload(composed) -> None:
    version = _add(composed, composed.placement("environment:z"))
    version = _add(composed, composed.placement("environment:a", feature=True))
    assert [item.instance_id for item in version.environment_instances] == [
        "environment:a",
        "environment:z",
    ]
    assert version.environment_instances[0].source.selection.kind == "feature"
    assert version.environment_instances[0].source.bounds["coordinates"] == [0, 0, 0, 100, 100, 100]
    assert version.environment_instances[1].source.selection.kind == "whole_asset"
    assert {item.availability for item in version.environment_instances} == {"available"}
    reopened = composed.worlds.version(version.version_id)
    assert reopened.state_sha256 == version.state_sha256
    assert reopened.environment_instances == version.environment_instances


def test_move_changes_only_destination_then_remove_and_undo_restore_it(composed) -> None:
    version = _add(composed, composed.placement("environment:corridor", feature=True))
    source = version.environment_instances[0].source
    version = composed.worlds.move_environment(
        version.version_id,
        "environment:corridor",
        _transform(5000),
        base_state_sha256=version.state_sha256,
        actor=uuid.uuid4(),
    )
    assert version.environment_instances[0].source == source
    assert version.environment_instances[0].transform.x_mm == 5000
    moved = version.state_sha256
    version = composed.worlds.remove_environment(
        version.version_id,
        "environment:corridor",
        base_state_sha256=version.state_sha256,
        actor=uuid.uuid4(),
    )
    assert version.environment_instances[0].removed
    version = composed.worlds.undo(
        version.version_id, base_state_sha256=version.state_sha256, actor=uuid.uuid4()
    )
    assert not version.environment_instances[0].removed
    assert version.state_sha256 == moved


def test_two_clients_reject_the_stale_environment_base(composed, spine_schema) -> None:
    composed.worlds.connection.commit()
    psycopg_module, scratch = spine_schema
    connection = open_scratch_connection(psycopg_module, scratch)
    WorkspaceScope(connection, composed.worlds.workspace_id)
    competitor = WorldObjectRepository(
        connection, composed.worlds.workspace_id, store=composed.store
    )
    try:
        base = composed.version.state_sha256
        _add(composed, composed.placement("environment:first"))
        with pytest.raises(StaleObjectBase):
            competitor.add_environment(
                composed.version.version_id,
                composed.placement("environment:second"),
                base_state_sha256=base,
                actor=uuid.uuid4(),
            )
    finally:
        connection.close()


def test_add_rechecks_authorization_at_commit_and_rolls_back(monkeypatch, composed) -> None:
    original = composed.worlds._final_environment_authorization

    def withdraw_before_final(instance) -> None:
        composed.environments.withdraw("asset", composed.render.asset_id)
        original(instance)

    monkeypatch.setattr(
        composed.worlds, "_final_environment_authorization", withdraw_before_final
    )
    with pytest.raises(EnvironmentSourceWithdrawn):
        _add(composed, composed.placement("environment:final-check"))
    unchanged = composed.worlds.version(composed.version.version_id)
    assert unchanged.environment_instances == ()
    assert unchanged.edit_seq == 0


def test_rights_denial_stale_publication_and_wrong_segment_fail_closed(
    composed, tmp_path
) -> None:
    existing = _add(composed, composed.placement("environment:indexed", feature=True))
    wrong_segment = composed.placement("environment:wrong", feature=True)
    wrong_segment = replace(
        wrong_segment, selection=EnvironmentSelection("feature", "0" * 32, 7)
    )
    with pytest.raises(InvalidEnvironmentData, match="feature and render batch"):
        composed.worlds.add_environment(
            composed.version.version_id,
            wrong_segment,
            base_state_sha256=composed.version.state_sha256,
            actor=uuid.uuid4(),
        )

    old = composed.publication.publication_id
    composed.worlds.connection.commit()
    composed.environments.publish_feature_index(
        composed.source.admission_id,
        FeatureIndexPublication(render_asset_id=composed.render.asset_id, features=()),
        actor=uuid.uuid4(),
    )
    drifted = composed.worlds.version(existing.version_id)
    assert drifted.environment_instances[0].availability == "binding_drift"
    with pytest.raises(EnvironmentBindingDrift):
        composed.worlds.add_environment(
            composed.version.version_id,
            composed.placement("environment:stale", feature=True, publication_id=old),
            base_state_sha256=composed.version.state_sha256,
            actor=uuid.uuid4(),
        )

    denied_bytes = b"denied render"
    denied_path = tmp_path / "denied.glb"
    denied_path.write_bytes(denied_bytes)
    denied = DerivedEnvironmentAsset(
        admission_id=composed.source.admission_id,
        expected_sha256=hashlib.sha256(denied_bytes).hexdigest(),
        expected_byte_size=len(denied_bytes),
        media_type="model/gltf-binary",
        derivation_kind="denied",
        derivation_lineage={
            "method": "fixture/v1",
            "input_sha256": [composed.source.expected_sha256],
        },
        geographic_frame=_frame(),
        geographic_bounds=_bounds(),
        operation_rights=_rights(compose=False),
        attribution="Synthetic fixture",
        modification_notice="Denied composition fixture",
        local_path=denied_path,
    )
    composed.environments.register_derived(denied, actor=uuid.uuid4())
    placement = composed.placement("environment:denied")
    placement = EnvironmentPlacement(
        instance_id=placement.instance_id,
        admission_id=placement.admission_id,
        render_asset_id=denied.asset_id,
        publication_id=None,
        selection=placement.selection,
        source_anchor=placement.source_anchor,
        region_id=placement.region_id,
        transform=placement.transform,
        origin=placement.origin,
    )
    with pytest.raises(EnvironmentCompositionDenied):
        composed.worlds.add_environment(
            composed.version.version_id,
            placement,
            base_state_sha256=composed.version.state_sha256,
            actor=uuid.uuid4(),
        )


def test_cross_workspace_hides_environment_history(composed, spine_schema) -> None:
    version = _add(composed, composed.placement("environment:private"))
    composed.worlds.connection.commit()
    psycopg_module, scratch = spine_schema
    connection = open_scratch_connection(psycopg_module, scratch)
    workspace_id = uuid.uuid4()
    WorkspaceScope(connection, workspace_id)
    try:
        stranger = WorldObjectRepository(connection, workspace_id, store=composed.store)
        assert stranger.versions() == ()
        with pytest.raises(UnknownWorldResource):
            stranger.version(version.version_id)
    finally:
        connection.close()


def test_withdrawal_retains_history_allows_remove_and_undo_but_refuses_move(composed) -> None:
    version = _add(composed, composed.placement("environment:withdrawn"))
    composed.environments.withdraw("asset", composed.render.asset_id)
    reread = composed.worlds.version(version.version_id)
    assert reread.environment_instances[0].availability == "withdrawn"
    with pytest.raises(EnvironmentSourceWithdrawn):
        composed.worlds.move_environment(
            version.version_id,
            "environment:withdrawn",
            _transform(10),
            base_state_sha256=version.state_sha256,
            actor=uuid.uuid4(),
        )
    version = composed.worlds.remove_environment(
        version.version_id,
        "environment:withdrawn",
        base_state_sha256=version.state_sha256,
        actor=uuid.uuid4(),
    )
    assert version.environment_instances[0].removed
    version = composed.worlds.undo(
        version.version_id, base_state_sha256=version.state_sha256, actor=uuid.uuid4()
    )
    assert not version.environment_instances[0].removed
    assert version.environment_instances[0].availability == "withdrawn"


def test_missing_exact_bytes_are_reported_without_substitution(composed) -> None:
    version = _add(composed, composed.placement("environment:missing"))
    digest = BlobId.from_hex(composed.render.expected_sha256)
    path = composed.store.root / composed.store.key_for(digest)
    path.unlink()
    reread = composed.worlds.version(version.version_id)
    assert reread.environment_instances[0].availability == "unavailable_bytes"
    assert reread.environment_instances[0].source.render_sha256 == composed.render.expected_sha256


def test_authenticated_environment_routes_add_move_reload_remove_and_undo(
    composed, spine_schema, monkeypatch
) -> None:
    token = "environment-composition-owner-token"
    actor = uuid.uuid4()
    monkeypatch.setenv(
        "EXULANICA_API_TOKENS",
        json.dumps(
            {
                token: {
                    "workspace_id": str(composed.worlds.workspace_id),
                    "actor": str(actor),
                }
            }
        ),
    )
    composed.worlds.connection.commit()
    _psycopg, scratch = spine_schema
    database = scratch_database(scratch)
    services = Services(
        database=database,
        readonly_database=database,
        store=composed.store,
        tokens=load_token_directory(),
        executor_shares_the_write_role=True,
        model_client=None,
    )
    headers = {"Authorization": f"Bearer {token}"}
    path = f"/world/versions/{composed.version.version_id}/environment-instances"
    body = {
        "base_state_sha256": composed.version.state_sha256,
        "instance_id": "environment:api",
        "admission_id": str(composed.source.admission_id),
        "render_asset_id": str(composed.render.asset_id),
        "publication_id": None,
        "selection": {"kind": "whole_asset"},
        "source_anchor": {
            "frame_name": "nyc-grid",
            "coordinate_scale": 1000,
            "coordinates": [10, 20, 0],
        },
        "region_id": "region-a",
        "transform": {
            "x_mm": 0,
            "y_mm": 0,
            "z_mm": 0,
            "yaw_microradians": 0,
            "scale_milli": 1000,
        },
        "origin_role": "personal",
    }
    with TestClient(create_app(services, verify=False)) as client:
        assert client.post(path, json=body).status_code in {401, 403}
        response = client.post(path, json=body, headers=headers)
        assert response.status_code == 201, response.text
        version = response.json()
        assert version["schema_version"] == 2
        assert version["environment_instances"][0]["availability"] == "available"
        assert version["environment_instances"][0]["origin"]["role"] == "personal"
        source = version["environment_instances"][0]["source"]

        move = client.post(
            f"{path}/environment:api/move",
            headers=headers,
            json={
                "base_state_sha256": version["state_sha256"],
                "transform": {**body["transform"], "x_mm": 2500},
            },
        )
        assert move.status_code == 200, move.text
        version = move.json()
        assert version["environment_instances"][0]["source"] == source
        assert version["environment_instances"][0]["transform"]["x_mm"] == 2500

        reread = client.get(
            f"/world/versions/{composed.version.version_id}", headers=headers
        )
        assert reread.json() == version
        remove = client.post(
            f"{path}/environment:api/remove",
            headers=headers,
            json={"base_state_sha256": version["state_sha256"]},
        )
        assert remove.status_code == 200
        version = remove.json()
        assert version["environment_instances"][0]["removed"]
        undo = client.post(
            f"{path}/undo",
            headers=headers,
            json={"base_state_sha256": version["state_sha256"]},
        )
        assert undo.status_code == 200, undo.text
        assert not undo.json()["environment_instances"][0]["removed"]
