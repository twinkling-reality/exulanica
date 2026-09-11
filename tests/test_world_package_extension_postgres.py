"""The authored-world extension projected from live PostgreSQL, and read back by two loaders.

The round trip is the acceptance: one alternate version holding one reviewed object, projected
into a signed package, verified offline, and read back by a loader that does not support the
extension and by one that does. Read back means the exported delta is the document the product
digests, its digest is the version's state token, and its edit chain is the log the database
holds, not merely that a file with the right name exists.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from exulanica.ingest.pipeline import PhotoIngestPipeline
from exulanica.store.local import LocalContentAddressedStore
from exulanica.world import (
    AuthoredObject,
    ElementOverride,
    ObjectBehaviour,
    ObjectOrigin,
    Transform,
    WorldObjectRepository,
    WorldStructureRepository,
)
from exulanica.world.objects import canonical_delta_document
from exulanica.world_package import authored, project_world_package, verify_package
from exulanica.world_package.package import MANIFEST_PATH, SIGNATURE_PATH, import_check_package

from conftest import write_photo
from world_structure_fixtures import structural_candidate

pytestmark = pytest.mark.postgres

CUBE = "b41289ac10548cf698d46a15206caa8e744b0b800f4ac29260c99f18d8b831d9"
MOTION = ObjectBehaviour(
    "motion.bounded-path",
    1,
    {"axis": "y", "easing": "linear", "period_milliseconds": 3_000, "travel_mm": 600},
)


def _urn(kind: str, value: object) -> str:
    return f"urn:exulanica:wmp:{kind}:{hashlib.sha256(f'{kind}:{value}'.encode()).hexdigest()}"


def _apply(structures: WorldStructureRepository, candidate) -> object:
    actor = uuid.uuid4()
    preview = structures.preview(candidate, proposed_by=actor)
    return structures.apply(
        preview.preview_id,
        base_snapshot_id=preview.base_snapshot_id,
        base_graph_sha256=preview.base_graph_sha256,
        base_reconstruction_sha256=preview.base_reconstruction_sha256,
        committed_by=actor,
    )


def _export(repository, output: Path, *, extensions=()):
    return project_world_package(
        repository.connection,
        workspace_id=repository.workspace_id,
        actor=uuid.uuid4(),
        output=output,
        private_key=Ed25519PrivateKey.generate(),
        extensions=extensions,
    )


def _one_version_one_object(repository):
    structures = WorldStructureRepository(repository.connection, repository.workspace_id)
    snapshot = _apply(structures, structural_candidate())
    objects = WorldObjectRepository(repository.connection, repository.workspace_id)
    version = objects.create_version(
        source_snapshot_id=snapshot.snapshot_id, title="Evening study", created_by=uuid.uuid4()
    )
    base = version.state_sha256
    version = objects.add_object(
        version.version_id,
        AuthoredObject(
            object_id="object:lantern",
            asset_sha256=CUBE,
            region_id="region-a",
            transform=Transform(1_200, 0, -450, 785_398, 1_000),
            origin=ObjectOrigin("authored", "fictional"),
            behaviour=MOTION,
        ),
        base_state_sha256=base,
        actor=uuid.uuid4(),
    )
    version = objects.move_object(
        version.version_id,
        "object:lantern",
        Transform(2_400, 0, -450, 0, 1_500),
        base_state_sha256=version.state_sha256,
        actor=uuid.uuid4(),
    )
    return objects, snapshot, version


def test_one_version_one_object_round_trips_through_a_signed_package(repository, tmp_path: Path):
    objects, snapshot, version = _one_version_one_object(repository)
    plain = _export(repository, tmp_path / "plain.wmp")
    extended = _export(repository, tmp_path / "extended.wmp", extensions=[authored.EXTENSION_KEY])

    # The 1.0 payloads are the same bytes with and without the extension.
    for path in sorted(plain.output.rglob("*.json")):
        relative = str(path.relative_to(plain.output))
        if relative in {"ro-crate-metadata.json", MANIFEST_PATH, SIGNATURE_PATH}:
            continue
        assert (extended.output / relative).read_bytes() == path.read_bytes(), relative
    assert not (plain.output / "extensions").exists()

    report = verify_package(extended.output)
    [finding] = report.extensions
    assert finding.rules_checked
    world = finding.authored_world
    assert world is not None
    [packaged] = world.versions
    stored = objects.version(version.version_id)
    assert packaged["version_id"] == _urn("alternate-version", version.version_id)
    assert packaged["source_snapshot_id"] == _urn("structure", snapshot.snapshot_id)
    assert packaged["delta"] == canonical_delta_document(stored.objects, stored.element_overrides)
    assert (
        packaged["state_sha256"] == stored.state_sha256 == authored.delta_sha256(packaged["delta"])
    )
    assert [
        (e["kind"], e["base_state_sha256"], e["result_state_sha256"]) for e in packaged["edits"]
    ] == [(e.kind, e.base_state_sha256, e.result_state_sha256) for e in stored.edits]
    assert packaged["edits"][0]["base_state_sha256"] == authored.EMPTY_DELTA_SHA256
    [obj] = packaged["delta"]["objects"]
    assert obj["transform"]["x_mm"] == 2_400 and obj["transform"]["scale_milli"] == 1_500
    assert obj["origin"] == {"kind": "authored", "role": "fictional"}
    assert obj["behaviour"]["parameters"]["travel_mm"] == 600
    [asset] = world.assets.values()
    registry = {a.content_sha256: a for a in objects.reviewed_assets()}
    assert asset["asset_key"] == registry[CUBE].asset_key
    assert asset["licence_sha256"] == registry[CUBE].licence_sha256
    assert (
        world.behaviours[("motion.bounded-path", 1)]["parameters"]
        == (objects.behaviour_registry()[("motion.bounded-path", 1)])
    )
    everything = json.dumps(
        [json.loads(p.read_bytes()) for p in (extended.output / authored.EXTENSION_DIR).iterdir()]
    )
    assert str(version.created_by) not in everything, "no actor is exported"
    assert str(version.version_id) not in everything, "database ids are pseudonymised"

    receipts = {
        row["export_id"]: row["export_policy"]
        for row in repository.connection.execute(
            "select export_id,export_policy from world_package_export"
        ).fetchall()
    }
    assert "extensions" not in receipts[plain.export_id]
    assert receipts[extended.export_id]["extensions"] == [authored.EXTENSION_KEY]

    styles = {
        f"style-profile:{p}"
        for p in import_check_package(extended.output)["required_style_profiles"]
    }
    interactions = {
        f"interaction:{c}"
        for c in import_check_package(extended.output)["required_interaction_capabilities"]
    }
    base_loader = frozenset(styles | interactions)
    without = import_check_package(extended.output, loader_capabilities=base_loader)
    assert without["compatible"] is True
    assert without["loadability"] == "partial"
    assert without["extensions"][0]["load"] == "not loaded"
    full = import_check_package(
        extended.output,
        loader_capabilities=base_loader
        | {
            authored.EXTENSION_CAPABILITY,
            authored.ASSET_RESOLUTION_CAPABILITY,
            "asset-media:model/gltf-binary",
            "behaviour:motion.bounded-path@1",
        },
    )
    assert full["loadability"] == "complete"
    assert full["extensions"][0]["load"] == "loaded"


def test_a_branch_and_a_source_override_resolve_inside_the_package(repository, tmp_path: Path):
    objects, _snapshot, version = _one_version_one_object(repository)
    child = objects.create_version(
        parent_version_id=version.version_id, title="Variation", created_by=uuid.uuid4()
    )
    child = objects.set_element_override(
        child.version_id,
        ElementOverride("element:region-b:root", suppressed=True),
        base_state_sha256=child.state_sha256,
        actor=uuid.uuid4(),
    )
    result = _export(repository, tmp_path / "branch.wmp", extensions=[authored.EXTENSION_KEY])
    world = verify_package(result.output).extensions[0].authored_world
    by_id = {v["version_id"]: v for v in world.versions}
    packaged = by_id[_urn("alternate-version", child.version_id)]
    assert packaged["parent_version_id"] == _urn("alternate-version", version.version_id)
    assert packaged["delta"]["element_overrides"] == [
        {"element_id": "element:region-b:root", "suppressed": True, "transform": None}
    ]
    assert packaged["state_sha256"] == objects.version(child.version_id).state_sha256


def test_a_version_whose_source_was_deleted_is_withheld_and_counted(
    repository, tmp_path: Path, photo_dir
):
    """The decision section 8 of the objects contract left open: withheld, counted, unnamed."""
    structures = WorldStructureRepository(repository.connection, repository.workspace_id)
    store = LocalContentAddressedStore(tmp_path / "blobs")
    outcome = PhotoIngestPipeline(repository, store, vision=None).ingest_file(
        write_photo(photo_dir, "authored-source.jpg")
    )
    assert outcome.error is None
    evidence = repository.connection.execute(
        "select s.span_id,c.capture_id from evidence_span s join capture c "
        "on c.workspace_id=s.workspace_id and c.blob_sha256=s.blob_sha256 "
        "where s.workspace_id=%s limit 1",
        (repository.workspace_id,),
    ).fetchone()
    dependent = _apply(
        structures,
        structural_candidate(graph="graph-with-source", evidence_span_id=evidence["span_id"]),
    )
    objects = WorldObjectRepository(repository.connection, repository.workspace_id)
    version = objects.create_version(
        source_snapshot_id=dependent.snapshot_id, title="Doomed", created_by=uuid.uuid4()
    )

    before = _export(repository, tmp_path / "before.wmp", extensions=[authored.EXTENSION_KEY])
    assert verify_package(before.output).extensions[0].authored_world.withheld_versions == 0

    repository.insert_tombstone(
        scope="capture",
        capture_id=evidence["capture_id"],
        requested_by=uuid.uuid4(),
        reason="the source scene was deleted",
    )
    assert objects.version(version.version_id).source_invalidated is True
    after = _export(repository, tmp_path / "after.wmp", extensions=[authored.EXTENSION_KEY])
    world = verify_package(after.output).extensions[0].authored_world
    assert world.versions == ()
    assert world.withheld_versions == 1
    assert world.declaration["counts"]["withheld_versions"] == 1
    text = (after.output / authored.VERSIONS_PATH).read_text()
    assert _urn("alternate-version", version.version_id) not in text
    assert "Doomed" not in text
