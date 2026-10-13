"""Source physical proxies include nonwalking fixtures and exports cannot drop affinity."""

from __future__ import annotations

import copy
import uuid
from dataclasses import replace

import pytest
from exulanica.canonical import sha256_of_canonical
from exulanica.things.kinds import shipped_thing_kinds
from exulanica.world.authored_delta import version_delta_sha256
from exulanica.world.composers import site_plan
from exulanica.world.kinds.document import read_kind
from exulanica.world.objects import ObjectOrigin, Transform
from exulanica.world.placed_things import (
    PlacedThing,
    ThingKindReference,
    ThingPlacement,
    read_support_reference,
)
from exulanica.world.site_drawing import site_drawing
from exulanica.world.society_authored_ground import (
    authored_ground_from_snapshot,
    supported_things_projection,
)
from exulanica.world.society_input_policy import OFF_GROUND
from exulanica.world.support_placement import (
    PlacementContext,
    SupportPlacementRefused,
    validate_supported_placement,
)
from exulanica.world.support_placement_source import source_from_documents
from exulanica.world_package.export_partition import (
    REASON_SECTION_NOT_CARRIED,
    PlaneVersion,
    plan_export,
)
from exulanica.world_package.extension_formats import AUTHORED_WORLD_1_1, ENVIRONMENT_INSTANCES_1_1

from kind_briefs import fixture_kind
from living_town_support import version_of
from test_support_site import authoring, context


def test_nonwalking_source_geometry_remains_a_physical_placement_obstruction():
    document = copy.deepcopy(fixture_kind("farm"))
    next(part for part in document["parts"] if part["key"] == "hay_bale")["blocks"] = 0
    kind = read_kind(document)
    world = site_plan.compose_kind(
        kind,
        kind.values("small_farm"),
        "world:physical-test",
        support=authoring(context()["base_place"]),
    )
    drawing = site_drawing(
        world_id=world.receipt["world_id"],
        receipt=world.receipt,
        receipt_sha256=world.receipt_sha256,
        records=world.records,
    )
    support = site_plan.receipt_support(world.receipt, world.records)
    snapshot = uuid.uuid4()
    source = source_from_documents(
        world.receipt["world_id"],
        snapshot,
        world.receipt_sha256,
        drawing,
        support.projection.place(),
    )
    record = next(
        r for r in world.records if r.RECORD_KIND == "site.fixture" and r.part_key == "hay_bale"
    )
    assert not record.blocks
    key = "source-slot/" + sha256_of_canonical(record.identity).hex()
    volume = next(v for v in source.physical_solids if v.solid_id == key)
    assert volume.box_mm[2] == 0 and volume.box_mm[5] == record.height_mm
    ctx = PlacementContext(
        source.world_id,
        uuid.uuid4(),
        snapshot,
        source.receipt_sha256,
        "a" * 64,
        source.region_id,
        source.network,
        other_solids=source.physical_solids,
        actor_volumes=source.actor_volumes,
    )
    lantern = shipped_thing_kinds()[("lantern", 1)]
    p = ThingPlacement(
        "thing:test",
        ThingKindReference(lantern.kind, lantern.version, lantern.sha256),
        source.region_id,
        Transform(record.x_mm, 0, -record.y_mm, 0, 1000),
        ObjectOrigin("authored", "fictional"),
    )
    with pytest.raises(SupportPlacementRefused, match="obstruction"):
        validate_supported_placement(p, lantern, ctx.reference("base-ground"), context=ctx)


def test_package_formats_withhold_support_bearing_things_section_and_lineage():
    formats = [AUTHORED_WORLD_1_1, ENVIRONMENT_INSTANCES_1_1]
    version = PlaneVersion(
        "supported",
        None,
        source_invalidated=False,
        chain_kinds=frozenset({"add_thing"}),
        chain_subjects=frozenset(),
        state_sections=frozenset({"things"}),
    )
    plan = plan_export([version], formats)
    assert all("supported" not in exported for exported in plan.exported.values())
    # Both the unadmitted thing edit and uncarried things section remain explicit; no format
    # may recover the transform while silently forgetting the new nested v2 support document.
    withheld = [entry for rows in plan.withheld.values() for entry in rows]
    assert any(entry.version_id == "supported" for entry in withheld)
    section_only = plan_export([replace(version, chain_kinds=frozenset())], formats)
    assert any(
        entry.reason == REASON_SECTION_NOT_CARRIED and entry.names == ("things",)
        for rows in section_only.withheld.values()
        for entry in rows
    )


@pytest.mark.parametrize(
    "surface,pose,expected",
    [
        (
            "base-ground",
            Transform(2000, 0, -122000, 0, 1000),
            "supported_thing_projection_unavailable",
        ),
        ("deck", Transform(55000, 150, -8000, 0, 1000), None),
    ],
)
def test_admitted_ground_support_never_uses_an_untrue_off_ground_reason(surface, pose, expected):
    kind = read_kind(fixture_kind("farm"))
    spec = authoring(context()["base_place"])
    spec["surfaces"][0]["rect_mm"] = [50000, -10340, 58000, -4340]
    world = site_plan.compose_kind(
        kind, kind.values("small_farm"), "world:review-ground", support=spec
    )
    snapshot = uuid.UUID("ef6a7f0c-573e-4e6e-b84a-df69b185c77c")
    drawing = site_drawing(
        world_id=world.receipt["world_id"],
        receipt=world.receipt,
        receipt_sha256=world.receipt_sha256,
        records=world.records,
    )
    support = site_plan.receipt_support(world.receipt, world.records)
    source = source_from_documents(
        world.receipt["world_id"],
        snapshot,
        world.receipt_sha256,
        drawing,
        support.projection.place(),
    )
    version = version_of(source.world_id, snapshot)
    ctx = PlacementContext(
        source.world_id,
        version.version_id,
        snapshot,
        source.receipt_sha256,
        version.state_sha256,
        source.region_id,
        source.network,
        source.physical_solids,
        (),
        source.actor_volumes,
    )
    bench = shipped_thing_kinds()[("bench", 2)]
    placement = ThingPlacement(
        "thing:bench",
        ThingKindReference(bench.kind, bench.version, bench.sha256),
        source.region_id,
        pose,
        ObjectOrigin("authored", "fictional"),
    )
    # Clearance/admission is a positive control for both poses. Ground projection limitations
    # must not be disguised as geometry failure or an invented off-ground condition.
    validate_supported_placement(placement, bench, ctx.reference(surface), context=ctx)
    thing = PlacedThing(
        placement.thing_id,
        placement.kind,
        placement.region_id,
        placement.transform,
        placement.origin,
        support=read_support_reference(ctx.reference(surface)),
    )
    version = replace(version, things=(thing,))
    version = replace(version, state_sha256=version_delta_sha256(version))
    ground = authored_ground_from_snapshot(
        world_id=source.world_id,
        snapshot_id=snapshot,
        snapshot_sha256=world.receipt_sha256,
        composer_key=world.candidate.composer_key,
        composer_version=world.candidate.composer_version,
        topology=world.candidate.topology,
        placement=world.candidate.placement,
    )
    omitted, records, reason = supported_things_projection(
        version, ground, {thing.thing_id: bench}, source
    )
    assert reason == expected
    if expected is not None:
        assert omitted == frozenset() and records == []
        assert pose.y_mm == ground.elevation_mm == 0
    else:
        assert omitted == frozenset({thing.thing_id}) and records[0]["reason"] == OFF_GROUND
        assert pose.y_mm != ground.elevation_mm
