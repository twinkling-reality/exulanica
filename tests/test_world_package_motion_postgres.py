"""A world with motion is exported, verified and read back under the 1.1 extension versions.

The 1.0 formats withhold a version whose chain gives, changes or takes away a behaviour
(``test_world_package_behaviour_edit_postgres.py``). Authored-world 1.1 and environment-instances
1.1 admit ``set_object_behaviour``, so the same versions leave with the package: the object keeps
the reviewed behaviour and parameters the database stores, the chain names every behaviour edit,
and a verifier re-derives every state token from the exported delta.

Verification and loading stay two answers. ``verify`` says the bytes and the rules hold and that
loading was not assessed; ``import-check`` compares what a loader declares with what the signed
content needs, so a loader that cannot run the motion is told which objects to show without it,
and one that does not know the 1.1 extension is told what it leaves behind.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from exulanica.ingest.pipeline import PhotoIngestPipeline
from exulanica.store.local import LocalContentAddressedStore
from exulanica.world import (
    WorldObjectRepository,
    WorldStructureRepository,
    seed_reviewed_assets,
)
from exulanica.world.authored_delta import canonical_delta_document
from exulanica.world.objects import AuthoredObject, ObjectOrigin, Transform
from exulanica.world_package import package, project_world_package, verify_package
from exulanica.world_package.extension_formats import (
    AUTHORED_WORLD_1_0,
    AUTHORED_WORLD_1_1,
    ENVIRONMENT_INSTANCES_1_0,
    ENVIRONMENT_INSTANCES_1_1,
    REASON_SOURCE_INVALIDATED,
)
from exulanica.world_package.package import RUNTIME_LOADABILITY, import_check_package

from conftest import write_photo
from test_world_environment_composition_postgres import _add, _composed_over
from test_world_package_behaviour_edit_postgres import SLOWER, _a_version_given_a_behaviour_later
from test_world_package_extension_postgres import (
    CUBE,
    MOTION,
    _apply,
    _one_version_one_object,
    _urn,
)
from world_structure_fixtures import structural_candidate

pytestmark = pytest.mark.postgres

MOTION_CAPABILITY = "behaviour:motion.bounded-path@1"


def _export(repository, output: Path, *, world_id: str, extensions=(), store=None):
    """The package of the world a test wrote into, named rather than assumed."""
    return project_world_package(
        repository.connection,
        workspace_id=repository.workspace_id,
        actor=uuid.uuid4(),
        output=output,
        private_key=Ed25519PrivateKey.generate(),
        world_id=world_id,
        extensions=extensions,
        store=store,
    )


def _base_loader(output: Path) -> frozenset[str]:
    """What a loader of the 1.0 world alone declares for this package."""
    undeclared = import_check_package(output)
    return frozenset(
        {f"style-profile:{p}" for p in undeclared["required_style_profiles"]}
        | {f"interaction:{c}" for c in undeclared["required_interaction_capabilities"]}
    )


def _stored_behaviour(repository, version_id, object_id) -> dict:
    """The behaviour columns exactly as the database holds them for one placed object."""
    row = repository.connection.execute(
        "select behaviour_key,behaviour_version,behaviour_parameters from world_alternate_object "
        "where version_id=%s and object_id=%s",
        (version_id, object_id),
    ).fetchone()
    return {
        "behaviour_key": row["behaviour_key"],
        "behaviour_version": row["behaviour_version"],
        "parameters": row["behaviour_parameters"],
    }


def test_a_world_with_motion_exports_verifies_and_round_trips(repository, tmp_path: Path):
    objects, snapshot, plain = _one_version_one_object(repository, tmp_path)
    edited = _a_version_given_a_behaviour_later(objects, snapshot)
    branch = objects.create_version(
        parent_version_id=edited.version_id, title="Branch of it", created_by=uuid.uuid4()
    )
    stopped = objects.set_object_behaviour(
        branch.version_id,
        "object:kite",
        None,
        base_state_sha256=branch.state_sha256,
        actor=uuid.uuid4(),
    )
    result = _export(
        repository,
        tmp_path / "motion.wmp",
        world_id=objects.world_id,
        extensions=[AUTHORED_WORLD_1_1.key],
    )

    report = verify_package(result.output)
    [finding] = report.extensions
    assert (finding.extension, finding.extension_version) == (AUTHORED_WORLD_1_1.name, "1.1")
    assert finding.rules_checked and finding.directory == AUTHORED_WORLD_1_1.directory
    world = finding.authored_world
    exported = {version["version_id"]: version for version in world.versions}
    assert set(exported) == {
        _urn("alternate-version", version.version_id) for version in (plain, edited, branch)
    }
    assert world.withheld_versions == 0
    for version in (plain, edited, stopped):
        stored = objects.version(version.version_id)
        packaged = exported[_urn("alternate-version", version.version_id)]
        assert packaged["delta"] == canonical_delta_document(
            objects=stored.objects,
            element_overrides=stored.element_overrides,
            environment_instances=(),
            point_map_instances=(),
        )
        assert packaged["state_sha256"] == stored.state_sha256
        assert [(e["kind"], e["result_state_sha256"]) for e in packaged["edits"]] == [
            (e.kind, e.result_state_sha256) for e in stored.edits
        ]
    moving = exported[_urn("alternate-version", edited.version_id)]
    assert [edit["kind"] for edit in moving["edits"]] == ["add_object", "set_object_behaviour"]
    [kite] = moving["delta"]["objects"]
    # The reviewed behaviour and its parameters, exactly as the database stores them.
    assert kite["behaviour"] == _stored_behaviour(repository, edited.version_id, "object:kite")
    assert kite["behaviour"] == SLOWER.document()
    stopped_packaged = exported[_urn("alternate-version", branch.version_id)]
    assert [edit["kind"] for edit in stopped_packaged["edits"]] == ["set_object_behaviour"]
    assert stopped_packaged["delta"]["objects"][0]["behaviour"] is None
    assert stopped_packaged["parent_version_id"] == _urn("alternate-version", edited.version_id)
    assert set(world.behaviours) == {("motion.bounded-path", 1)}

    # Verified is one answer, and it says it did not load anything.
    verified = report.as_dict()
    assert verified["verified"] is True
    assert verified["runtime_loadability"] == RUNTIME_LOADABILITY
    assert f"{AUTHORED_WORLD_1_1.name}@1.1" in verified["summary"]


def test_what_a_loader_can_run_is_a_separate_answer(repository, tmp_path: Path):
    objects, snapshot, _ = _one_version_one_object(repository, tmp_path)
    _a_version_given_a_behaviour_later(objects, snapshot)
    result = _export(
        repository,
        tmp_path / "motion.wmp",
        world_id=objects.world_id,
        extensions=[AUTHORED_WORLD_1_1.key],
    )
    base = _base_loader(result.output)
    resolving = {
        AUTHORED_WORLD_1_1.capability,
        "asset-resolution:sha256-content-address",
        "asset-media:model/gltf-binary",
    }

    knows_1_0_only = import_check_package(
        result.output, loader_capabilities=base | {AUTHORED_WORLD_1_0.capability}
    )
    assert knows_1_0_only["loadability"] == "partial"
    [extension] = knows_1_0_only["extensions"]
    assert extension["load"] == "not loaded"
    assert AUTHORED_WORLD_1_1.capability in extension["not_loaded"]
    assert extension["not_loaded"] in knows_1_0_only["warnings"]

    no_motion = import_check_package(result.output, loader_capabilities=base | resolving)
    assert no_motion["loadability"] == "partial"
    assert no_motion["unsupported_capabilities"] == [MOTION_CAPABILITY]
    [extension] = no_motion["extensions"]
    assert extension["load"] == "loaded with unsupported parts named"
    assert {item["object_id"] for item in extension["objects_with_unsupported_behaviour"]} == {
        "object:lantern",
        "object:kite",
    }
    assert {item["shown_as"] for item in extension["objects_with_unsupported_behaviour"]} == {
        "present, with its behaviour marked unsupported"
    }

    complete = import_check_package(
        result.output, loader_capabilities=base | resolving | {MOTION_CAPABILITY}
    )
    assert complete["loadability"] == "complete"
    assert complete["extensions"][0]["load"] == "loaded"


def test_a_verifier_that_knows_only_1_0_verifies_the_bytes_and_names_1_1_unchecked(
    repository, tmp_path: Path, monkeypatch
):
    """What a verifier from before 1.1 does with a 1.1 package, by removing what this one knows."""
    objects, snapshot, _ = _one_version_one_object(repository, tmp_path)
    _a_version_given_a_behaviour_later(objects, snapshot)
    result = _export(
        repository,
        tmp_path / "motion.wmp",
        world_id=objects.world_id,
        extensions=[AUTHORED_WORLD_1_1.key],
    )
    monkeypatch.setattr(
        package,
        "_KNOWN_FORMATS",
        {
            (format_.name, format_.version): format_
            for format_ in (AUTHORED_WORLD_1_0, ENVIRONMENT_INSTANCES_1_0)
        },
    )
    [finding] = verify_package(result.output).extensions
    assert not finding.rules_checked
    assert finding.extension_version == "1.1"
    assert AUTHORED_WORLD_1_1.capability in finding.required_loader_capabilities
    assert "Not checked by this verifier" in verify_package(result.output).as_dict()["summary"]


def _a_version_on_a_deleted_source(repository, tmp_path: Path, photo_dir: Path):
    """A version posed on structure that depended on a photograph, which is then deleted."""
    outcome = PhotoIngestPipeline(
        repository, LocalContentAddressedStore(tmp_path / "blobs"), vision=None
    ).ingest_file(write_photo(photo_dir, "authored-source.jpg"))
    assert outcome.error is None
    evidence = repository.connection.execute(
        "select s.span_id,c.capture_id from evidence_span s join capture c "
        "on c.workspace_id=s.workspace_id and c.blob_sha256=s.blob_sha256 "
        "where s.workspace_id=%s limit 1",
        (repository.workspace_id,),
    ).fetchone()
    dependent = _apply(
        WorldStructureRepository(repository.connection, repository.workspace_id),
        structural_candidate(graph="graph-with-source", evidence_span_id=evidence["span_id"]),
    )
    objects = WorldObjectRepository(repository.connection, repository.workspace_id)
    version = objects.create_version(
        source_snapshot_id=dependent.snapshot_id, title="Doomed", created_by=uuid.uuid4()
    )
    repository.insert_tombstone(
        scope="capture",
        capture_id=evidence["capture_id"],
        requested_by=uuid.uuid4(),
        reason="the source scene was deleted",
    )
    assert objects.version(version.version_id).source_invalidated is True
    return version


def test_the_1_1_package_counts_what_it_withholds_by_reason(repository, tmp_path, photo_dir):
    """A deletion is the reason here, and the 1.1 section says so rather than one total."""
    doomed = _a_version_on_a_deleted_source(repository, tmp_path, photo_dir)
    result = _export(
        repository,
        tmp_path / "after-1-1.wmp",
        world_id=doomed.world_id,
        extensions=[AUTHORED_WORLD_1_1.key],
    )
    world = verify_package(result.output).extensions[0].authored_world
    assert world.versions == ()
    assert world.withheld_versions == 1
    text = (result.output / AUTHORED_WORLD_1_1.section_path("versions")).read_text()
    assert json.loads(text)["withheld"]["reasons"] == [
        {"names": [], "reason": REASON_SOURCE_INVALIDATED, "versions": 1}
    ]
    assert "Doomed" not in text
    assert _urn("alternate-version", doomed.version_id) not in text


def test_an_environment_version_with_motion_exports_under_environment_instances_1_1(
    repository, tmp_path: Path
):
    composed = _composed_over(repository, tmp_path, structural_candidate())
    seed_reviewed_assets(composed.store)
    version = _add(composed, composed.placement("environment:fair"))
    version = composed.worlds.add_object(
        version.version_id,
        _lantern(),
        base_state_sha256=version.state_sha256,
        actor=uuid.uuid4(),
    )
    version = composed.worlds.set_object_behaviour(
        version.version_id,
        "object:lantern",
        SLOWER,
        base_state_sha256=version.state_sha256,
        actor=uuid.uuid4(),
    )
    older = _export(
        repository,
        tmp_path / "environments-1-0.wmp",
        world_id=composed.worlds.world_id,
        extensions=[ENVIRONMENT_INSTANCES_1_0.key],
        store=composed.store,
    )
    assert verify_package(older.output).extensions[0].environment_instances.versions == ()

    result = _export(
        repository,
        tmp_path / "environments-1-1.wmp",
        world_id=composed.worlds.world_id,
        extensions=[ENVIRONMENT_INSTANCES_1_1.key],
        store=composed.store,
    )
    finding = verify_package(result.output).extensions[0]
    assert finding.extension_version == "1.1" and finding.rules_checked
    [packaged] = finding.environment_instances.versions
    stored = composed.worlds.version(version.version_id)
    assert packaged["state_sha256"] == stored.state_sha256
    assert [edit["kind"] for edit in packaged["edits"]] == [
        "add_environment",
        "add_object",
        "set_object_behaviour",
    ]
    assert packaged["delta"]["objects"][0]["behaviour"] == SLOWER.document()
    assert packaged["delta"]["schema_version"] == 2


def _lantern() -> AuthoredObject:
    return AuthoredObject(
        object_id="object:lantern",
        asset_sha256=CUBE,
        region_id="region-a",
        transform=Transform(1_200, 0, -450, 0, 1_000),
        origin=ObjectOrigin("authored", "fictional"),
        behaviour=MOTION,
    )
