"""The environment-instances extension, without changing WMP 1.0 or authored-world 1.0."""

from __future__ import annotations

import copy
import json
import uuid
from pathlib import Path

import pytest
from exulanica.world.environment_instances import (
    EnvironmentInstance,
    EnvironmentSelection,
    EnvironmentSourceBinding,
    SourceAnchor,
)
from exulanica.world.objects import ObjectOrigin, Transform, canonical_delta_document
from exulanica.world.objects import delta_sha256 as product_delta_sha256
from exulanica.world_package import authored, environments
from exulanica.world_package.package import PackageError, import_check_package, verify_package

from test_world_package_extension import (
    BASE_LOADER,
    GOLDEN,
    _extended,
    _golden_components,
    _golden_copy,
    _sections,
    _urn,
    _write_signed,
)

ADMISSION = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
PLACE = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
RENDER = uuid.UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")
SOURCE_SHA = "11" * 32
RENDER_SHA = "22" * 32
RECEIPT_SHA = "33" * 32
FRAME = {"name": "nyc-grid", "axis_order": ["east", "north", "height"]}
BOUNDS = {
    "kind": "bbox",
    "frame_name": "nyc-grid",
    "coordinate_scale": 1000,
    "coordinates": [0, 0, 0, 100, 100, 100],
}
ENV_LOADER = BASE_LOADER | {
    environments.EXTENSION_CAPABILITY,
    environments.ENVIRONMENT_SOURCE_CAPABILITY,
}


def _instance(
    *, instance_id: str = "environment:plaza", removed: bool = False
) -> EnvironmentInstance:
    return EnvironmentInstance(
        instance_id=instance_id,
        source=EnvironmentSourceBinding(
            admission_id=ADMISSION,
            render_asset_id=RENDER,
            publication_id=None,
            source_sha256=SOURCE_SHA,
            source_receipt_sha256=RECEIPT_SHA,
            render_sha256=RENDER_SHA,
            render_receipt_sha256=RECEIPT_SHA,
            index_sha256=None,
            index_receipt_sha256=None,
            publication_receipt_sha256=None,
            place_id=PLACE,
            frame=FRAME,
            bounds=BOUNDS,
            anchor=SourceAnchor("nyc-grid", 1000, (10, 20, 0)),
            selection=EnvironmentSelection("whole_asset"),
        ),
        region_id="region-a",
        transform=Transform(1_200, 0, 0, 0, 1_000),
        origin=ObjectOrigin("authored", "fictional"),
        removed=removed,
    )


def _environment_sections(*, availability: str = "available") -> dict[str, object]:
    instance = _instance()
    added = product_delta_sha256([], [], [instance])
    structure = json.loads((GOLDEN / "world/structure.json").read_bytes())
    topology = json.loads((GOLDEN / "world/topology.json").read_bytes())
    version = {
        "created_at": "2026-09-21T10:00:00Z",
        "delta": canonical_delta_document([], [], [instance]),
        "edit_seq": 1,
        "edits": [
            {
                "base_state_sha256": authored.EMPTY_DELTA_SHA256,
                "edit_id": _urn("alternate-edit", "env-1"),
                "edit_seq": 1,
                "element_id": None,
                "environment_instance_id": instance.instance_id,
                "kind": "add_environment",
                "object_id": None,
                "recorded_at": "2026-09-21T10:00:00Z",
                "result_state_sha256": added,
                "undone_edit_id": None,
            }
        ],
        "environment_availability": [
            {"availability": availability, "instance_id": instance.instance_id}
        ],
        "origin": "authored",
        "parent_version_id": None,
        "source_snapshot_id": structure["lineage"]["snapshot_id"],
        "state_sha256": added,
        "style_version_id": None,
        "title": "Placed plaza",
        "version_id": _urn("alternate-version", "env"),
    }
    return environments.build_sections(
        versions=[version],
        source_snapshots=[
            {
                "current": True,
                "element_ids": sorted(e["element_id"] for e in topology["elements"]),
                "region_ids": sorted(r["region_id"] for r in topology["regions"]),
                "snapshot_id": structure["lineage"]["snapshot_id"],
                "snapshot_sha256": structure["digests"]["snapshot_sha256"],
            }
        ],
        assets=[],
        behaviours=[],
        withheld_versions=0,
    )


def _environment_package(root: Path, **options: str) -> Path:
    components = _golden_components()
    components.update(copy.deepcopy(_environment_sections(**options)))
    return _write_signed(root, components)


def test_a_1_0_package_written_before_either_extension_still_verifies(tmp_path: Path):
    report = verify_package(_golden_copy(tmp_path))
    assert report.profile_version == "exulanica-wmp-1.0"
    assert report.extensions == ()


def test_schema_version_2_is_refused_under_authored_world_1_0(tmp_path: Path):
    def mutate(components: dict[str, object]) -> None:
        version = components[authored.VERSIONS_PATH]["items"][0]
        version["delta"]["schema_version"] = 2

    with pytest.raises(PackageError, match="unknown delta schema"):
        verify_package(_extended(tmp_path / "authored-v2", mutate=mutate))


def test_the_environment_inclusive_digest_rederives_without_the_product_code():
    sections = _environment_sections()
    [version] = sections[environments.VERSIONS_PATH]["items"]
    assert environments.delta_sha256(version["delta"]) == version["state_sha256"]
    assert version["state_sha256"] == product_delta_sha256([], [], [_instance()])
    assert version["delta"]["schema_version"] == 2
    assert "environment_instances" in version["delta"]


def test_the_environment_extension_verifies_and_does_not_assess_loading(tmp_path: Path):
    report = verify_package(_environment_package(tmp_path / "env")).as_dict()
    assert report["verified"] is True
    [extension] = report["extensions"]
    assert extension["extension"] == environments.EXTENSION_NAME
    assert extension["extension_version"] == "1.0"
    assert extension["rules"] == "checked by this verifier"
    assert report["runtime_loadability"].startswith("not assessed")
    crate = json.loads(
        (_environment_package(tmp_path / "crate") / "ro-crate-metadata.json").read_bytes()
    )
    nodes = {node["@id"]: node for node in crate["@graph"]}
    assert nodes["./"]["conformsTo"] == {
        "@id": "https://exulanica.local/profiles/world-memory-package/1.0"
    }
    assert nodes[environments.DECLARATION_PATH]["conformsTo"] == {
        "@id": environments.EXTENSION_PROFILE_ID
    }


def test_a_verifier_that_knows_no_extension_still_verifies_an_environment_package(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from exulanica.world_package import package as package_module

    package = _environment_package(tmp_path / "env")
    monkeypatch.setattr(package_module, "_verify_extensions", lambda files, paths: ())
    report = verify_package(package)
    assert report.profile_version == "exulanica-wmp-1.0"
    assert report.file_count == 18 + len(environments.EXTENSION_PATHS)


def test_authored_world_1_0_on_the_same_package_still_verifies(tmp_path: Path):
    components = _golden_components()
    components.update(copy.deepcopy(_sections()))
    components.update(copy.deepcopy(_environment_sections()))
    package = _write_signed(tmp_path / "both", components)
    report = verify_package(package)
    by_name = {finding.extension: finding for finding in report.extensions}
    assert by_name[authored.EXTENSION_NAME].rules_checked
    assert by_name[environments.EXTENSION_NAME].rules_checked
    authored_delta = by_name[authored.EXTENSION_NAME].authored_world.versions[0]["delta"]
    assert authored_delta["schema_version"] == 1
    assert "environment_instances" not in authored_delta


def test_a_loader_without_the_environment_capability_is_told_to_omit_not_infer(
    tmp_path: Path,
):
    package = _environment_package(tmp_path / "env")
    checked = import_check_package(package, loader_capabilities=BASE_LOADER)
    assert checked["compatible"] is True
    assert checked["loadability"] == "partial"
    [extension] = checked["extensions"]
    assert extension["load"] == "not loaded"
    assert environments.EXTENSION_CAPABILITY in extension["unsupported_capabilities"]
    assert "1 alternate version(s) and 1 present environment instance(s)" in extension["not_loaded"]
    assert "rather than infer objects from exulanica-wmp-ext-authored-world@1.0" in extension[
        "not_loaded"
    ]


def test_a_loader_with_the_environment_capability_loads_and_names_unavailable_instances(
    tmp_path: Path,
):
    package = _environment_package(tmp_path / "withdrawn", availability="withdrawn")
    checked = import_check_package(package, loader_capabilities=ENV_LOADER)
    assert checked["loadability"] == "complete"
    [extension] = checked["extensions"]
    assert extension["load"] == "loaded"
    assert extension["instances_unavailable"] == [
        {
            "availability": "withdrawn",
            "instance_id": "environment:plaza",
            "version_id": _urn("alternate-version", "env"),
        }
    ]


def test_a_signed_but_inconsistent_environment_digest_is_refused(tmp_path: Path):
    def mutate(components: dict[str, object]) -> None:
        components[environments.VERSIONS_PATH]["items"][0]["delta"]["environment_instances"][0][
            "transform"
        ]["x_mm"] = 9_999

    components = _golden_components()
    components.update(copy.deepcopy(_environment_sections()))
    mutate(components)
    package = _write_signed(tmp_path / "bad-digest", components)
    with pytest.raises(PackageError, match="does not re-derive"):
        verify_package(package)
