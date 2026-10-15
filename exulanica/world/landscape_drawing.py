"""A site world on a landscape: its landscape checked against the site, read back from the receipt,
and drawn as ``exulanica.landscape-drawing/v1`` beside the site's own drawing.

A site laid out on a landscape (site-plan composer version 6) is laid out on the landscape's land
exactly as a site on land is (:mod:`exulanica.world.site_land`); the landscape adds the volumes
placed round it (:mod:`exulanica.grammar.landscape`). Here:

* :func:`place_landscape_on_site` holds a landscape to its site: its extent is the site's (the
  land's frame is the site's extent), and every placed volume stands off the site, its whole reach
  turned and moved to where it stands, so the site's people never meet rock their place does not
  know (``landscape_extent_not_site``, ``landscape_volume_on_site``). Volumes are scenery until
  the walking layer stands people on them.
* :func:`receipt_landscape` reads a receipt's landscape back under the landscape rules it names and
  holds it to its digest and to the receipt's land, or refuses by name
  (``generated_world_landscape_rules_changed``, ``generated_world_landscape_changed``).
* :func:`landscape_drawing` realizes its volumes under a seed drawn from the world and the
  landscape (:func:`landscape_seed`) and names the site drawing, the land and every volume chunk
  and top by digest; the documents those digests name come with it, to be served by digest.

A placed volume's chunks and tops are in its own frame: a reader places a point ``p`` of them at
``at_mm + R(yaw) p``, ``R`` the turn counterclockwise seen from above.

Pure: no connection and no store.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any, Final

from exulanica.canonical import canonical_json
from exulanica.grammar.landscape import (
    LandscapeDocument,
    LandscapeRefused,
    check_landscape_rules,
    compose_volumes,
    read_landscape_document,
    volume_bodies,
    volumes_section,
)
from exulanica.grammar.volumes import TURN_ONE, VolumeField, sin_cos
from exulanica.world.errors import InvalidStructuralData

__all__ = [
    "LANDSCAPE_DRAWING_PROFILE",
    "landscape_drawing",
    "landscape_drawing_sha256",
    "landscape_seed",
    "place_landscape_on_site",
    "read_site_landscape",
    "receipt_landscape",
]

LANDSCAPE_DRAWING_PROFILE: Final = "exulanica.landscape-drawing/v1"


def read_site_landscape(raw: object) -> LandscapeDocument:
    """A landscape stated for a site, its refusals named by their path in the request."""
    try:
        return read_landscape_document(raw)
    except LandscapeRefused as refused:
        path = f"landscape.{refused.path}" if refused.path else "landscape"
        raise LandscapeRefused(refused.detail, path=path, code=refused.code) from refused


def place_landscape_on_site(landscape: LandscapeDocument, width_mm: int, depth_mm: int) -> None:
    """Refuse a landscape whose extent is not the site's, or a volume that reaches onto the site."""
    if landscape.extent_mm != (width_mm, depth_mm):
        raise LandscapeRefused(
            f"a site's landscape has the site's extent, {width_mm} by {depth_mm} mm, not "
            f"{landscape.extent_mm[0]} by {landscape.extent_mm[1]} mm",
            path="landscape.extent_mm",
            code="landscape_extent_not_site",
        )
    for index, placement in enumerate(landscape.placements):
        (low_x, low_y, _), (high_x, high_y, _) = VolumeField(placement.volume, b"").extent
        sine, cosine = sin_cos(placement.yaw_mdeg)
        turned = [
            ((cosine * x - sine * y) // TURN_ONE, (sine * x + cosine * y) // TURN_ONE)
            for x in (low_x, high_x)
            for y in (low_y, high_y)
        ]
        east = [x + placement.at_mm[0] for x, _ in turned]
        north = [y + placement.at_mm[1] for _, y in turned]
        if min(east) < width_mm and max(east) > 0 and min(north) < depth_mm and max(north) > 0:
            raise LandscapeRefused(
                f"{placement.id} reaches from ({min(east)}, {min(north)}) to ({max(east)}, "
                f"{max(north)}), onto the site 0 to {width_mm} east and 0 to {depth_mm} north; "
                "volumes stand off a site",
                path=f"landscape.volumes[{index}]",
                code="landscape_volume_on_site",
            )


def receipt_landscape(receipt: Mapping[str, Any]) -> LandscapeDocument:
    """The landscape a version 6 receipt states, under the landscape rules it names, held to its
    digest and to the receipt's land; refused by name otherwise."""
    try:
        check_landscape_rules(receipt.get("landscape_rules"))
    except LandscapeRefused as exc:
        raise InvalidStructuralData(
            f"generated_world_landscape_rules_changed: {exc.detail}"
        ) from exc
    try:
        landscape = read_landscape_document(receipt.get("landscape"))
    except LandscapeRefused as exc:
        raise InvalidStructuralData(
            f"generated_world_landscape_changed: its landscape no longer reads: {exc.detail}"
        ) from exc
    if landscape.sha256 != receipt.get(
        "landscape_sha256"
    ) or landscape.land.canonical() != receipt.get("land"):
        raise InvalidStructuralData(
            "generated_world_landscape_changed: its landscape is not the one its receipt names"
        )
    return landscape


def landscape_seed(world_id: str, landscape_sha256: str) -> str:
    """The seed a world's landscape is realized with: its world's identity and its landscape's
    digest, both in its receipt, as the land's seed is drawn (``site_land.land_seed``)."""
    return hashlib.sha256(f"exulanica.landscape:{world_id}:{landscape_sha256}".encode()).hexdigest()


def landscape_drawing(
    world_id: str,
    receipt: Mapping[str, Any],
    receipt_sha256: str,
    site_drawing_sha256: str,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """The landscape's drawing for a version 6 receipt, and every chunk and top it names by its
    digest."""
    landscape = receipt_landscape(receipt)
    placed = compose_volumes(landscape, landscape_seed(world_id, landscape.sha256))
    drawing = {
        "profile": LANDSCAPE_DRAWING_PROFILE,
        "world_id": world_id,
        "receipt_sha256": receipt_sha256,
        "site_drawing_sha256": site_drawing_sha256,
        "land_sha256": receipt["land_sha256"],
        "landscape_sha256": landscape.sha256,
        "landscape_rules_version": receipt["landscape_rules"]["version"],
        **volumes_section(placed),
    }
    return drawing, volume_bodies(placed)


def landscape_drawing_sha256(drawing: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(drawing)).hexdigest()
