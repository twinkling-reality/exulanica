from __future__ import annotations

import json
import uuid
from pathlib import Path

import psycopg
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from exulanica.evidence import BlobId
from exulanica.world import (
    ProposalOrigin,
    ProposalProvenance,
    WorldInteractionPolicyRepository,
    WorldStructureRepository,
)
from exulanica.world.interaction import InteractionProposal
from exulanica.world_package import diff_packages, project_world_package, verify_package

from world_structure_fixtures import structural_candidate, with_topology

pytestmark = pytest.mark.postgres


def _capture(repository, value: bytes):
    blob = BlobId.of_bytes(value)
    repository.upsert_blob(
        blob,
        byte_size=len(value),
        media_type="image/jpeg",
        storage_key=f"test-only/{blob.hex}",
    )
    return repository.insert_capture(blob, device_id=None, started_at=None)


def _export(repository, output: Path, *, hook=None, parent=None):
    return project_world_package(
        repository.connection,
        workspace_id=repository.workspace_id,
        actor=uuid.uuid4(),
        output=output,
        private_key=Ed25519PrivateKey.generate(),
        parent_merkle_root_sha256=parent,
        after_snapshot_hook=hook,
    )


def test_projector_archives_current_structure_and_append_only_receipt(repository, tmp_path: Path):
    structures = WorldStructureRepository(repository.connection, repository.workspace_id)
    candidate = structural_candidate()
    preview = structures.preview(candidate, proposed_by=uuid.uuid4())
    snapshot = structures.apply(
        preview.preview_id,
        base_snapshot_id=None,
        base_graph_sha256=None,
        base_reconstruction_sha256=None,
        committed_by=uuid.uuid4(),
    )
    policies = WorldInteractionPolicyRepository(repository.connection, repository.workspace_id)
    policy_proposal = InteractionProposal(
        uuid.uuid4(),
        ProposalProvenance(ProposalOrigin.USER, uuid.uuid4()),
        {"comfort.vignette": "strong"},
        None,
        snapshot.snapshot_id,
        snapshot.digests.topology_sha256,
        {"source": "settings"},
        "Apply one reviewed comfort capability.",
        ("settings",),
    )
    policy_preview = policies.preview(policy_proposal)
    policy = policies.apply(
        policy_preview.preview_id,
        base_policy_version_id=None,
        base_structure_snapshot_id=snapshot.snapshot_id,
        base_topology_sha256=snapshot.digests.topology_sha256,
        applied_by=uuid.uuid4(),
    )

    result = _export(repository, tmp_path / "world.wmp")
    verified = verify_package(result.output)
    assert verified.merkle_root_sha256 == result.merkle_root_sha256
    assert json.loads((result.output / "world/topology.json").read_text()) == candidate.topology
    appearance = json.loads((result.output / "appearance/style.json").read_text())
    interaction = json.loads((result.output / "interaction/policy.json").read_text())
    crate = json.loads((result.output / "ro-crate-metadata.json").read_text())
    assert appearance["state"] == "current"
    assert appearance["registry"][0]["maximum_value"] == {
        "@type": "exulanica:IEEE754Binary64",
        "hex": "0x1.0000000000000p+0",
    }
    assert appearance["recipe_binding"]["modules"] == [
        "aeroheart-optics-v1",
        "registered-surface-v1",
        "bounded-tempo-v1",
        "source-light-v1",
    ]
    assert {
        value["module_id"] for value in appearance["registry_modules"]
    } >= {"aeroheart-optics-v1", "registered-surface-v1", "bounded-tempo-v1"}
    assert interaction["state"] == "current"
    assert interaction["parameters"]["comfort.vignette"] == "strong"
    assert crate["@context"] == "https://w3id.org/ro/crate/1.2/context"
    assert any(node["@id"] == "#responsible-ai-boundary" for node in crate["@graph"])
    receipt = repository.connection.execute(
        "select * from world_package_export where export_id=%s", (result.export_id,)
    ).fetchone()
    assert receipt["structure_snapshot_id"] == snapshot.snapshot_id
    assert receipt["style_version_id"] is not None
    assert receipt["interaction_policy_version_id"] == policy.version_id
    assert receipt["export_policy"]["raw_payloads"] == "excluded"
    with pytest.raises(psycopg.errors.IntegrityConstraintViolation):
        repository.connection.execute(
            "update world_package_export set actor=%s where export_id=%s",
            (uuid.uuid4(), result.export_id),
        )


def test_repeatable_read_excludes_a_capture_committed_during_projection(
    ingest_spine, tmp_path: Path
):
    repository, open_another = ingest_spine
    first = _capture(repository, b"first-photo")
    other = open_another()

    def mutate_after_snapshot() -> None:
        _capture(other, b"concurrent-photo")

    result = _export(repository, tmp_path / "concurrent.wmp", hook=mutate_after_snapshot)
    graph = json.loads((result.output / "memory/graph.json").read_text())
    assert len(graph["captures"]) == 1
    assert graph["captures"][0]["content_sha256"] == BlobId.of_bytes(b"first-photo").hex
    assert repository.capture(first.capture_id) is not None
    assert other.connection.execute("select count(*) as n from capture").fetchone()["n"] == 2


def test_export_during_topology_commit_keeps_one_protected_snapshot(
    ingest_spine, tmp_path: Path
):
    repository, open_another = ingest_spine
    structures = WorldStructureRepository(repository.connection, repository.workspace_id)
    initial_candidate = structural_candidate(region_b_x_mm=10_000)
    initial_preview = structures.preview(initial_candidate, proposed_by=uuid.uuid4())
    initial = structures.apply(
        initial_preview.preview_id,
        base_snapshot_id=None,
        base_graph_sha256=None,
        base_reconstruction_sha256=None,
        committed_by=uuid.uuid4(),
    )
    other = open_another()
    other_structures = WorldStructureRepository(other.connection, other.workspace_id)
    replacement_topology = json.loads(json.dumps(initial_candidate.topology))
    replacement_topology["navigation"]["agent_radius_mm"] = 350
    replacement_preview = other_structures.preview(
        with_topology(initial_candidate, replacement_topology), proposed_by=uuid.uuid4()
    )

    def commit_replacement() -> None:
        other_structures.apply(
            replacement_preview.preview_id,
            base_snapshot_id=initial.snapshot_id,
            base_graph_sha256=initial.candidate.graph_sha256,
            base_reconstruction_sha256=initial.candidate.reconstruction_sha256,
            committed_by=uuid.uuid4(),
        )

    result = _export(repository, tmp_path / "topology-race.wmp", hook=commit_replacement)
    topology = json.loads((result.output / "world/topology.json").read_text())
    placement = json.loads((result.output / "world/placement.json").read_text())
    region_b = next(
        item for item in placement["elements"] if item["element_id"] == "element:region-b:root"
    )
    assert result.structure_snapshot_id == initial.snapshot_id
    assert topology["navigation"]["agent_radius_mm"] == 300
    assert region_b["x_mm"] == 10_000
    assert other_structures.current().snapshot_id != initial.snapshot_id


def test_deletion_reexport_changes_root_and_semantic_diff(repository, tmp_path: Path):
    capture = _capture(repository, b"photo-to-delete")
    before = _export(repository, tmp_path / "before.wmp")
    repository.insert_tombstone(
        scope="capture",
        requested_by=uuid.uuid4(),
        capture_id=capture.capture_id,
        reason="private reason must not enter the package",
    )
    after = _export(
        repository,
        tmp_path / "after.wmp",
        parent=before.merkle_root_sha256,
    )
    difference = diff_packages(before.output, after.output)
    assert before.merkle_root_sha256 != after.merkle_root_sha256
    assert difference.changed
    assert "memory/graph.json" in difference.changed_files
    assert "deletion/tombstones.json" in difference.changed_files
    assert json.loads((after.output / "memory/graph.json").read_text())["captures"] == []
    deletion_text = (after.output / "deletion/tombstones.json").read_text()
    assert "private reason" not in deletion_text
    assert any(change["kind"] == "removed" for change in difference.semantic_changes)


def test_unchanged_snapshot_and_same_lineage_reuses_the_exact_package_root(
    repository, tmp_path: Path
):
    _capture(repository, b"stable-photo")
    first = _export(repository, tmp_path / "first.wmp")
    second = _export(repository, tmp_path / "second.wmp")
    assert first.merkle_root_sha256 == second.merkle_root_sha256
    assert first.manifest_sha256 == second.manifest_sha256
    assert first.export_id != second.export_id
