"""Lift an authored gallery into a plain structural layout without changing source bindings.

Each source keeps its own element, including missing sources and world-owned slots. Evidence cards
have no collision geometry.

Nothing here has a position. The composer is given which sources belong to which region and
nothing about where anything is, so every element and every region's destination is written as
explicitly unplaced, and no navigation edge is asserted between regions. It used to space elements
by their index in a sorted list and chain destinations in that same order, which is a sort
presented as a place.
"""

from __future__ import annotations

from typing import Any, Final

from exulanica.world.models import TopologyContract
from exulanica.world.structure import SpatialCandidate

UNPLACED_REASON: Final = "no authored or measured position"


def composed_candidate(
    contract: TopologyContract, graph_sha256: str, reconstruction_sha256: str
) -> SpatialCandidate:
    regions = sorted(contract.region_ids)
    elements: list[dict[str, Any]] = []
    destinations: list[dict[str, Any]] = []
    unplaced_elements: list[dict[str, Any]] = []
    unplaced_destinations: list[dict[str, Any]] = []
    for source in sorted(contract.source_slots, key=lambda s: str(s.source_id)):
        region = source.region_id
        element_id = f"element:source:{source.source_id}"
        span = source.evidence_span_id
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
        unplaced_elements.append({"element_id": element_id, "reason": UNPLACED_REASON})
    for region in regions:
        destination_id = f"destination:{region}"
        destinations.append(
            {"destination_id": destination_id, "region_id": region, "required": True}
        )
        unplaced_destinations.append({"destination_id": destination_id, "reason": UNPLACED_REASON})

    topology = {
        "schema_version": 1,
        "world_id": contract.world_id,
        "regions": [{"region_id": region} for region in regions],
        "elements": elements,
        "navigation": {
            "agent_radius_mm": 300,
            "maximum_slope_millidegrees": 15_000,
            "destinations": destinations,
            "edges": [],
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
    placement: dict[str, Any] = {
        "schema_version": 1,
        "coordinate_unit": "millimetre",
        "elements": [],
        "destinations": [],
    }
    # An empty list is never written: absent means nothing is unplaced, so the digest has one input.
    if unplaced_elements:
        placement["unplaced_elements"] = unplaced_elements
    if unplaced_destinations:
        placement["unplaced_destinations"] = unplaced_destinations
    neighborhood = {
        "schema_version": 1,
        "neighborhood_version": 1,
        "layout_version": 1,
        "neighborhoods": [{"neighborhood_id": "neighborhood:0", "region_ids": list(regions)}],
    }

    return SpatialCandidate(
        graph_sha256, reconstruction_sha256, topology, layout, placement, neighborhood
    )
