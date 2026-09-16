"""The initial structural writer preserves the composed sources under PostgreSQL."""

from __future__ import annotations

import json
import uuid
from dataclasses import replace

import pytest
from exulanica.api.app import create_app
from exulanica.api.authorisation import load_token_directory
from exulanica.api.services import Services
from exulanica.ingest.pipeline import PhotoIngestPipeline
from exulanica.orchestration.judge_seed import prepare_sandbox_world
from exulanica.orchestration.reference_world import compose_reference_sources
from exulanica.store.local import LocalContentAddressedStore
from exulanica.world import (
    InvalidStructuralData,
    TopologyContract,
    TopologySourceSlot,
    WorldObjectRepository,
    WorldStructureRepository,
    WorldStyleRepository,
)
from exulanica.world.bootstrap import bootstrap_world
from exulanica.world.composed import UNPLACED_REASON, composed_candidate
from exulanica.world.structure import validate_candidate
from fastapi.testclient import TestClient

from conftest import write_photo
from test_world_objects_api import CUBE, TOKEN, transform
from tests_support_api import EVERY_PERMISSION, scratch_database

pytestmark = pytest.mark.postgres


@pytest.fixture
def composed(repository, photo_dir, tmp_path):
    store = LocalContentAddressedStore(tmp_path / "blobs")
    pipeline = PhotoIngestPipeline(repository, store, vision=None)
    for index in range(3):
        result = pipeline.ingest_file(
            write_photo(photo_dir, f"source-{index}.jpg", size=(160 + index, 100))
        )
        assert result.error is None
    rows = repository.connection.execute(
        "select capture_id,blob_sha256 from capture where workspace_id=%s order by capture_id",
        (repository.workspace_id,),
    ).fetchall()
    options = dict(
        region_id="region-a",
        source_manifest_sha256="ab" * 32,
        captures=[
            (r["capture_id"], bytes(r["blob_sha256"]).hex(), str(i)) for i, r in enumerate(rows)
        ],
    )
    compose_reference_sources(repository, **options)
    return store, options


@pytest.fixture
def bootstrap_api(repository, composed, spine_schema, monkeypatch):
    actor = uuid.uuid4()
    monkeypatch.setenv(
        "EXULANICA_API_TOKENS",
        json.dumps(
            {
                TOKEN: {
                    "workspace_id": str(repository.workspace_id),
                    "actor": str(actor),
                    "permissions": EVERY_PERMISSION,
                },
            }
        ),
    )
    repository.connection.commit()
    database = scratch_database(spine_schema[1])
    services = Services(
        database=database,
        readonly_database=database,
        store=composed[0],
        tokens=load_token_directory(),
        executor_shares_the_write_role=True,
        model_client=None,
    )
    with TestClient(create_app(services, verify=False)) as client:
        client.headers["Authorization"] = f"Bearer {TOKEN}"
        yield client


def counts(repository):
    return {
        table: repository.connection.execute(f"select count(*) as n from {table}").fetchone()["n"]
        for table in (
            "world_structure_snapshot",
            "world_structure_preview",
            "world_structure_audit_event",
            "world_alternate_version",
            "world_topology_contract",
            "world_topology_source",
            "world_style_version",
        )
    }


def test_bootstrap_keeps_every_source_and_object_survives_recompose(
    repository, composed, bootstrap_api
):
    client = bootstrap_api
    before = client.get("/world/source-media").json()
    assert len(before) == 3
    styles_before = client.get("/world/styles/current").json()
    state_before = repository.connection.execute("select * from world_style_state").fetchall()
    style_count = counts(repository)["world_style_version"]
    digest = styles_before["current_topology_digest"]
    first = client.post("/world/versions/bootstrap", json={"base_topology_digest": digest})
    assert first.status_code == 200, first.text
    opened = first.json()
    assert opened["snapshot"] == "applied"
    assert opened["version"] == "created"
    assert client.get("/world/styles/current").json() == styles_before
    assert (
        repository.connection.execute("select * from world_style_state").fetchall() == state_before
    )
    assert counts(repository)["world_style_version"] == style_count
    assert client.get("/world/source-media").json() == before
    assert client.get("/world/styles/current").json()["current_topology_digest"] == digest
    snapshot = WorldStructureRepository(repository.connection, repository.workspace_id).current()
    elements = snapshot.candidate.topology["elements"]
    contract = WorldStyleRepository(
        repository.connection, repository.workspace_id
    ).current_topology_contract()
    assert {(e["lineage"]["slot_key"], e["evidence"]["span_id"]) for e in elements} == {
        (s.slot_key, str(s.evidence_span_id)) for s in contract.source_slots
    }
    version = client.post(
        f"/world/versions/{opened['version_id']}/objects",
        json={
            "base_state_sha256": opened["state_sha256"],
            "object_id": "object:bootstrap-marker",
            "asset_sha256": CUBE,
            "region_id": "region-a",
            "transform": transform(),
            "origin_role": "fictional",
        },
    )
    assert version.status_code == 201, version.text
    compose_reference_sources(repository, **{**composed[1], "source_manifest_sha256": "cd" * 32})
    repository.connection.commit()
    assert client.get("/world/source-media").json() == before
    assert client.get(f"/world/versions/{opened['version_id']}").json() == version.json()
    assert version.json()["objects"][0]["removed"] is False


def test_second_bootstrap_and_seed_are_noops(repository, bootstrap_api):
    client = bootstrap_api
    body = {
        "base_topology_digest": client.get("/world/styles/current").json()[
            "current_topology_digest"
        ]
    }
    first = client.post("/world/versions/bootstrap", json=body).json()
    before = counts(repository)
    second = client.post("/world/versions/bootstrap", json={**body, "title": "Ignored retry"})
    assert second.status_code == 200, second.text
    assert second.json() == {**first, "snapshot": "reused", "version": "reused"}
    assert counts(repository) == before
    seeded = prepare_sandbox_world(
        repository.connection, workspace_id=repository.workspace_id, actor=uuid.uuid4()
    )
    assert seeded == second.json()
    assert counts(repository) == before


def test_stale_digest_refuses_before_and_after_snapshot(repository, bootstrap_api):
    client = bootstrap_api
    for _ in range(2):
        before = counts(repository)
        refused = client.post("/world/versions/bootstrap", json={"base_topology_digest": "stale"})
        assert refused.status_code == 409, refused.text
        assert refused.json()["code"] == "protected_topology_conflict"
        assert counts(repository) == before
        digest = client.get("/world/styles/current").json()["current_topology_digest"]
        assert (
            client.post(
                "/world/versions/bootstrap", json={"base_topology_digest": digest}
            ).status_code
            == 200
        )


def test_missing_and_world_owned_slots_and_historical_topologies_are_preserved(
    repository, composed
):
    styles = WorldStyleRepository(repository.connection, repository.workspace_id)
    original = styles.current_topology_contract()
    contract = replace(
        original,
        topology_digest="new-current",
        source_slots=(
            *original.source_slots,
            TopologySourceSlot(
                uuid.uuid4(), "missing-region", "region-a", None, "No source chosen"
            ),
            TopologySourceSlot(uuid.uuid4(), "missing-world", None, None, "No world source chosen"),
        ),
    )
    styles.register_topology(contract)
    before = styles.source_media(composed[0])
    prepare_sandbox_world(
        repository.connection, workspace_id=repository.workspace_id, actor=uuid.uuid4()
    )
    assert styles.current_topology_contract() == replace(
        contract, source_slots=tuple(sorted(contract.source_slots, key=lambda s: s.source_id))
    )
    assert styles.source_media(composed[0]) == before
    snapshot = WorldStructureRepository(repository.connection, repository.workspace_id).current()
    assert len(snapshot.candidate.topology["elements"]) == 5


def _coincident_zeros(candidate):
    """The composed candidate with every unplaced identity given the origin instead."""
    placement = {
        key: value
        for key, value in candidate.placement.items()
        if key not in {"unplaced_elements", "unplaced_destinations"}
    }
    placement["elements"] = [
        {
            "element_id": item["element_id"],
            "x_mm": 0,
            "y_mm": 0,
            "z_mm": 0,
            "yaw_microradians": 0,
            "scale_milli": 1_000,
        }
        for item in candidate.placement["unplaced_elements"]
    ]
    placement["destinations"] = [
        {"destination_id": item["destination_id"], "x_mm": 0, "y_mm": 0, "z_mm": 0}
        for item in candidate.placement["unplaced_destinations"]
    ]
    return replace(candidate, placement=placement)


def _dropped_last_source(candidate):
    return replace(
        candidate,
        topology={**candidate.topology, "elements": candidate.topology["elements"][:-1]},
        placement={
            **candidate.placement,
            "unplaced_elements": candidate.placement["unplaced_elements"][:-1],
        },
    )


@pytest.mark.parametrize("alter", [_dropped_last_source, _coincident_zeros])
def test_preservation_path_refuses_changed_candidate(repository, composed, alter):
    # Coincident zeros is a valid structural candidate, and it is still refused: a position
    # nobody authored is not the composed sources, even when every coordinate is the same.
    styles = WorldStyleRepository(repository.connection, repository.workspace_id)
    contract = styles.current_topology_contract()
    altered = alter(composed_candidate(contract, "ab" * 32, "cd" * 32))
    structures = WorldStructureRepository(repository.connection, repository.workspace_id)
    preview = structures.preview(altered, proposed_by=uuid.uuid4())
    with pytest.raises(InvalidStructuralData, match="exact composed sources"):
        structures.apply(
            preview.preview_id,
            base_snapshot_id=None,
            base_graph_sha256=None,
            base_reconstruction_sha256=None,
            committed_by=uuid.uuid4(),
            base_composed_topology_digest=contract.topology_digest,
        )
    assert structures.current() is None
    assert styles.current_topology_contract() == contract


def test_bootstrap_writes_every_source_and_destination_as_explicitly_unplaced(repository, composed):
    styles = WorldStyleRepository(repository.connection, repository.workspace_id)
    bootstrap_world(
        repository.connection,
        workspace_id=repository.workspace_id,
        actor=uuid.uuid4(),
        base_topology_digest=styles.current_topology_digest(),
    )
    snapshot = WorldStructureRepository(repository.connection, repository.workspace_id).current()
    topology = snapshot.candidate.topology
    placement = snapshot.candidate.placement
    assert placement["elements"] == []
    assert placement["destinations"] == []
    assert placement["unplaced_elements"] == [
        {"element_id": element["element_id"], "reason": UNPLACED_REASON}
        for element in topology["elements"]
    ]
    assert placement["unplaced_destinations"] == [
        {"destination_id": destination["destination_id"], "reason": UNPLACED_REASON}
        for destination in topology["navigation"]["destinations"]
    ]
    assert topology["navigation"]["edges"] == []
    assert not {"x_mm", "y_mm", "z_mm"} & set(json.dumps(placement).replace('"', " ").split())
    rows = repository.connection.execute(
        "select element_id,placement_sha256 from world_structure_snapshot_element "
        "where snapshot_id=%s order by element_id",
        (snapshot.snapshot_id,),
    ).fetchall()
    assert [row["element_id"] for row in rows] == [e["element_id"] for e in topology["elements"]]


def _regions_contract(*regions):
    return TopologyContract(
        "regions",
        tuple(regions),
        tuple(
            TopologySourceSlot(uuid.uuid4(), f"slot-{region}", region, None, "No source chosen")
            for region in regions
        ),
    )


def test_separate_regions_get_no_route_between_them():
    # Adjacency in a sorted list is not adjacency in a world. Two regions nobody has related stay
    # unconnected, and a candidate that asserts an edge to a destination with no position fails.
    candidate = composed_candidate(_regions_contract("region-b", "region-a"), "ab" * 32, "cd" * 32)
    validate_candidate(candidate)
    assert candidate.topology["navigation"]["edges"] == []
    assert [item["destination_id"] for item in candidate.placement["unplaced_destinations"]] == [
        "destination:region-a",
        "destination:region-b",
    ]
    routed = replace(
        candidate,
        topology={
            **candidate.topology,
            "navigation": {
                **candidate.topology["navigation"],
                "edges": [
                    {
                        "from": "destination:region-a",
                        "to": "destination:region-b",
                        "kind": "field",
                        "max_slope_millidegrees": 0,
                    }
                ],
            },
        },
    )
    with pytest.raises(InvalidStructuralData, match="has no position"):
        validate_candidate(routed)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda p: {**p, "unplaced_destinations": []}, "omitted when nothing is unplaced"),
        (
            lambda p: {**p, "unplaced_elements": p["unplaced_elements"][::-1]},
            "must be sorted",
        ),
        (
            lambda p: {**p, "unplaced_elements": [{**p["unplaced_elements"][0], "reason": " "}]},
            "reason must be a non-empty string",
        ),
        (
            lambda p: {
                **p,
                "elements": [
                    {
                        "element_id": p["unplaced_elements"][0]["element_id"],
                        "x_mm": 0,
                        "y_mm": 0,
                        "z_mm": 0,
                        "yaw_microradians": 0,
                        "scale_milli": 1_000,
                    }
                ],
            },
            "partition the topology elements",
        ),
        # A destination in neither list is taken as positioned, so it needs a route first.
        (
            lambda p: {k: v for k, v in p.items() if k != "unplaced_destinations"},
            "unreachable",
        ),
        (
            lambda p: {**p, "unplaced_destinations": p["unplaced_destinations"][:1]},
            "partition the navigation destinations",
        ),
    ],
)
def test_unplaced_lists_have_one_encoding_and_cover_each_identity_once(change, message):
    candidate = composed_candidate(_regions_contract("region-a", "region-b"), "ab" * 32, "cd" * 32)
    with pytest.raises(InvalidStructuralData, match=message):
        validate_candidate(replace(candidate, placement=change(dict(candidate.placement))))


def test_a_collision_body_cannot_be_unplaced():
    candidate = composed_candidate(_regions_contract("region-a"), "ab" * 32, "cd" * 32)
    element = {**candidate.topology["elements"][0], "collision": {"kind": "circle", "radius_mm": 1}}
    with pytest.raises(InvalidStructuralData, match="collision body but no position"):
        validate_candidate(
            replace(candidate, topology={**candidate.topology, "elements": [element]})
        )


def test_failed_version_creation_rolls_back_snapshot(repository, composed):
    digest = WorldStyleRepository(
        repository.connection, repository.workspace_id
    ).current_topology_digest()
    before = counts(repository)
    from exulanica.world import InvalidObjectData

    with pytest.raises(InvalidObjectData):
        bootstrap_world(
            repository.connection,
            workspace_id=repository.workspace_id,
            actor=uuid.uuid4(),
            base_topology_digest=digest,
            title=" ",
        )
    assert counts(repository) == before
    assert WorldObjectRepository(repository.connection, repository.workspace_id).versions() == ()


def test_existing_multiple_versions_returns_latest_without_writes(repository, composed):
    actor = uuid.uuid4()
    styles = WorldStyleRepository(repository.connection, repository.workspace_id)
    args = dict(
        workspace_id=repository.workspace_id,
        actor=actor,
        base_topology_digest=styles.current_topology_digest(),
    )
    first = bootstrap_world(repository.connection, **args)
    objects = WorldObjectRepository(repository.connection, repository.workspace_id)
    latest = objects.create_version(
        source_snapshot_id=uuid.UUID(first["snapshot_id"]),
        title="Newest alternate",
        created_by=actor,
    )
    before = counts(repository)
    result = bootstrap_world(repository.connection, **args)
    assert result["version_id"] == str(latest.version_id)
    assert counts(repository) == before


def test_concurrent_bootstrap_serializes_to_one_snapshot_and_version(
    repository, composed, spine_schema
):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from test_world_objects_postgres import another_connection

    digest = WorldStyleRepository(
        repository.connection, repository.workspace_id
    ).current_topology_digest()
    repository.connection.commit()
    ready = Barrier(2)

    def run():
        with another_connection(spine_schema, repository.workspace_id) as connection:
            ready.wait(timeout=10)
            result = bootstrap_world(
                connection,
                workspace_id=repository.workspace_id,
                actor=uuid.uuid4(),
                base_topology_digest=digest,
            )
            connection.commit()
            return result

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(run) for _ in range(2)]
        results = [future.result(timeout=20) for future in futures]
    assert len({r["snapshot_id"] for r in results}) == 1
    assert len({r["version_id"] for r in results}) == 1
    assert {r["snapshot"] for r in results} == {"applied", "reused"}
    assert counts(repository)["world_structure_snapshot"] == 1
    assert counts(repository)["world_alternate_version"] == 1


def test_deleted_source_cannot_bootstrap_or_extend_an_existing_snapshot(
    repository, composed, bootstrap_api
):
    client = bootstrap_api
    digest = client.get("/world/styles/current").json()["current_topology_digest"]
    body = {"base_topology_digest": digest}
    assert client.post("/world/versions/bootstrap", json=body).status_code == 200
    repository.insert_tombstone(
        scope="capture",
        capture_id=composed[1]["captures"][0][0],
        requested_by=uuid.uuid4(),
        reason="test withdrawal",
    )
    repository.connection.commit()
    before = counts(repository)
    refused = client.post("/world/versions/bootstrap", json=body)
    assert refused.status_code == 409, refused.text
    assert refused.json()["code"] == "invalidated_source_version"
    assert counts(repository) == before


def test_invalidated_oldest_version_does_not_hide_latest_live_version(repository, composed):
    from exulanica.world import PlacementMigration

    actor = uuid.uuid4()
    styles = WorldStyleRepository(repository.connection, repository.workspace_id)
    contract = styles.current_topology_contract()
    first = bootstrap_world(
        repository.connection,
        workspace_id=repository.workspace_id,
        actor=actor,
        base_topology_digest=contract.topology_digest,
    )
    withdrawn = composed[1]["captures"][0][0]
    span = repository.connection.execute(
        "select e.span_id from evidence_span e join capture c "
        "on c.workspace_id=e.workspace_id and c.blob_sha256=e.blob_sha256 "
        "where c.capture_id=%s and e.region is null",
        (withdrawn,),
    ).fetchone()["span_id"]
    repository.insert_tombstone(
        scope="capture", capture_id=withdrawn, requested_by=actor, reason="test withdrawal"
    )
    live_contract = replace(
        contract, source_slots=tuple(s for s in contract.source_slots if s.evidence_span_id != span)
    )
    candidate = replace(
        composed_candidate(live_contract, "ab" * 32, "cd" * 32),
        placement_migrations=(
            PlacementMigration(uuid.uuid4(), "region-a", "Remove withdrawn source"),
        ),
    )
    structures = WorldStructureRepository(repository.connection, repository.workspace_id)
    preview = structures.preview(candidate, proposed_by=actor)
    snapshot = structures.apply(
        preview.preview_id,
        base_snapshot_id=preview.base_snapshot_id,
        base_graph_sha256=preview.base_graph_sha256,
        base_reconstruction_sha256=preview.base_reconstruction_sha256,
        committed_by=actor,
    )
    objects = WorldObjectRepository(repository.connection, repository.workspace_id)
    latest = objects.create_version(
        source_snapshot_id=snapshot.snapshot_id, title="Live alternate", created_by=actor
    )
    assert objects.version(uuid.UUID(first["version_id"])).source_invalidated
    before = counts(repository)
    result = bootstrap_world(
        repository.connection,
        workspace_id=repository.workspace_id,
        actor=actor,
        base_topology_digest=styles.current_topology_digest(),
    )
    assert result["version_id"] == str(latest.version_id)
    assert counts(repository) == before


def test_existing_snapshot_opens_only_the_first_alternate(repository, composed):
    actor = uuid.uuid4()
    styles = WorldStyleRepository(repository.connection, repository.workspace_id)
    contract = styles.current_topology_contract()
    structures = WorldStructureRepository(repository.connection, repository.workspace_id)
    preview = structures.preview(
        composed_candidate(contract, "ab" * 32, "cd" * 32), proposed_by=actor
    )
    snapshot = structures.apply(
        preview.preview_id,
        base_snapshot_id=None,
        base_graph_sha256=None,
        base_reconstruction_sha256=None,
        committed_by=actor,
        base_composed_topology_digest=contract.topology_digest,
    )
    before = counts(repository)
    result = bootstrap_world(
        repository.connection,
        workspace_id=repository.workspace_id,
        actor=actor,
        base_topology_digest=contract.topology_digest,
    )
    assert result["snapshot"] == "reused"
    assert result["snapshot_id"] == str(snapshot.snapshot_id)
    assert result["version"] == "created"
    assert counts(repository) == {**before, "world_alternate_version": 1}


def test_bootstrap_requires_authentication_and_refuses_caller_topology(repository, bootstrap_api):
    before = counts(repository)
    unauthorized = bootstrap_api.post(
        "/world/versions/bootstrap",
        headers={"Authorization": "Bearer unknown"},
        json={"base_topology_digest": "anything"},
    )
    assert unauthorized.status_code == 401
    forbidden_shape = bootstrap_api.post(
        "/world/versions/bootstrap",
        json={
            "base_topology_digest": "anything",
            "source_slots": [],
        },
    )
    assert forbidden_shape.status_code == 422
    assert counts(repository) == before


def test_bootstrap_ignores_other_worlds_and_historical_regions(repository, composed):
    from exulanica.world import TopologyContract

    styles = WorldStyleRepository(repository.connection, repository.workspace_id)
    current = styles.current_topology_contract()
    historical = replace(
        current, topology_digest="historical", region_ids=("historical-region",), source_slots=()
    )
    styles.register_topology(historical)
    styles.register_topology(current)
    other = WorldStyleRepository(
        repository.connection, repository.workspace_id, world_id="other-world"
    )
    other.register_topology(
        TopologyContract(
            "other",
            ("other-region",),
            (
                TopologySourceSlot(
                    uuid.uuid4(),
                    "other-source",
                    "other-region",
                    current.source_slots[0].evidence_span_id,
                    None,
                ),
            ),
            world_id="other-world",
        )
    )
    opened = bootstrap_world(
        repository.connection,
        workspace_id=repository.workspace_id,
        actor=uuid.uuid4(),
        base_topology_digest=current.topology_digest,
    )
    assert opened["regions"] == ["region-a"]
    snapshot = WorldStructureRepository(repository.connection, repository.workspace_id).current()
    assert len(snapshot.candidate.topology["elements"]) == 3
    assert styles.current_topology_contract() == current
    assert other.current_topology_digest() == "other"
    assert (
        WorldStructureRepository(
            repository.connection, repository.workspace_id, world_id="other-world"
        ).current()
        is None
    )
