"""Live PostgreSQL proofs for structural world authority and its protected boundaries."""

from __future__ import annotations

import copy
import uuid

import psycopg
import pytest
from exulanica.ingest.pipeline import PhotoIngestPipeline
from exulanica.store.local import LocalContentAddressedStore
from exulanica.world import (
    InvalidStructuralData,
    PlacementMigration,
    ProposalOrigin,
    ProposalProvenance,
    SpatialCandidate,
    StaleStructuralBase,
    StyleProposal,
    StyleReference,
    StyleScope,
    WorldStructureRepository,
    WorldStyleRepository,
)

from conftest import write_photo
from world_structure_fixtures import structural_candidate
from world_support import registered_world

pytestmark = pytest.mark.postgres


def fixture_structures(repository) -> WorldStructureRepository:
    """The structure of the registered fixture world the synthetic candidates are written for."""
    world_id = registered_world(repository.connection, repository.workspace_id)
    return WorldStructureRepository(
        repository.connection, repository.workspace_id, world_id=world_id
    )


def apply_candidate(
    structures: WorldStructureRepository,
    candidate: SpatialCandidate,
    *,
    actor: uuid.UUID | None = None,
):
    actor = actor or uuid.uuid4()
    preview = structures.preview(candidate, proposed_by=actor)
    return structures.apply(
        preview.preview_id,
        base_snapshot_id=preview.base_snapshot_id,
        base_graph_sha256=preview.base_graph_sha256,
        base_reconstruction_sha256=preview.base_reconstruction_sha256,
        committed_by=actor,
    )


def test_preview_apply_writes_immutable_sections_lineage_and_package_projection(repository):
    structures = fixture_structures(repository)
    preview = structures.preview(structural_candidate(), proposed_by=uuid.uuid4())
    assert preview.base_snapshot_id is None
    assert preview.validation_checks == {
        "schema_version": 1,
        "canonical_sha256": "pass",
        "stable_identity": "pass",
        "reachability": "pass",
        "collision": "pass",
        "evidence_liveness": "pass",
        "placement_migrations": "pass",
    }
    assert preview.protected_diff["regions"]["added"] == ["region-a", "region-b"]

    snapshot = structures.apply(
        preview.preview_id,
        base_snapshot_id=None,
        base_graph_sha256=None,
        base_reconstruction_sha256=None,
        committed_by=uuid.uuid4(),
    )
    assert snapshot.revision == 0
    assert structures.current() == snapshot
    assert structures.effective_current() == snapshot
    assert snapshot.package_projection["snapshot_sha256"] == snapshot.digests.snapshot_sha256
    assert [item["path"] for item in snapshot.package_projection["sections"]] == [
        "world/topology.json",
        "world/layout.json",
        "world/placement.json",
        "world/neighborhood.json",
    ]
    identities = repository.connection.execute(
        "select element_id,owner_kind,owner_id from world_structure_element_identity "
        "order by element_id"
    ).fetchall()
    assert [(row["owner_kind"], row["owner_id"]) for row in identities] == [
        ("region", "region-a"),
        ("region", "region-b"),
    ]
    with pytest.raises(psycopg.errors.IntegrityConstraintViolation):
        repository.connection.execute(
            "update world_structure_snapshot set revision=99 where snapshot_id=%s",
            (snapshot.snapshot_id,),
        )


def test_two_initial_or_stale_composers_cannot_both_become_current(repository):
    structures = fixture_structures(repository)
    first = structures.preview(structural_candidate(), proposed_by=uuid.uuid4())
    second = structures.preview(structural_candidate(), proposed_by=uuid.uuid4())
    applied = structures.apply(
        first.preview_id,
        base_snapshot_id=None,
        base_graph_sha256=None,
        base_reconstruction_sha256=None,
        committed_by=uuid.uuid4(),
    )
    with pytest.raises(StaleStructuralBase):
        structures.apply(
            second.preview_id,
            base_snapshot_id=None,
            base_graph_sha256=None,
            base_reconstruction_sha256=None,
            committed_by=uuid.uuid4(),
        )
    assert structures.current().snapshot_id == applied.snapshot_id
    assert (
        repository.connection.execute(
            "select status from world_structure_preview where preview_id=%s", (second.preview_id,)
        ).fetchone()["status"]
        == "stale"
    )


def test_region_movement_requires_a_recorded_migration_and_owner_identity_is_stable(repository):
    structures = fixture_structures(repository)
    first = apply_candidate(structures, structural_candidate())

    moved = structural_candidate(graph="graph-b", region_b_x_mm=14_000)
    with pytest.raises(InvalidStructuralData, match="without a recorded migration"):
        structures.preview(moved, proposed_by=uuid.uuid4())

    migration = PlacementMigration(uuid.uuid4(), "region-b", "reviewed archive expansion")
    moved = structural_candidate(graph="graph-b", region_b_x_mm=14_000, migrations=(migration,))
    second = apply_candidate(structures, moved)
    assert second.parent_snapshot_id == first.snapshot_id
    row = repository.connection.execute(
        "select region_id,reason,approved_by from world_structure_placement_migration "
        "where snapshot_id=%s",
        (second.snapshot_id,),
    ).fetchone()
    assert row["region_id"] == "region-b"
    assert row["reason"] == migration.reason
    assert row["approved_by"] == second.committed_by

    changed_owner = structural_candidate(graph="graph-c")
    topology = copy.deepcopy(changed_owner.topology)
    topology["elements"][0]["owner"]["id"] = "region-b"
    changed_owner = SpatialCandidate(
        changed_owner.graph_sha256,
        changed_owner.reconstruction_sha256,
        topology,
        changed_owner.layout,
        changed_owner.placement,
        changed_owner.neighborhood,
    )
    with pytest.raises(InvalidStructuralData, match="semantic owner"):
        structures.preview(changed_owner, proposed_by=uuid.uuid4())


def test_appearance_apply_cannot_change_any_structural_pointer_or_digest(repository):
    structures = fixture_structures(repository)
    snapshot = apply_candidate(structures, structural_candidate())
    before = repository.connection.execute(
        "select * from world_structure_state where workspace_id=%s",
        (repository.workspace_id,),
    ).fetchone()

    styles = WorldStyleRepository(
        repository.connection, repository.workspace_id, world_id=structures.world_id
    )
    current = styles.current()
    style_preview = styles.preview(
        StyleProposal(
            uuid.uuid4(),
            ProposalProvenance(ProposalOrigin.SETTINGS, uuid.uuid4(), "appearance-panel"),
            StyleScope("global"),
            current.version_id,
            snapshot.digests.topology_sha256,
            StyleReference("origin-landscape", 1, {"vitality": 0.35}),
        )
    )
    styles.apply(
        style_preview.preview_id,
        base_style_version_id=current.version_id,
        base_topology_digest=snapshot.digests.topology_sha256,
        applied_by=uuid.uuid4(),
    )
    after = repository.connection.execute(
        "select * from world_structure_state where workspace_id=%s",
        (repository.workspace_id,),
    ).fetchone()
    assert after["current_snapshot_id"] == before["current_snapshot_id"]
    assert after["current_graph_sha256"] == before["current_graph_sha256"]
    assert after["current_reconstruction_sha256"] == before["current_reconstruction_sha256"]


def test_tombstone_invalidates_the_dependent_snapshot_and_selects_nearest_valid_fallback(
    repository, tmp_path, photo_dir
):
    structures = fixture_structures(repository)
    fallback = apply_candidate(structures, structural_candidate())

    store = LocalContentAddressedStore(tmp_path / "blobs")
    outcome = PhotoIngestPipeline(repository, store, vision=None).ingest_file(
        write_photo(photo_dir, "structural-source.jpg")
    )
    assert outcome.error is None
    evidence = repository.connection.execute(
        "select s.span_id,c.capture_id from evidence_span s join capture c "
        "on c.workspace_id=s.workspace_id and c.blob_sha256=s.blob_sha256 "
        "where s.workspace_id=%s limit 1",
        (repository.workspace_id,),
    ).fetchone()
    dependent = apply_candidate(
        structures,
        structural_candidate(graph="graph-with-source", evidence_span_id=evidence["span_id"]),
    )
    repository.insert_tombstone(
        scope="capture",
        capture_id=evidence["capture_id"],
        requested_by=uuid.uuid4(),
        reason="the source was deleted",
    )

    literal = structures.current()
    effective = structures.effective_current()
    assert literal.snapshot_id == dependent.snapshot_id and literal.invalidated
    assert effective.snapshot_id == fallback.snapshot_id and not effective.invalidated
    invalidation = repository.connection.execute(
        "select reason from world_structure_invalidation where snapshot_id=%s",
        (dependent.snapshot_id,),
    ).fetchone()
    assert "tombstone" in invalidation["reason"]
