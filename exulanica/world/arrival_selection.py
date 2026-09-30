"""Choose a saved world's opening region from its owned, drawable source regions.

The v4 presentation policy makes the world's own region eligible before the Atlas five-region
display limit. Source membership comes from the saved structural snapshot; graph membership says
whether the browser can draw that region. An unrelated workspace region cannot become this
world's society ground merely because its photograph was taken earlier.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import re
import uuid
from collections import Counter
from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
ARRIVAL_POLICY = json.loads(
    (Path(__file__).resolve().parents[2] / "assets/catalogs/arrival/arrival-presentation.v1.json")
    .read_text()
)
if (
    ARRIVAL_POLICY["profile"] != "exulanica.arrival-presentation/v1"
    or ARRIVAL_POLICY["layout_scale_milli"] != 1000
    or ARRIVAL_POLICY["scale_is_metric"] is not False
):
    raise ValueError("the arrival presentation policy does not state the production layout")


class RetainedScenePin(BaseModel):
    """The exact scene build a v4 society and its entry share."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    profile: Literal["exulanica.arrival-scene-pin/v1"]
    world_id: str = Field(min_length=1)
    version_id: uuid.UUID
    source_snapshot_id: uuid.UUID
    region_id: str = Field(min_length=1)
    scene_id: uuid.UUID
    job_id: uuid.UUID
    pose_receipt_sha256: str = Field(pattern=_SHA256.pattern)
    placement_receipt_sha256: str = Field(pattern=_SHA256.pattern)
    gate_receipt_sha256: str = Field(pattern=_SHA256.pattern)


class PointMapArrivalPin(BaseModel):
    """One exact standalone estimate of an owned photograph."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    profile: Literal["exulanica.arrival-point-map-pin/v1"]
    world_id: str = Field(min_length=1)
    version_id: uuid.UUID
    source_snapshot_id: uuid.UUID
    region_id: str = Field(min_length=1)
    capture_id: uuid.UUID
    artifact_id: uuid.UUID
    content_sha256: str = Field(pattern=_SHA256.pattern)
    byte_size: StrictInt = Field(gt=0)


class PhotographArrivalPin(BaseModel):
    """The source-photograph fallback when an owned region has no authorized geometry."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    profile: Literal["exulanica.arrival-photograph-pin/v1"]
    world_id: str = Field(min_length=1)
    version_id: uuid.UUID
    source_snapshot_id: uuid.UUID
    region_id: str = Field(min_length=1)
    capture_id: uuid.UUID


class ArrivalDescriptor(BaseModel):
    """Region-local opening pose and exact source under the versioned display policy."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    profile: Literal["exulanica.arrival-descriptor/v1"]
    presentation_policy: Literal["exulanica.arrival-presentation/v1"]
    region_id: str = Field(min_length=1)
    position_local_mm: tuple[StrictInt, StrictInt, StrictInt]
    forward_local_millionths: tuple[StrictInt, StrictInt, StrictInt]
    source: RetainedScenePin | PointMapArrivalPin | PhotographArrivalPin = Field(
        discriminator="profile"
    )

    @model_validator(mode="after")
    def matching_region(self) -> ArrivalDescriptor:
        if self.region_id != self.source.region_id:
            raise ValueError("arrival source region disagrees with pose")
        if any(abs(value) > 10**9 for value in self.position_local_mm):
            raise ValueError("arrival position exceeds the local frame")
        if any(abs(value) > 10**6 for value in self.forward_local_millionths):
            raise ValueError("arrival direction component exceeds one")
        if math.hypot(*self.forward_local_millionths) < 10**5:
            raise ValueError("arrival forward direction is empty")
        return self


def fallback_arrival_pose(anchor_count: int) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    """The region-local form of the renderer's photograph-only opening rule.

    ``footprintOf(seedAnchors)`` is a monotone phyllotaxis radius, so only the outermost of the
    ``anchor_count`` supported occurrences matters. No layout solver or island placement is read.
    """
    if anchor_count < 0:
        raise ValueError("negative arrival anchor count")
    radius = 0.0 if anchor_count == 0 else 1.6 * math.sqrt(anchor_count - 0.5)
    return fallback_arrival_pose_for_radius(radius + 2.5)


def fallback_arrival_pose_for_radius(
    footprint: float,
) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    """The local fallback camera when a geometry branch supplies the island's radius."""
    if not math.isfinite(footprint) or footprint < 0:
        raise ValueError("invalid arrival footprint")
    policy = ARRIVAL_POLICY
    distance = max(
        policy["fallback_min_distance_mm"],
        min(
            policy["fallback_max_distance_mm"],
            round(footprint * policy["fallback_radius_fraction_millionths"] / 1000),
        ),
    )
    pitch = policy["fallback_pitch_microradians"] / 1_000_000
    forward = (0, round(math.sin(pitch) * 1_000_000), -round(math.cos(pitch) * 1_000_000))
    return (0, policy["eye_height_mm"], distance), forward


@dataclass(frozen=True, slots=True)
class OwnedSource:
    region_id: str
    capture_ids: tuple[str, ...]
    captured_at: dt.datetime | None
    available: bool


def unique_source_regions(sources: Iterable[OwnedSource]) -> dict[str, str]:
    """Map captures to one region, omitting ambiguous captures as the browser does."""
    regions: dict[str, str] = {}
    ambiguous: set[str] = set()
    for source in sources:
        for capture_id in source.capture_ids:
            held = regions.get(capture_id)
            if held is not None and held != source.region_id:
                ambiguous.add(capture_id)
            else:
                regions[capture_id] = source.region_id
    for capture_id in ambiguous:
        regions.pop(capture_id, None)
    return regions


def select_owned_opening_region(
    sources: Sequence[OwnedSource],
    topology_regions: Collection[str],
    graph_captures: Collection[str],
    placement_regions: Sequence[str],
) -> str | None:
    """Select an authorized world region by placement count, then capture order and id.

    A region is drawable only when the world's live source media and the graph both name one of
    its unambiguous captures. The graph requirement matches ``buildIslands``: a source present
    only in the media catalog creates no Atlas island. The browser's v4 policy moves the chosen
    owned island before its five-island cut, without moving any source into another region.
    """
    permitted = set(topology_regions)
    graph = set(graph_captures)
    mapped = unique_source_regions(sources)
    eligible: dict[str, tuple[dt.datetime, str]] = {}
    for source in sources:
        if not source.available or source.region_id not in permitted:
            continue
        if not any(mapped.get(capture_id) == source.region_id and capture_id in graph
                   for capture_id in source.capture_ids):
            continue
        # Null time sorts after dated captures, like graph-client's island order.
        time = source.captured_at or dt.datetime.max.replace(tzinfo=dt.UTC)
        key = (time, source.region_id)
        if source.region_id not in eligible or key < eligible[source.region_id]:
            eligible[source.region_id] = key
    if not eligible:
        return None
    counts = Counter(placement_regions)
    return min(eligible, key=lambda region: (-counts[region], *eligible[region]))
