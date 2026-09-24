"""Authored-world 1.1 without a database: behaviour edits admitted, withheld versions by reason.

Each package here is the 1.0 fixture plus one extension directory, re-signed, so a refusal is the
extension version's rule and never a broken signature. The chain gains the edit 1.1 exists for,
``set_object_behaviour``, and the same chain under 1.0 is the control that shows the rule is the
format's closed list and not the chain's shape.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from exulanica.world.authored_delta import canonical_delta_document
from exulanica.world.authored_delta import delta_sha256 as product_delta_sha256
from exulanica.world.objects import AuthoredObject, ObjectBehaviour, ObjectOrigin, Transform
from exulanica.world_package import authored
from exulanica.world_package.extension_formats import (
    AUTHORED_WORLD_1_0,
    AUTHORED_WORLD_1_1,
    REASON_KIND_NOT_ADMITTED,
    REASON_SECTION_NOT_CARRIED,
    REASON_SOURCE_INVALIDATED,
    WITHHELD_RULE,
    ExtensionFormat,
)
from exulanica.world_package.package import PackageError, import_check_package, verify_package

from test_world_package_extension import (
    BASE_LOADER,
    CUBE,
    MOTION,
    _edit,
    _golden_components,
    _objects_only,
    _urn,
    _write_signed,
)

SLOWER = ObjectBehaviour(
    "motion.bounded-path",
    1,
    {"axis": "z", "easing": "smooth", "period_milliseconds": 9_000, "travel_mm": 1_500},
)
#: What a package of this kind withholds, one pair per version: why, and what the reason names.
WITHHELD = (
    (REASON_SOURCE_INVALIDATED, ()),
    (REASON_KIND_NOT_ADMITTED, ("add_point_map",)),
    (REASON_KIND_NOT_ADMITTED, ("add_point_map",)),
)


def _moving_version() -> dict[str, Any]:
    """One version: a lantern placed with motion, moved, then given a slower motion."""
    placed = AuthoredObject(
        object_id="object:lantern",
        asset_sha256=CUBE.content_sha256,
        region_id="region-a",
        transform=Transform(1_200, 0, -450, 785_398, 1_000),
        origin=ObjectOrigin("authored", "fictional"),
        behaviour=ObjectBehaviour(
            "motion.bounded-path",
            1,
            {"axis": "x", "easing": "smooth", "period_milliseconds": 4000, "travel_mm": 2000},
        ),
    )
    moved = replace(placed, transform=Transform(2_400, 0, -450, 785_398, 1_000))
    slower = replace(moved, behaviour=SLOWER)
    states = [product_delta_sha256(**_objects_only([obj])) for obj in (placed, moved, slower)]
    edits = [
        _edit(1, "add_object", authored.EMPTY_DELTA_SHA256, states[0]),
        _edit(2, "move_object", states[0], states[1]),
        _edit(3, "set_object_behaviour", states[1], states[2]),
    ]
    structure = _golden_components()["world/structure.json"]
    return {
        "created_at": "2026-09-23T10:00:00Z",
        "delta": canonical_delta_document(**_objects_only([slower])),
        "edit_seq": len(edits),
        "edits": edits,
        "origin": "authored",
        "parent_version_id": None,
        "source_snapshot_id": structure["lineage"]["snapshot_id"],
        "state_sha256": states[2],
        "style_version_id": None,
        "title": "Slower lantern",
        "version_id": _urn("alternate-version", "moving"),
    }


def _sections(format_: ExtensionFormat, withheld=WITHHELD) -> dict[str, Any]:
    components = _golden_components()
    structure = components["world/structure.json"]
    topology = components["world/topology.json"]
    return authored.build_sections(
        format_,
        versions=[_moving_version()],
        source_snapshots=[
            {
                "current": True,
                "element_ids": sorted(e["element_id"] for e in topology["elements"]),
                "region_ids": sorted(r["region_id"] for r in topology["regions"]),
                "snapshot_id": structure["lineage"]["snapshot_id"],
                "snapshot_sha256": structure["digests"]["snapshot_sha256"],
            }
        ],
        assets=[
            {
                "asset_key": CUBE.asset_key,
                "byte_size": CUBE.byte_size,
                "content_sha256": CUBE.content_sha256,
                "licence_id": CUBE.licence_id,
                "licence_sha256": CUBE.licence_sha256,
                "media_type": CUBE.media_type,
                "ni_uri": authored.ni_uri(CUBE.content_sha256),
                "retrieval": authored.ASSET_RETRIEVAL,
                "summary": CUBE.summary,
                "title": CUBE.title,
            }
        ],
        behaviours=[MOTION],
        withheld=withheld,
    )


def _package(
    root: Path,
    format_: ExtensionFormat = AUTHORED_WORLD_1_1,
    *,
    mutate: Callable[[dict[str, Any]], None] | None = None,
) -> Path:
    components = _golden_components()
    components.update(copy.deepcopy(_sections(format_)))
    if mutate is not None:
        mutate(components)
    return _write_signed(root, components)


def test_a_behaviour_edit_verifies_under_authored_world_1_1(tmp_path: Path):
    report = verify_package(_package(tmp_path / "package"))
    [finding] = report.extensions
    assert (finding.extension_version, finding.directory) == ("1.1", AUTHORED_WORLD_1_1.directory)
    assert finding.rules_checked
    world = finding.authored_world
    [version] = world.versions
    assert [edit["kind"] for edit in version["edits"]][-1] == "set_object_behaviour"
    assert version["delta"]["objects"][0]["behaviour"] == SLOWER.document()
    assert world.withheld_versions == 3
    assert world.declaration["counts"]["withheld_versions"] == 3
    assert AUTHORED_WORLD_1_1.capability in finding.required_loader_capabilities


def test_the_same_chain_is_refused_under_authored_world_1_0(tmp_path: Path):
    """The control: 1.0's closed list, not the chain's shape, is what refuses the edit."""
    with pytest.raises(PackageError, match=r"version .* edit 3 is malformed"):
        verify_package(_package(tmp_path / "package", AUTHORED_WORLD_1_0))


def test_withheld_versions_are_counted_by_reason_and_never_named(tmp_path: Path):
    package = _package(tmp_path / "package")
    versions = (package / AUTHORED_WORLD_1_1.section_path("versions")).read_text()
    withheld = _sections(AUTHORED_WORLD_1_1)[AUTHORED_WORLD_1_1.section_path("versions")][
        "withheld"
    ]
    assert withheld == {
        "reasons": [
            {"names": ["add_point_map"], "reason": REASON_KIND_NOT_ADMITTED, "versions": 2},
            {"names": [], "reason": REASON_SOURCE_INVALIDATED, "versions": 1},
        ],
        "rule": WITHHELD_RULE,
        "versions": 3,
    }
    assert "alternate-version" not in str(withheld)
    assert '"withheld"' in versions


def test_a_loader_of_1_1_without_motion_is_told_what_it_shows_still(tmp_path: Path):
    package = _package(tmp_path / "package")
    declared = BASE_LOADER | {
        AUTHORED_WORLD_1_1.capability,
        authored.ASSET_RESOLUTION_CAPABILITY,
        "asset-media:model/gltf-binary",
    }
    report = import_check_package(package, loader_capabilities=declared)
    assert report["loadability"] == "partial"
    [extension] = report["extensions"]
    assert [item["object_id"] for item in extension["objects_with_unsupported_behaviour"]] == [
        "object:lantern"
    ]
    full = import_check_package(
        package, loader_capabilities=declared | {"behaviour:motion.bounded-path@1"}
    )
    assert full["loadability"] == "complete"


def _withheld(**changes: Any) -> Callable[[dict[str, Any]], None]:
    def mutate(components: dict[str, Any]) -> None:
        document = components[AUTHORED_WORLD_1_1.section_path("versions")]["withheld"]
        for key, value in changes.items():
            if key == "first_reason":
                document["reasons"][0].update(value)
            else:
                document[key] = value

    return mutate


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (_withheld(reasons=[]), "withheld is malformed"),
        (_withheld(versions=4), "withheld is malformed"),
        (_withheld(rule="counted"), "withheld is malformed"),
        (_withheld(first_reason={"reason": "felt_like_it"}), "withheld is malformed"),
        (_withheld(first_reason={"names": []}), "withheld is malformed"),
        (_withheld(first_reason={"names": ["Add Point Map"]}), "withheld is malformed"),
        (
            _withheld(first_reason={"names": ["add_point_map", "add_point_map"]}),
            "withheld is malformed",
        ),
        (_withheld(first_reason={"versions": 0}), "withheld is malformed"),
        (
            _withheld(
                reasons=[
                    {"names": [], "reason": REASON_SOURCE_INVALIDATED, "versions": 1},
                    {"names": ["add_point_map"], "reason": REASON_KIND_NOT_ADMITTED, "versions": 2},
                ]
            ),
            "withheld is malformed",
        ),
        (
            _withheld(
                reasons=[
                    {
                        "names": ["point_map_instances"],
                        "reason": REASON_SOURCE_INVALIDATED,
                        "versions": 3,
                    },
                ]
            ),
            "withheld is malformed",
        ),
        (
            lambda components: components[AUTHORED_WORLD_1_1.section_path("versions")].update(
                withheld={"invalidated_source_versions": 3, "reason": authored.WITHHELD_REASON}
            ),
            "expected exactly",
        ),
    ],
)
def test_a_withheld_section_that_breaks_the_1_1_rules_is_refused(
    tmp_path: Path, mutate: Callable[[dict[str, Any]], None], message: str
):
    with pytest.raises(PackageError, match=message):
        verify_package(_package(tmp_path / "package", mutate=mutate))


def test_a_section_reason_names_the_sections_it_is_about(tmp_path: Path):
    """The third reason verifies too, so the vocabulary the plan writes is the one verified."""

    def mutate(components: dict[str, Any]) -> None:
        document = components[AUTHORED_WORLD_1_1.section_path("versions")]["withheld"]
        # Reasons sort by reason, then names: "section_not_carried" before "source_invalidated".
        document["reasons"].insert(
            1,
            {"names": ["point_map_instances"], "reason": REASON_SECTION_NOT_CARRIED, "versions": 1},
        )
        document["versions"] = 4
        components[AUTHORED_WORLD_1_1.declaration_path]["counts"]["withheld_versions"] = 4

    world = verify_package(_package(tmp_path / "package", mutate=mutate)).extensions[0]
    assert world.authored_world.withheld_versions == 4
