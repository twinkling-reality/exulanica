"""Environment-instances extension projected from live PostgreSQL."""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from exulanica.evidence.blob import BlobId
from exulanica.world import (
    AuthoredObject,
    ObjectOrigin,
    Transform,
)
from exulanica.world.authored_delta import canonical_delta_document
from exulanica.world_package import authored, environments, project_world_package, verify_package
from exulanica.world_package.package import PackageError, import_check_package

from test_world_environment_composition_postgres import _add, _composed_over
from test_world_package_extension_postgres import CUBE, _one_version_one_object, _reviewed_objects
from world_structure_fixtures import structural_candidate

pytestmark = pytest.mark.postgres


def _urn(kind: str, value: object) -> str:
    return f"urn:exulanica:wmp:{kind}:{hashlib.sha256(f'{kind}:{value}'.encode()).hexdigest()}"


def _export(repository, output: Path, *, world_id: str, extensions=(), store=None):
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


def test_authored_world_1_0_without_environments_still_verifies(repository, tmp_path: Path):
    objects, _snapshot, _version = _one_version_one_object(repository, tmp_path)
    result = _export(
        repository,
        tmp_path / "authored.wmp",
        extensions=[authored.EXTENSION_KEY],
        world_id=objects.world_id,
    )
    report = verify_package(result.output)
    [finding] = report.extensions
    assert finding.extension == authored.EXTENSION_NAME
    assert finding.authored_world.versions[0]["delta"]["schema_version"] == 1
    assert "environment_instances" not in finding.authored_world.versions[0]["delta"]


def test_environment_instance_round_trips_through_a_signed_package(repository, tmp_path: Path):
    composed = _composed_over(repository, tmp_path, structural_candidate())
    version = _add(composed, composed.placement("environment:plaza"))
    stored = composed.worlds.version(version.version_id)
    result = _export(
        repository,
        tmp_path / "environment.wmp",
        extensions=[environments.EXTENSION_KEY],
        store=composed.store,
        world_id=composed.worlds.world_id,
    )
    report = verify_package(result.output)
    [finding] = report.extensions
    world = finding.environment_instances
    assert world is not None
    [packaged] = world.versions
    assert packaged["version_id"] == _urn("alternate-version", version.version_id)
    assert packaged["delta"] == canonical_delta_document(
        objects=stored.objects,
        element_overrides=stored.element_overrides,
        environment_instances=stored.environment_instances,
        point_map_instances=(),
    )
    assert packaged["delta"]["schema_version"] == 2
    assert packaged["state_sha256"] == stored.state_sha256 == environments.delta_sha256(
        packaged["delta"]
    )
    [instance] = packaged["delta"]["environment_instances"]
    assert instance["instance_id"] == "environment:plaza"
    assert instance["origin"] == {"kind": "authored", "role": "fictional"}
    assert packaged["environment_availability"] == [
        {"availability": "available", "instance_id": "environment:plaza"}
    ]
    text = (result.output / environments.VERSIONS_PATH).read_text()
    assert str(version.created_by) not in text
    assert str(version.version_id) not in text
    receipts = repository.connection.execute(
        "select export_policy from world_package_export where export_id=%s",
        (result.export_id,),
    ).fetchone()
    assert receipts["export_policy"]["extensions"] == [environments.EXTENSION_KEY]


def test_undone_environment_addition_is_omitted_from_the_exported_delta(
    repository, tmp_path: Path
):
    composed = _composed_over(repository, tmp_path, structural_candidate())
    empty = composed.version.state_sha256
    version = _add(composed, composed.placement("environment:temporary"))
    version = composed.worlds.undo(
        version.version_id, base_state_sha256=version.state_sha256, actor=uuid.uuid4()
    )
    assert version.environment_instances == () and version.state_sha256 == empty
    result = _export(
        repository,
        tmp_path / "undone-environment.wmp",
        extensions=[environments.EXTENSION_KEY],
        store=composed.store,
        world_id=composed.worlds.world_id,
    )
    world = verify_package(result.output).extensions[0].environment_instances
    packaged = next(item for item in world.versions if item["title"] == "Environment study")
    assert "environment_instances" not in packaged["delta"]
    assert packaged["delta"]["schema_version"] == 1
    assert packaged["environment_availability"] == []
    assert [edit["kind"] for edit in packaged["edits"]] == ["add_environment", "undo"]
    assert packaged["state_sha256"] == empty


def test_withdrawn_instances_are_exported_with_honest_availability(repository, tmp_path: Path):
    composed = _composed_over(repository, tmp_path, structural_candidate())
    withdrawn = _add(composed, composed.placement("environment:withdrawn"))
    composed.environments.withdraw("asset", composed.render.asset_id)
    result = _export(
        repository,
        tmp_path / "withdrawn.wmp",
        extensions=[environments.EXTENSION_KEY],
        store=composed.store,
        world_id=composed.worlds.world_id,
    )
    [packaged] = verify_package(result.output).extensions[0].environment_instances.versions
    assert packaged["environment_availability"] == [
        {"availability": "withdrawn", "instance_id": "environment:withdrawn"}
    ]
    assert packaged["delta"]["environment_instances"][0]["instance_id"] == "environment:withdrawn"
    assert packaged["state_sha256"] == composed.worlds.version(withdrawn.version_id).state_sha256


def test_unavailable_bytes_are_exported_without_substitute_geometry(repository, tmp_path: Path):
    composed = _composed_over(repository, tmp_path, structural_candidate())
    version = _add(composed, composed.placement("environment:missing"))
    digest = BlobId.from_hex(composed.render.expected_sha256)
    (composed.store.root / composed.store.key_for(digest)).unlink()
    result = _export(
        repository,
        tmp_path / "unavailable.wmp",
        extensions=[environments.EXTENSION_KEY],
        store=composed.store,
        world_id=composed.worlds.world_id,
    )
    [packaged] = verify_package(result.output).extensions[0].environment_instances.versions
    assert packaged["environment_availability"] == [
        {"availability": "unavailable_bytes", "instance_id": "environment:missing"}
    ]
    assert packaged["state_sha256"] == composed.worlds.version(version.version_id).state_sha256


def test_authored_world_1_0_alone_refuses_a_version_that_has_environments(
    repository, tmp_path: Path
):
    composed = _composed_over(repository, tmp_path, structural_candidate())
    _add(composed, composed.placement("environment:plaza"))
    with pytest.raises(PackageError, match="cannot export versions whose state includes"):
        _export(
            repository,
            tmp_path / "pretend.wmp",
            extensions=[authored.EXTENSION_KEY],
            world_id=composed.worlds.world_id,
        )


def test_dual_export_keeps_schema_v1_in_authored_world_and_environments_in_the_other(
    repository, tmp_path: Path
):
    composed = _composed_over(repository, tmp_path, structural_candidate())
    env_version = _add(composed, composed.placement("environment:plaza"))
    objects = _reviewed_objects(repository, tmp_path, world_id=composed.worlds.world_id)
    object_version = objects.create_version(
        source_snapshot_id=env_version.source_snapshot_id,
        title="Lantern only",
        created_by=uuid.uuid4(),
    )
    object_version = objects.add_object(
        object_version.version_id,
        AuthoredObject(
            object_id="object:lantern",
            asset_sha256=CUBE,
            region_id="region-a",
            transform=Transform(1_200, 0, -450, 0, 1_000),
            origin=ObjectOrigin("authored", "fictional"),
        ),
        base_state_sha256=object_version.state_sha256,
        actor=uuid.uuid4(),
    )
    result = _export(
        repository,
        tmp_path / "dual.wmp",
        extensions=[authored.EXTENSION_KEY, environments.EXTENSION_KEY],
        store=composed.store,
        world_id=composed.worlds.world_id,
    )
    report = verify_package(result.output)
    by_name = {finding.extension: finding for finding in report.extensions}
    authored_world = by_name[authored.EXTENSION_NAME].authored_world
    env_world = by_name[environments.EXTENSION_NAME].environment_instances
    authored_ids = {item["version_id"] for item in authored_world.versions}
    env_ids = {item["version_id"] for item in env_world.versions}
    assert authored_ids == {_urn("alternate-version", object_version.version_id)}
    assert env_ids == {_urn("alternate-version", env_version.version_id)}
    assert authored_world.versions[0]["delta"]["schema_version"] == 1
    assert "environment_instances" not in authored_world.versions[0]["delta"]
    assert env_world.versions[0]["delta"]["schema_version"] == 2
    exported = env_world.versions[0]["delta"]["environment_instances"]
    assert [item["instance_id"] for item in exported] == ["environment:plaza"]
    styles = {
        f"style-profile:{profile}"
        for profile in import_check_package(result.output)["required_style_profiles"]
    }
    interactions = {
        f"interaction:{capability}"
        for capability in import_check_package(result.output)["required_interaction_capabilities"]
    }
    without_env = import_check_package(
        result.output,
        loader_capabilities=frozenset(styles | interactions | {authored.EXTENSION_CAPABILITY}),
    )
    assert without_env["loadability"] == "partial"
    env_report = next(
        item
        for item in without_env["extensions"]
        if item["extension"] == environments.EXTENSION_NAME
    )
    assert env_report["load"] == "not loaded"
    assert "rather than infer objects from exulanica-wmp-ext-authored-world@1.0" in env_report[
        "not_loaded"
    ]


def _parent_then_environment_child(repository, tmp_path: Path):
    composed = _composed_over(repository, tmp_path, structural_candidate())
    parent = composed.version
    child = composed.worlds.create_version(
        parent_version_id=parent.version_id,
        title="Child plaza",
        created_by=uuid.uuid4(),
    )
    child = composed.worlds.add_environment(
        child.version_id,
        composed.placement("environment:plaza"),
        base_state_sha256=child.state_sha256,
        actor=uuid.uuid4(),
    )
    return composed, parent, child


def test_dual_export_of_an_authored_parent_and_environment_child_verifies(
    repository, tmp_path: Path
):
    composed, parent, child = _parent_then_environment_child(repository, tmp_path)
    result = _export(
        repository,
        tmp_path / "parent-child-dual.wmp",
        extensions=[authored.EXTENSION_KEY, environments.EXTENSION_KEY],
        store=composed.store,
        world_id=composed.worlds.world_id,
    )
    report = verify_package(result.output)
    by_name = {finding.extension: finding for finding in report.extensions}
    authored_world = by_name[authored.EXTENSION_NAME].authored_world
    env_world = by_name[environments.EXTENSION_NAME].environment_instances
    parent_urn = _urn("alternate-version", parent.version_id)
    child_urn = _urn("alternate-version", child.version_id)
    authored_by_id = {item["version_id"]: item for item in authored_world.versions}
    env_by_id = {item["version_id"]: item for item in env_world.versions}
    assert set(authored_by_id) == {parent_urn}
    assert set(env_by_id) == {parent_urn, child_urn}
    assert authored_by_id[parent_urn]["delta"]["schema_version"] == 1
    assert "environment_instances" not in authored_by_id[parent_urn]["delta"]
    assert env_by_id[parent_urn]["delta"]["schema_version"] == 1
    assert "environment_instances" not in env_by_id[parent_urn]["delta"]
    assert env_by_id[child_urn]["parent_version_id"] == parent_urn
    assert env_by_id[child_urn]["delta"]["schema_version"] == 2
    exported = env_by_id[child_urn]["delta"]["environment_instances"]
    assert [item["instance_id"] for item in exported] == ["environment:plaza"]


def test_dual_export_closes_a_multi_hop_schema_v1_ancestor_chain(repository, tmp_path: Path):
    composed = _composed_over(repository, tmp_path, structural_candidate())
    grandparent = composed.version
    parent = composed.worlds.create_version(
        parent_version_id=grandparent.version_id,
        title="Middle floor",
        created_by=uuid.uuid4(),
    )
    child = composed.worlds.create_version(
        parent_version_id=parent.version_id,
        title="Child plaza",
        created_by=uuid.uuid4(),
    )
    child = composed.worlds.add_environment(
        child.version_id,
        composed.placement("environment:plaza"),
        base_state_sha256=child.state_sha256,
        actor=uuid.uuid4(),
    )
    result = _export(
        repository,
        tmp_path / "multi-hop-dual.wmp",
        extensions=[authored.EXTENSION_KEY, environments.EXTENSION_KEY],
        store=composed.store,
        world_id=composed.worlds.world_id,
    )
    report = verify_package(result.output)
    by_name = {finding.extension: finding for finding in report.extensions}
    authored_by_id = {
        item["version_id"]: item
        for item in by_name[authored.EXTENSION_NAME].authored_world.versions
    }
    env_by_id = {
        item["version_id"]: item
        for item in by_name[environments.EXTENSION_NAME].environment_instances.versions
    }
    grandparent_urn = _urn("alternate-version", grandparent.version_id)
    parent_urn = _urn("alternate-version", parent.version_id)
    child_urn = _urn("alternate-version", child.version_id)
    assert set(authored_by_id) == {grandparent_urn, parent_urn}
    assert set(env_by_id) == {grandparent_urn, parent_urn, child_urn}
    assert set(authored_by_id) & set(env_by_id) == {grandparent_urn, parent_urn}
    for ancestor in (grandparent_urn, parent_urn):
        assert authored_by_id[ancestor]["delta"]["schema_version"] == 1
        assert env_by_id[ancestor]["delta"]["schema_version"] == 1
        assert "environment_instances" not in authored_by_id[ancestor]["delta"]
        assert "environment_instances" not in env_by_id[ancestor]["delta"]
    assert env_by_id[parent_urn]["parent_version_id"] == grandparent_urn
    assert env_by_id[child_urn]["parent_version_id"] == parent_urn
    assert env_by_id[child_urn]["delta"]["schema_version"] == 2
    exported = env_by_id[child_urn]["delta"]["environment_instances"]
    assert [item["instance_id"] for item in exported] == ["environment:plaza"]


def test_an_incapable_loader_omits_a_parent_child_dual_rather_than_inferring_authored_world(
    repository, tmp_path: Path
):
    composed, parent, child = _parent_then_environment_child(repository, tmp_path)
    result = _export(
        repository,
        tmp_path / "parent-child-omit.wmp",
        extensions=[authored.EXTENSION_KEY, environments.EXTENSION_KEY],
        store=composed.store,
        world_id=composed.worlds.world_id,
    )
    report = verify_package(result.output)
    by_name = {finding.extension: finding for finding in report.extensions}
    parent_urn = _urn("alternate-version", parent.version_id)
    child_urn = _urn("alternate-version", child.version_id)
    authored_ids = {
        item["version_id"] for item in by_name[authored.EXTENSION_NAME].authored_world.versions
    }
    env_ids = {
        item["version_id"]
        for item in by_name[environments.EXTENSION_NAME].environment_instances.versions
    }
    assert authored_ids == {parent_urn}
    assert env_ids == {parent_urn, child_urn}
    declared = import_check_package(result.output)
    styles = {f"style-profile:{profile}" for profile in declared["required_style_profiles"]}
    interactions = {
        f"interaction:{capability}" for capability in declared["required_interaction_capabilities"]
    }
    capabilities = frozenset(styles | interactions | {authored.EXTENSION_CAPABILITY})
    checked = import_check_package(result.output, loader_capabilities=capabilities)
    assert checked["loadability"] == "partial"
    authored_report = next(
        item for item in checked["extensions"] if item["extension"] == authored.EXTENSION_NAME
    )
    env_report = next(
        item for item in checked["extensions"] if item["extension"] == environments.EXTENSION_NAME
    )
    assert authored_report["load"] == "loaded"
    assert env_report["load"] == "not loaded"
    omission = (
        f"this loader does not declare {environments.EXTENSION_CAPABILITY}, so "
        "2 alternate version(s) and 1 present environment instance(s) "
        "in this package are not loaded; the loader must say so rather than infer "
        "objects from exulanica-wmp-ext-authored-world@1.0 as the whole authored state"
    )
    assert env_report["not_loaded"] == omission
    assert omission in checked["warnings"]


def test_environment_only_export_includes_the_authored_parent_the_child_names(
    repository, tmp_path: Path
):
    composed, parent, child = _parent_then_environment_child(repository, tmp_path)
    result = _export(
        repository,
        tmp_path / "parent-child-env.wmp",
        extensions=[environments.EXTENSION_KEY],
        store=composed.store,
        world_id=composed.worlds.world_id,
    )
    assert not (result.output / authored.EXTENSION_DIR).exists()
    world = verify_package(result.output).extensions[0].environment_instances
    by_id = {item["version_id"]: item for item in world.versions}
    parent_urn = _urn("alternate-version", parent.version_id)
    child_urn = _urn("alternate-version", child.version_id)
    assert set(by_id) == {parent_urn, child_urn}
    assert by_id[parent_urn]["delta"]["schema_version"] == 1
    assert by_id[child_urn]["parent_version_id"] == parent_urn
    assert by_id[child_urn]["delta"]["schema_version"] == 2


def test_dual_export_of_a_child_whose_parent_stayed_environment_bearing_after_undo_verifies(
    repository, tmp_path: Path
):
    composed = _composed_over(repository, tmp_path, structural_candidate())
    parent = _add(composed, composed.placement("environment:temporary"))
    parent = composed.worlds.undo(
        parent.version_id, base_state_sha256=parent.state_sha256, actor=uuid.uuid4()
    )
    assert parent.environment_instances == ()
    child = composed.worlds.create_version(
        parent_version_id=parent.version_id,
        title="Schema v1 child",
        created_by=uuid.uuid4(),
    )
    lantern = composed.worlds.create_version(
        source_snapshot_id=parent.source_snapshot_id,
        title="Lantern only",
        created_by=uuid.uuid4(),
    )
    lantern = _reviewed_objects(repository, tmp_path, world_id=composed.worlds.world_id).add_object(
        lantern.version_id,
        AuthoredObject(
            object_id="object:lantern",
            asset_sha256=CUBE,
            region_id="region-a",
            transform=Transform(1_200, 0, -450, 0, 1_000),
            origin=ObjectOrigin("authored", "fictional"),
        ),
        base_state_sha256=lantern.state_sha256,
        actor=uuid.uuid4(),
    )
    result = _export(
        repository,
        tmp_path / "undone-parent-child.wmp",
        extensions=[authored.EXTENSION_KEY, environments.EXTENSION_KEY],
        store=composed.store,
        world_id=composed.worlds.world_id,
    )
    report = verify_package(result.output)
    by_name = {finding.extension: finding for finding in report.extensions}
    authored_ids = {
        item["version_id"] for item in by_name[authored.EXTENSION_NAME].authored_world.versions
    }
    env_by_id = {
        item["version_id"]: item
        for item in by_name[environments.EXTENSION_NAME].environment_instances.versions
    }
    parent_urn = _urn("alternate-version", parent.version_id)
    child_urn = _urn("alternate-version", child.version_id)
    assert authored_ids == {_urn("alternate-version", lantern.version_id)}
    assert set(env_by_id) == {parent_urn, child_urn}
    assert env_by_id[parent_urn]["delta"]["schema_version"] == 1
    assert [edit["kind"] for edit in env_by_id[parent_urn]["edits"]] == [
        "add_environment",
        "undo",
    ]
    assert env_by_id[child_urn]["parent_version_id"] == parent_urn
    assert env_by_id[child_urn]["delta"]["schema_version"] == 1
    assert "environment_instances" not in env_by_id[child_urn]["delta"]


def test_dual_export_omits_authored_world_when_every_kept_version_is_environment_bearing(
    repository, tmp_path: Path
):
    composed = _composed_over(repository, tmp_path, structural_candidate())
    _add(composed, composed.placement("environment:plaza"))
    result = _export(
        repository,
        tmp_path / "all-env-dual.wmp",
        extensions=[authored.EXTENSION_KEY, environments.EXTENSION_KEY],
        store=composed.store,
        world_id=composed.worlds.world_id,
    )
    assert not (result.output / authored.EXTENSION_DIR).exists()
    assert authored.EXTENSION_KEY not in result.extensions
    assert result.extensions == (environments.EXTENSION_KEY,)
    report = verify_package(result.output)
    assert [finding.extension for finding in report.extensions] == [environments.EXTENSION_NAME]
    [packaged] = report.extensions[0].environment_instances.versions
    assert packaged["delta"]["schema_version"] == 2


def test_a_1_0_package_payload_is_unchanged_when_only_the_environment_extension_is_added(
    repository, tmp_path: Path
):
    composed = _composed_over(repository, tmp_path, structural_candidate())
    _add(composed, composed.placement("environment:plaza"))
    plain = _export(repository, tmp_path / "plain.wmp", world_id=composed.worlds.world_id)
    extended = _export(
        repository,
        tmp_path / "extended.wmp",
        extensions=[environments.EXTENSION_KEY],
        store=composed.store,
        world_id=composed.worlds.world_id,
    )
    for path in sorted(plain.output.rglob("*.json")):
        relative = str(path.relative_to(plain.output))
        if relative in {"ro-crate-metadata.json", "wmp/manifest.json", "wmp/signature.json"}:
            continue
        assert (extended.output / relative).read_bytes() == path.read_bytes(), relative
