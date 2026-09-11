"""Lift an authored gallery into a plain structural layout without changing source bindings.

Positions are authored layout, never measured geometry. Each source keeps its own element,
including missing sources and world-owned slots. Evidence cards have no collision geometry.
"""

from __future__ import annotations

from typing import Any

from exulanica.world.models import TopologyContract
from exulanica.world.structure import SpatialCandidate


def composed_candidate(
    contract: TopologyContract, graph_sha256: str, reconstruction_sha256: str
) -> SpatialCandidate:
    regions = sorted(contract.region_ids)
    elements: list[dict[str, Any]] = []
    destinations: list[dict[str, Any]] = []
    placements: list[dict[str, Any]] = []
    destination_placements: list[dict[str, Any]] = []
    source_ordinals: dict[str | None, int] = {}
    for source in sorted(contract.source_slots, key=lambda s: str(s.source_id)):
        region = source.region_id
        element_id = f"element:source:{source.source_id}"
        span = source.evidence_span_id
        local_ordinal = source_ordinals.get(region, 0)
        source_ordinals[region] = local_ordinal + 1
        elements.append(
            {
                "element_id": element_id,
                "owner": {
                    "kind": "region" if region else "world",
                    "id": region or contract.world_id,
                },
                "module": {
                    "key": "region.evidence-cards",
                    "version": 1,
                    "requested_key": "region.evidence-cards",
                },
                "lineage": {
                    "recipe_key": "region.rung-3",
                    "recipe_version": 1,
                    "slot_key": source.slot_key,
                },
                "collision": {"kind": "none"},
                "evidence": (
                    {"kind": "span", "span_id": str(span)}
                    if span is not None
                    else {"kind": "missing", "reason": source.missing_reason}
                ),
                "attachment": None,
                "streaming_key": "world-asset:region.evidence-cards@1",
            }
        )
        placements.append(
            {
                "element_id": element_id,
                "x_mm": regions.index(region) * 10_000 if region is not None else 0,
                "y_mm": 0,
                "z_mm": local_ordinal * 2_000,
                "yaw_microradians": 0,
                "scale_milli": 1_000,
            }
        )
    for ordinal, region in enumerate(regions):
        destination_id = f"destination:{region}"
        destinations.append(
            {"destination_id": destination_id, "region_id": region, "required": True}
        )
        destination_placements.append(
            {"destination_id": destination_id, "x_mm": ordinal * 10_000, "y_mm": 1_600, "z_mm": 0}
        )

    edges = [
        {
            "from": f"destination:{regions[index]}",
            "to": f"destination:{regions[index + 1]}",
            "kind": "field",
            "max_slope_millidegrees": 0,
        }
        for index in range(len(regions) - 1)
    ]

    topology = {
        "schema_version": 1,
        "world_id": contract.world_id,
        "regions": [{"region_id": region} for region in regions],
        "elements": elements,
        "navigation": {
            "agent_radius_mm": 300,
            "maximum_slope_millidegrees": 15_000,
            "destinations": destinations,
            "edges": edges,
        },
        "dependencies": [],
    }
    layout = {
        "schema_version": 1,
        "layout_version": 1,
        "regions": [
            {"region_id": region, "creation_ordinal": ordinal}
            for ordinal, region in enumerate(regions)
        ],
    }
    placement = {
        "schema_version": 1,
        "coordinate_unit": "millimetre",
        "elements": placements,
        "destinations": destination_placements,
    }
    neighborhood = {
        "schema_version": 1,
        "neighborhood_version": 1,
        "layout_version": 1,
        "neighborhoods": [{"neighborhood_id": "neighborhood:0", "region_ids": list(regions)}],
    }

    return SpatialCandidate(
        graph_sha256, reconstruction_sha256, topology, layout, placement, neighborhood
    )
