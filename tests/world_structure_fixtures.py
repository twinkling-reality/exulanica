"""Synthetic spatial-world candidates for world-structure tests.

Factories build :class:`~exulanica.world.SpatialCandidate` documents and optional
placement migrations. They are not loaded by the application.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import replace

from exulanica.world import PlacementMigration, SpatialCandidate

from world_support import FIXTURE_WORLD_ID


def digest(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def structural_candidate(
    *,
    graph: str = "graph-a",
    reconstruction: str = "reconstruction-a",
    region_b_x_mm: int = 10_000,
    evidence_span_id: uuid.UUID | None = None,
    migrations: tuple[PlacementMigration, ...] = (),
    world_id: str = FIXTURE_WORLD_ID,
) -> SpatialCandidate:
    evidence_a = (
        {"kind": "span", "span_id": str(evidence_span_id)}
        if evidence_span_id is not None
        else {"kind": "missing", "reason": "no authorised source was recorded"}
    )
    topology = {
        "schema_version": 1,
        "world_id": world_id,
        "regions": [{"region_id": "region-a"}, {"region_id": "region-b"}],
        "elements": [
            {
                "element_id": "element:region-a:root",
                "owner": {"kind": "region", "id": "region-a"},
                "module": {
                    "key": "region.evidence-cards",
                    "version": 1,
                    "requested_key": "region.evidence-cards",
                },
                "lineage": {
                    "recipe_key": "region.rung-3",
                    "recipe_version": 1,
                    "slot_key": "root",
                },
                "collision": {"kind": "circle", "radius_mm": 1_000},
                "evidence": evidence_a,
                "attachment": None,
                "streaming_key": "world-asset:region.evidence-cards@1",
            },
            {
                "element_id": "element:region-b:root",
                "owner": {"kind": "region", "id": "region-b"},
                "module": {
                    "key": "region.evidence-cards",
                    "version": 1,
                    "requested_key": "region.evidence-cards",
                },
                "lineage": {
                    "recipe_key": "region.rung-3",
                    "recipe_version": 1,
                    "slot_key": "root",
                },
                "collision": {"kind": "circle", "radius_mm": 1_000},
                "evidence": {"kind": "missing", "reason": "source is not in this archive"},
                "attachment": None,
                "streaming_key": "world-asset:region.evidence-cards@1",
            },
        ],
        "navigation": {
            "agent_radius_mm": 300,
            "maximum_slope_millidegrees": 15_000,
            "destinations": [
                {
                    "destination_id": "destination:region-a",
                    "region_id": "region-a",
                    "required": True,
                },
                {
                    "destination_id": "destination:region-b",
                    "region_id": "region-b",
                    "required": True,
                },
            ],
            "edges": [
                {
                    "from": "destination:region-a",
                    "to": "destination:region-b",
                    "kind": "field",
                    "max_slope_millidegrees": 0,
                }
            ],
        },
        "dependencies": [],
    }
    layout = {
        "schema_version": 1,
        "layout_version": 1,
        "regions": [
            {"region_id": "region-a", "creation_ordinal": 0},
            {"region_id": "region-b", "creation_ordinal": 1},
        ],
    }
    placement = {
        "schema_version": 1,
        "coordinate_unit": "millimetre",
        "elements": [
            {
                "element_id": "element:region-a:root",
                "x_mm": 0,
                "y_mm": 0,
                "z_mm": 0,
                "yaw_microradians": 0,
                "scale_milli": 1_000,
            },
            {
                "element_id": "element:region-b:root",
                "x_mm": region_b_x_mm,
                "y_mm": 0,
                "z_mm": 0,
                "yaw_microradians": 0,
                "scale_milli": 1_000,
            },
        ],
        "destinations": [
            {"destination_id": "destination:region-a", "x_mm": 0, "y_mm": 1_600, "z_mm": 0},
            {
                "destination_id": "destination:region-b",
                "x_mm": region_b_x_mm,
                "y_mm": 1_600,
                "z_mm": 0,
            },
        ],
    }
    neighborhood = {
        "schema_version": 1,
        "neighborhood_version": 1,
        "layout_version": 1,
        "neighborhoods": [
            {"neighborhood_id": "neighborhood:0", "region_ids": ["region-a", "region-b"]}
        ],
    }
    return SpatialCandidate(
        digest(graph),
        digest(reconstruction),
        topology,
        layout,
        placement,
        neighborhood,
        placement_migrations=migrations,
    )


def with_topology(candidate: SpatialCandidate, topology: dict) -> SpatialCandidate:
    return replace(candidate, topology=topology)
