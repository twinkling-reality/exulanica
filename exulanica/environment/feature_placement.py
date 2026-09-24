"""A selected NYC Open Data building, as the authored environment instance an edit would place.

The NYC environment panel proposes placing the building a person selected into an alternate
version. The instance is named from the building's provider identifier, so the same building is
always proposed under the same id, and it is anchored at the centre of the building's bounding box
in the admitted source frame.
"""

from __future__ import annotations

from collections.abc import Sequence

from exulanica.environment.repository import EnvironmentFeatureCatalog
from exulanica.world import (
    EnvironmentPlacement,
    EnvironmentSelection,
    ObjectOrigin,
    SourceAnchor,
    Transform,
)

__all__ = ["nyc_instance_id", "selected_feature_placement"]


def nyc_instance_id(provider_feature_id: str) -> str:
    """The authored instance id of an admitted NYC Open Data building, from its DOITT id."""
    return f"nyc-open-data:{provider_feature_id.replace(':', '-')}"


def selected_feature_placement(
    catalog: EnvironmentFeatureCatalog,
    *,
    instance_id: str,
    feature_id: str,
    render_batch_id: int,
    frame_name: str,
    bbox: Sequence[int],
    region_id: str,
    transform: tuple[int, int, int, int, int],
    origin_role: str,
) -> EnvironmentPlacement:
    """The placement of one feature of ``catalog``, anchored at its bounding box's centre.

    ``bbox`` holds the minimum corner then the maximum corner, in two or three dimensions, and the
    anchor is their midpoint in whole source units, rounded up. ``transform`` is the region-local
    placement in the order :class:`~exulanica.world.Transform` takes it.
    """
    dimensions = len(bbox) // 2
    return EnvironmentPlacement(
        instance_id=instance_id,
        admission_id=catalog.admission_id,
        render_asset_id=catalog.render_asset_id,
        publication_id=catalog.publication_id,
        selection=EnvironmentSelection("feature", feature_id, render_batch_id),
        source_anchor=SourceAnchor(
            frame_name,
            catalog.coordinate_scale,
            tuple((bbox[index] + bbox[index + dimensions] + 1) // 2 for index in range(dimensions)),
        ),
        region_id=region_id,
        transform=Transform(*transform),
        origin=ObjectOrigin("authored", origin_role),
    )
