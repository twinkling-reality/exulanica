from __future__ import annotations

import copy
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
from exulanica.epistemics.assertions import AssertionWriter
from exulanica.evidence.blob import BlobId
from exulanica.identity import IdentityRepository, confirm_link, name_occurrence
from exulanica.ingest.pipeline import PhotoIngestPipeline
from exulanica.ingest.repository import IngestRepository
from exulanica.ingest.spine.scope import WorkspaceScope
from exulanica.models.budget import BudgetGuard
from exulanica.models.client import ModelClient
from exulanica.models.transport import HttpResponse
from exulanica.selection import (
    ContentScope,
    ContentSelector,
    Intent,
    PlaceBridgeRepository,
    PlaceSelector,
    RejectionCode,
    SelectionPlan,
    SelectionRejected,
    Session,
    execute,
    validate,
)
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
    TopologyContract,
    TopologySourceSlot,
    Transform,
    UnavailableAsset,
    UnknownWorldResource,
    WorldObjectRepository,
    WorldStructureRepository,
)
from exulanica.world.composed import UNPLACED_REASON, composed_candidate
from fastapi.testclient import TestClient

from conftest import (
    DEFAULT_PAYLOAD,
    TEST_CEILING_USD,
    TEST_MAX_CALLS,
    CountingVisionModel,
    ingest_observed,
    write_photo,
)
from model_fakes import FakeTransport, chat_body
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
    return _composed_over(repository, tmp_path, structural_candidate())


@pytest.fixture
def unplaced_composed(repository, tmp_path) -> Composed:
    """The same composition over a snapshot the bootstrap composer wrote: nothing has a position."""
    contract = TopologyContract(
        "unplaced-composition",
        ("region-a",),
        (TopologySourceSlot(uuid.uuid4(), "no-source", "region-a", None, "No source chosen"),),
    )
    return _composed_over(repository, tmp_path, composed_candidate(contract, "ab" * 32, "cd" * 32))


def _composed_over(repository, tmp_path, candidate) -> Composed:
    actor = uuid.uuid4()
    structures = WorldStructureRepository(repository.connection, repository.workspace_id)
    preview = structures.preview(candidate, proposed_by=actor)
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
        provider_key="nyc-open-data",
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
                    provider_feature_id="doitt_id:1",
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
    worlds = WorldObjectRepository(repository.connection, repository.workspace_id, store=store)
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


def test_an_unplaced_source_region_takes_an_authored_environment_without_gaining_a_position(
    unplaced_composed,
) -> None:
    version = _add(unplaced_composed, unplaced_composed.placement("environment:corridor"))
    assert [item.availability for item in version.environment_instances] == ["available"]
    assert version.environment_instances[0].region_id == "region-a"
    assert version.environment_instances[0].transform == _transform()
    stored = unplaced_composed.worlds.connection.execute(
        "select topology,placement from world_structure_snapshot where snapshot_id=%s",
        (version.source_snapshot_id,),
    ).fetchone()
    # The person's region-local transform is the only position in the composition. The source
    # snapshot still says its region has none, and nothing was written to give it one.
    assert stored["placement"]["elements"] == []
    assert stored["placement"]["destinations"] == []
    assert [item["reason"] for item in stored["placement"]["unplaced_destinations"]] == [
        UNPLACED_REASON
    ]
    assert stored["topology"]["navigation"]["edges"] == []


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

    monkeypatch.setattr(composed.worlds, "_final_environment_authorization", withdraw_before_final)
    with pytest.raises(EnvironmentSourceWithdrawn):
        _add(composed, composed.placement("environment:final-check"))
    unchanged = composed.worlds.version(composed.version.version_id)
    assert unchanged.environment_instances == ()
    assert unchanged.edit_seq == 0


def test_read_only_environment_validation_reuses_add_checks_without_editing(composed) -> None:
    placement = composed.placement("environment:preview", feature=True)
    before = composed.worlds.version(composed.version.version_id)

    validated = composed.worlds.validate_environment_placement(
        composed.version.version_id,
        placement,
        base_state_sha256=composed.version.state_sha256,
    )

    assert validated.source.selection.feature_id == composed.feature_id
    assert composed.worlds.version(composed.version.version_id) == before

    with pytest.raises(InvalidEnvironmentData, match="not a region"):
        composed.worlds.validate_environment_placement(
            composed.version.version_id,
            replace(placement, region_id="region-that-does-not-exist"),
            base_state_sha256=composed.version.state_sha256,
        )
    with pytest.raises(InvalidEnvironmentData, match="x_mm"):
        composed.worlds.validate_environment_placement(
            composed.version.version_id,
            replace(placement, transform=Transform(1_000_000_001, 0, 0, 0, 1000)),
            base_state_sha256=composed.version.state_sha256,
        )
    assert composed.worlds.version(composed.version.version_id) == before


def test_rights_denial_stale_publication_and_wrong_segment_fail_closed(composed, tmp_path) -> None:
    existing = _add(composed, composed.placement("environment:indexed", feature=True))
    wrong_segment = composed.placement("environment:wrong", feature=True)
    wrong_segment = replace(wrong_segment, selection=EnvironmentSelection("feature", "0" * 32, 7))
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
        composed.worlds.validate_environment_placement(
            composed.version.version_id,
            composed.placement("environment:stale-preview", feature=True, publication_id=old),
            base_state_sha256=composed.version.state_sha256,
        )
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
        composed.worlds.validate_environment_placement(
            composed.version.version_id,
            placement,
            base_state_sha256=composed.version.state_sha256,
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
        composed.worlds.validate_environment_placement(
            version.version_id,
            composed.placement("environment:withdrawn-preview", feature=True),
            base_state_sha256=version.state_sha256,
        )
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
    before_seq = reread.edit_seq
    with pytest.raises(UnavailableAsset):
        composed.worlds.validate_environment_placement(
            version.version_id,
            composed.placement("environment:missing-preview", feature=True),
            base_state_sha256=version.state_sha256,
        )
    assert composed.worlds.version(version.version_id).edit_seq == before_seq


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

        reread = client.get(f"/world/versions/{composed.version.version_id}", headers=headers)
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


def test_environment_proposal_is_read_only_exact_and_workspace_scoped(
    composed, spine_schema, monkeypatch
) -> None:
    token = "environment-proposal-owner-token"
    stranger_token = "environment-proposal-stranger-token"
    stranger = uuid.uuid4()
    monkeypatch.setenv(
        "EXULANICA_API_TOKENS",
        json.dumps(
            {
                token: {
                    "workspace_id": str(composed.worlds.workspace_id),
                    "actor": str(uuid.uuid4()),
                },
                stranger_token: {
                    "workspace_id": str(stranger),
                    "actor": str(uuid.uuid4()),
                },
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
        "transform": {
            "x_mm": 10,
            "y_mm": 0,
            "z_mm": 20,
            "yaw_microradians": 0,
            "scale_milli": 1000,
        },
        "origin_role": "personal",
    }
    headers = {"Authorization": f"Bearer {token}"}
    stranger_headers = {"Authorization": f"Bearer {stranger_token}"}
    with TestClient(create_app(services, verify=False)) as client:
        before = client.get(
            f"/world/versions/{composed.version.version_id}", headers=headers
        ).json()
        response = client.post("/selection/environment", headers=headers, json=body)
        assert response.status_code == 200, response.text
        proposal = response.json()["proposal"]
        assert proposal["operation"] == "place_selected_feature"
        assert proposal["base_state_sha256"] == composed.version.state_sha256
        assert proposal["admission_id"] == str(composed.source.admission_id)
        assert proposal["render_asset_id"] == str(composed.render.asset_id)
        assert proposal["publication_id"] == str(composed.publication.publication_id)
        assert proposal["feature_id"] == composed.feature_id
        assert proposal["render_batch_id"] == 7
        assert proposal["origin_role"] == "personal"
        assert (
            client.get(f"/world/versions/{composed.version.version_id}", headers=headers).json()
            == before
        )

        original_read = EnvironmentRepository.read_features

        def non_nyc(repository, admission_id, **filters):
            catalog = original_read(repository, admission_id, **filters)
            return replace(catalog, provider_key="not-nyc-open-data")

        with monkeypatch.context() as scoped:
            scoped.setattr(EnvironmentRepository, "read_features", non_nyc)
            unsupported = client.post("/selection/environment", headers=headers, json=body)
        assert unsupported.status_code == 200
        assert unsupported.json()["refusal"]["code"] == "unsupported_source"
        assert transport.call_count == 1

        def non_doitt(repository, admission_id, **filters):
            catalog = original_read(repository, admission_id, **filters)
            feature = {**catalog.features[0], "provider_feature_id": "building-1"}
            return replace(catalog, features=(feature,))

        with monkeypatch.context() as scoped:
            scoped.setattr(EnvironmentRepository, "read_features", non_doitt)
            unsupported_id = client.post("/selection/environment", headers=headers, json=body)
        assert unsupported_id.json()["refusal"]["code"] == "unsupported_source"
        assert transport.call_count == 1

        foreign = client.post("/selection/environment", headers=stranger_headers, json=body)
        absent = client.post(
            "/selection/environment",
            headers=stranger_headers,
            json={**body, "version_id": str(uuid.uuid4())},
        )
        assert foreign.status_code == absent.status_code == 404

    sent = json.dumps(transport.requests[0]["payload"])
    for protected in (
        str(composed.source.admission_id),
        str(composed.publication.publication_id),
        composed.feature_id,
        str(composed.render.asset_id),
        "region-a",
        "personal",
    ):
        assert protected not in sent


def test_environment_proposal_refuses_missing_selection_and_stale_base_without_model(
    composed, spine_schema, monkeypatch
) -> None:
    token = "environment-proposal-closed-token"
    monkeypatch.setenv(
        "EXULANICA_API_TOKENS",
        json.dumps(
            {
                token: {
                    "workspace_id": str(composed.worlds.workspace_id),
                    "actor": str(uuid.uuid4()),
                }
            }
        ),
    )
    composed.worlds.connection.commit()
    transport = FakeTransport()
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
        "utterance": "place it",
        "version_id": str(composed.version.version_id),
        "base_state_sha256": composed.version.state_sha256,
        "admission_id": str(composed.source.admission_id),
        "selected_feature_id": composed.feature_id,
        "region_id": "region-a",
        "transform": {
            "x_mm": 0,
            "y_mm": 0,
            "z_mm": 0,
            "yaw_microradians": 0,
            "scale_milli": 1000,
        },
        "origin_role": "fictional",
    }
    headers = {"Authorization": f"Bearer {token}"}
    with TestClient(create_app(services, verify=False)) as client:
        before = client.get(
            f"/world/versions/{composed.version.version_id}", headers=headers
        ).json()
        missing = client.post(
            "/selection/environment",
            headers=headers,
            json={**body, "selected_feature_id": None},
        )
        stale = client.post(
            "/selection/environment",
            headers=headers,
            json={**body, "base_state_sha256": "f" * 64},
        )
        invalid_region = client.post(
            "/selection/environment",
            headers=headers,
            json={**body, "region_id": "not-a-source-region"},
        )
        invalid_transform = client.post(
            "/selection/environment",
            headers=headers,
            json={
                **body,
                "transform": {**body["transform"], "x_mm": 1_000_000_001},
            },
        )
        validation_failures = (
            (EnvironmentCompositionDenied("compose denied"), 403),
            (EnvironmentSourceWithdrawn("source withdrawn"), 410),
            (EnvironmentBindingDrift("publication drift"), 409),
        )
        for failure, expected_status in validation_failures:
            with monkeypatch.context() as scoped:
                scoped.setattr(
                    WorldObjectRepository,
                    "validate_environment_placement",
                    lambda *_args, refused=failure, **_kwargs: (_ for _ in ()).throw(refused),
                )
                refused = client.post("/selection/environment", headers=headers, json=body)
            assert refused.status_code == expected_status
        render_digest = BlobId.from_hex(composed.render.expected_sha256)
        render_path = composed.store.root / composed.store.key_for(render_digest)
        render_path.unlink()
        unavailable = client.post("/selection/environment", headers=headers, json=body)
        after = client.get(f"/world/versions/{composed.version.version_id}", headers=headers).json()
    assert missing.json()["refusal"]["code"] == "no_selected_feature"
    assert stale.json()["refusal"]["code"] == "stale_version"
    assert invalid_region.status_code == 422
    assert invalid_transform.status_code == 422
    assert unavailable.status_code == 424
    assert after == before
    assert transport.call_count == 0


@dataclass
class MemoryPlace:
    composed: Composed
    entity_id: uuid.UUID
    capture_ids: tuple[uuid.UUID, ...]
    actor: uuid.UUID

    @property
    def session(self) -> Session:
        return Session(self.composed.worlds.workspace_id, self.actor)

    def plan(
        self,
        scope: ContentScope = ContentScope.RELATED,
        *,
        limit: int = 24,
        after=None,
        entity_id: uuid.UUID | None = None,
    ) -> SelectionPlan:
        return SelectionPlan(
            intent=Intent.CONTENT,
            place=PlaceSelector(ids=[entity_id or self.entity_id]),
            content=ContentSelector(scope=scope, after=after),
            limit=limit,
        )

    def run(self, plan: SelectionPlan | None = None):
        selected = plan or self.plan()
        return execute(
            self.composed.worlds.connection,
            validate(self.composed.worlds.connection, selected, self.session),
            store=self.composed.store,
        )


def _memory_capture(
    composed: Composed,
    photo_dir,
    *,
    index: int,
    actor: uuid.UUID,
    entity_id: uuid.UUID | None = None,
) -> tuple[uuid.UUID, uuid.UUID]:
    repository = IngestRepository(composed.worlds.connection, composed.worlds.workspace_id)
    payload = copy.deepcopy(DEFAULT_PAYLOAD)
    payload["proposed_place"]["label"] = "Iceland"
    pipeline = PhotoIngestPipeline(
        repository,
        composed.store,
        vision=CountingVisionModel(payload=payload),
    )
    outcome = ingest_observed(
        pipeline,
        repository,
        write_photo(
            photo_dir,
            f"iceland-memory-{index}.jpg",
            when=f"2026:06:{index + 1:02d} 10:00:00",
            size=(160 + index, 100),
        ),
    )
    assert outcome.error is None, outcome.error
    occurrence = composed.worlds.connection.execute(
        "select occurrence_id from occurrence "
        "where workspace_id=%s and capture_id=%s and class='place'",
        (composed.worlds.workspace_id, outcome.capture_id),
    ).fetchone()
    assert occurrence is not None
    identity = IdentityRepository(composed.worlds.connection, composed.worlds.workspace_id)
    if entity_id is None:
        named = name_occurrence(
            identity,
            AssertionWriter(composed.worlds.connection, composed.worlds.workspace_id),
            occurrence_id=occurrence["occurrence_id"],
            display_name="Iceland",
            actor=actor,
        )
        entity_id = named.entity_id
    else:
        confirm_link(
            identity,
            occurrence_id=occurrence["occurrence_id"],
            entity_id=entity_id,
            actor=actor,
        )
    return outcome.capture_id, entity_id


@pytest.fixture
def memory_place(composed, photo_dir) -> MemoryPlace:
    actor = uuid.uuid4()
    first, entity_id = _memory_capture(composed, photo_dir, index=1, actor=actor)
    second, confirmed = _memory_capture(
        composed,
        photo_dir,
        index=2,
        actor=actor,
        entity_id=entity_id,
    )
    assert confirmed == entity_id
    return MemoryPlace(composed, entity_id, (first, second), actor)


def _confirm_bridge(memory: MemoryPlace):
    return PlaceBridgeRepository(
        memory.composed.worlds.connection, memory.composed.worlds.workspace_id
    ).confirm(
        place_id=memory.composed.source.place_id,
        entity_id=memory.entity_id,
        actor=memory.actor,
        reason="The account holder confirmed these identities refer to the same place.",
    )


def test_place_bridge_is_confirmed_readable_revocable_and_append_only(memory_place) -> None:
    repository = PlaceBridgeRepository(
        memory_place.composed.worlds.connection,
        memory_place.composed.worlds.workspace_id,
    )
    confirmed = _confirm_bridge(memory_place)
    assert confirmed.place_id != confirmed.entity_id
    assert repository.confirmed() == (confirmed,)

    revoked = repository.revoke(
        confirmed.decision_id,
        actor=memory_place.actor,
        reason="The account holder corrected the place identity.",
    )
    assert revoked.decision == "revoked"
    assert revoked.supersedes_decision_id == confirmed.decision_id
    assert repository.confirmed() == ()
    assert [
        item.decision
        for item in repository.history(place_id=confirmed.place_id, entity_id=confirmed.entity_id)
    ] == ["confirmed", "revoked"]
    with pytest.raises(SelectionRejected) as stale:
        repository.revoke(confirmed.decision_id, actor=memory_place.actor)
    assert stale.value.code is RejectionCode.UNKNOWN_REFERENCE


def test_place_bridge_rejects_wrong_class_equal_ids_and_foreign_rows(memory_place) -> None:
    repository = PlaceBridgeRepository(
        memory_place.composed.worlds.connection,
        memory_place.composed.worlds.workspace_id,
    )
    object_id = uuid.uuid4()
    memory_place.composed.worlds.connection.execute(
        "insert into entity(entity_id,workspace_id,class) values(%s,%s,'object')",
        (object_id, memory_place.composed.worlds.workspace_id),
    )
    with pytest.raises(SelectionRejected) as wrong_class:
        repository.confirm(
            place_id=memory_place.composed.source.place_id,
            entity_id=object_id,
            actor=memory_place.actor,
        )
    assert wrong_class.value.code is RejectionCode.MALFORMED_PLAN
    with pytest.raises(SelectionRejected, match="must remain distinct"):
        repository.confirm(
            place_id=memory_place.composed.source.place_id,
            entity_id=memory_place.composed.source.place_id,
            actor=memory_place.actor,
        )


def test_bridge_and_related_results_are_hidden_across_workspaces(
    memory_place, spine_schema
) -> None:
    decision = _confirm_bridge(memory_place)
    memory_place.composed.worlds.connection.commit()
    psycopg_module, scratch = spine_schema
    connection = open_scratch_connection(psycopg_module, scratch)
    stranger = uuid.uuid4()
    WorkspaceScope(connection, stranger)
    try:
        repository = PlaceBridgeRepository(connection, stranger)
        assert repository.confirmed() == ()
        with pytest.raises(SelectionRejected) as hidden:
            repository.revoke(decision.decision_id, actor=uuid.uuid4())
        assert hidden.value.code is RejectionCode.UNKNOWN_REFERENCE
    finally:
        connection.close()


def test_unconfirmed_same_name_does_not_bridge_by_label(memory_place, photo_dir) -> None:
    _confirm_bridge(memory_place)
    _capture, ambiguous_entity = _memory_capture(
        memory_place.composed,
        photo_dir,
        index=3,
        actor=memory_place.actor,
    )
    assert ambiguous_entity != memory_place.entity_id
    result = memory_place.run(memory_place.plan(entity_id=ambiguous_entity))
    assert {item.result_kind for item in result.content} == {"memory_capture"}
    assert all(item.canonical_place_id is None for item in result.content)


def test_broad_related_place_selection_unions_memories_imports_and_authored_versions(
    memory_place,
) -> None:
    _confirm_bridge(memory_place)
    _add(memory_place.composed, memory_place.composed.placement("environment:whole"))
    _add(
        memory_place.composed,
        memory_place.composed.placement("environment:feature", feature=True),
    )
    result = memory_place.run()
    kinds = {item.result_kind for item in result.content}
    assert kinds == {
        "memory_capture",
        "admitted_environment_source",
        "admitted_environment_feature",
        "authored_environment_instance",
    }
    assert sum(item.result_kind == "memory_capture" for item in result.content) == 2
    assert sum(item.result_kind == "authored_environment_instance" for item in result.content) == 2
    authored = [
        item for item in result.content if item.result_kind == "authored_environment_instance"
    ]
    assert all(item.match_reason == "authored_from_canonical_place" for item in authored)
    assert all(item.world_id and item.version_id for item in authored)
    assert all(
        any(value.startswith("admission:") for value in item.lineage_ids) for item in authored
    )


def test_memories_only_excludes_imports_and_fantasy_and_never_infers_a_visit(
    memory_place,
) -> None:
    _confirm_bridge(memory_place)
    _add(memory_place.composed, memory_place.composed.placement("environment:fantasy"))
    broad = memory_place.run()
    assert all(
        item.personal_visit_evidence == (item.result_kind == "memory_capture")
        for item in broad.content
    )
    fantasy = [
        item for item in broad.content if item.result_kind == "authored_environment_instance"
    ]
    assert [item.authored_role for item in fantasy] == ["fictional"]
    memories = memory_place.run(memory_place.plan(ContentScope.MEMORIES_ONLY))
    assert len(memories.content) == 2
    assert {item.result_kind for item in memories.content} == {"memory_capture"}
    assert {item.origin_kind for item in memories.content} == {"personal"}


def test_unavailable_bytes_are_labeled_but_withdrawn_metadata_and_counts_are_hidden(
    memory_place,
) -> None:
    _confirm_bridge(memory_place)
    _add(memory_place.composed, memory_place.composed.placement("environment:available"))
    render_digest = BlobId.from_hex(memory_place.composed.render.expected_sha256)
    render_path = memory_place.composed.store.root / memory_place.composed.store.key_for(
        render_digest
    )
    render_path.unlink()
    unavailable = memory_place.run()
    by_kind = {item.result_kind: item.availability for item in unavailable.content}
    assert by_kind["admitted_environment_source"] == "available"
    assert by_kind["admitted_environment_feature"] == "unavailable_bytes"
    assert by_kind["authored_environment_instance"] == "unavailable_bytes"

    memory_place.composed.environments.withdraw("source", memory_place.composed.source.admission_id)
    hidden = memory_place.run()
    assert hidden.total_matched == 2
    assert {item.result_kind for item in hidden.content} == {"memory_capture"}


def test_content_pages_are_bounded_stable_and_do_not_collapse_distinct_items(
    memory_place,
) -> None:
    _confirm_bridge(memory_place)
    _add(memory_place.composed, memory_place.composed.placement("environment:variation-a"))
    _add(memory_place.composed, memory_place.composed.placement("environment:variation-b"))
    page = memory_place.run(memory_place.plan(limit=2))
    total = page.total_matched
    seen: list[tuple[str, str]] = []
    while True:
        seen.extend((item.result_kind, item.source_id) for item in page.content)
        if page.next_page is None:
            break
        page = memory_place.run(memory_place.plan(limit=2, after=page.next_page))
        assert page.total_matched == total
    assert total == 6
    assert len(seen) == total
    assert len(set(seen)) == total
    assert sum(kind == "memory_capture" for kind, _source in seen) == 2
    assert sum(kind == "authored_environment_instance" for kind, _source in seen) == 2


def test_revoked_bridge_immediately_stops_canonical_and_authored_traversal(memory_place) -> None:
    decision = _confirm_bridge(memory_place)
    _add(memory_place.composed, memory_place.composed.placement("environment:revoked-link"))
    assert memory_place.run().total_matched > len(memory_place.capture_ids)
    PlaceBridgeRepository(
        memory_place.composed.worlds.connection,
        memory_place.composed.worlds.workspace_id,
    ).revoke(decision.decision_id, actor=memory_place.actor)
    current = memory_place.run()
    assert current.total_matched == len(memory_place.capture_ids)
    assert {item.result_kind for item in current.content} == {"memory_capture"}
    assert all(item.canonical_place_id is None for item in current.content)


def test_authenticated_place_bridge_routes_create_list_and_revoke(
    memory_place, spine_schema, monkeypatch
) -> None:
    token = "unified-place-bridge-owner-token"
    monkeypatch.setenv(
        "EXULANICA_API_TOKENS",
        json.dumps(
            {
                token: {
                    "workspace_id": str(memory_place.composed.worlds.workspace_id),
                    "actor": str(memory_place.actor),
                }
            }
        ),
    )
    _add(
        memory_place.composed,
        memory_place.composed.placement("environment:api-retrieval"),
    )
    memory_place.composed.worlds.connection.commit()
    _psycopg, scratch = spine_schema
    database = scratch_database(scratch)
    services = Services(
        database=database,
        readonly_database=database,
        store=memory_place.composed.store,
        tokens=load_token_directory(),
        executor_shares_the_write_role=True,
        model_client=None,
    )
    headers = {"Authorization": f"Bearer {token}"}
    body = {
        "canonical_place_id": str(memory_place.composed.source.place_id),
        "memory_place_entity_id": str(memory_place.entity_id),
        "reason": "Confirmed by the account holder.",
    }
    with TestClient(create_app(services, verify=False)) as client:
        assert client.post("/selection/place-bridges", json=body).status_code in {401, 403}
        unlinked = client.post(
            "/selection/ask",
            json={
                "question": "What building is this?",
                "city_context": {
                    "admission_id": str(memory_place.composed.source.admission_id),
                    "feature_id": memory_place.composed.feature_id,
                },
            },
            headers=headers,
        )
        assert unlinked.status_code == 200, unlinked.text
        assert unlinked.json()["deterministic"] is True
        assert unlinked.json()["execution"]["calls"] == []
        assert "Google supplied no identity" in unlinked.json()["answer"]["clauses"][0]["text"]
        assert "no confirmed memory-place bridge" in unlinked.json()["answer"]["clauses"][1]["text"]
        created = client.post("/selection/place-bridges", json=body, headers=headers)
        assert created.status_code == 201, created.text
        decision = created.json()
        selected = client.post(
            "/selection",
            json={
                "intent": "content",
                "place": {"ids": [str(memory_place.entity_id)]},
                "content": {"scope": "related"},
            },
            headers=headers,
        )
        assert selected.status_code == 200, selected.text
        assert {item["result_kind"] for item in selected.json()["content"]} == {
            "memory_capture",
            "admitted_environment_source",
            "admitted_environment_feature",
            "authored_environment_instance",
        }
        listed = client.get("/selection/place-bridges", headers=headers)
        assert listed.status_code == 200
        assert listed.json() == [decision]
        revoked = client.post(
            f"/selection/place-bridges/{decision['decision_id']}/revoke",
            json={"reason": "Corrected by the account holder."},
            headers=headers,
        )
        assert revoked.status_code == 200, revoked.text
        assert revoked.json()["decision"] == "revoked"
        assert client.get("/selection/place-bridges", headers=headers).json() == []
