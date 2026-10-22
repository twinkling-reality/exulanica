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
* :func:`receipt_landscape` reads a receipt's landscape back under the landscape rules it names (its
  volumes against the catalogs of the volume rules those name, and realized by them) and holds it
  to its digest and to the receipt's land, or refuses by name
  (``generated_world_landscape_rules_changed``, ``generated_world_landscape_changed``). A site on
  the landscape's land (version 6) states no ``site`` and its land is the landscape's; a site on a
  placed volume's top (version 7, :mod:`exulanica.world.site_on_top`) states one, and its land is
  that volume's top land.
* :func:`landscape_drawing` realizes its volumes under a seed drawn from the world and the
  landscape (:func:`landscape_seed`) and names the site drawing, the land and every volume chunk
  and top by digest, and each placed volume's look and top look, so a page dresses its faces and
  its upward faces as the volume says; the documents those digests name come with it, to be
  served by digest. A world on a placed volume's top (version 7) is drawn as
  ``exulanica.landscape-drawing/v2``: that volume capped by the site's graded top (the
  ``exulanica.site-top/v1`` document its site drawing keeps, named by ``top_sha256``), where the
  site stands in the landscape (``site_frame``: its south-west corner and its turn, so a page whose
  frame is the site's places the landscape round it), and ``ground``: the landscape's own land,
  ungraded, as land chunks, a backdrop and its water in the landscape's frame, the ground or sea
  the volume stands over.

A placed volume's chunks and tops are in its own frame: a reader places a point ``p`` of them at
``at_mm + R(yaw) p``, ``R`` the turn counterclockwise seen from above.

Pure: no connection and no store.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any, Final

from exulanica.canonical import canonical_json
from exulanica.grammar.landform import (
    CHUNK_MM,
    Backdrop,
    LandChunk,
    WaterBody,
    WorldFrame,
    realize_backdrop,
    realize_near,
    water_bodies,
)
from exulanica.grammar.landscape import (
    SERVED_LANDSCAPE_RULES,
    LandscapeDocument,
    LandscapeRefused,
    LandscapeSite,
    compose_volumes,
    landscape_catalog,
    read_landscape_document,
    volume_bodies,
    volumes_section,
)
from exulanica.grammar.landscape.rules import served_landscape_rules
from exulanica.grammar.volumes import TURN_ONE, TopHeights, VolumeField, VolumeRefused, sin_cos
from exulanica.world.errors import InvalidStructuralData

__all__ = [
    "LANDSCAPE_DRAWING_PROFILE",
    "TOP_LANDSCAPE_DRAWING_PROFILE",
    "landscape_drawing",
    "landscape_drawing_sha256",
    "landscape_seed",
    "place_landscape_on_site",
    "read_site_landscape",
    "receipt_landscape",
]

LANDSCAPE_DRAWING_PROFILE: Final = "exulanica.landscape-drawing/v1"
#: The drawing of a landscape whose site stands on one of its volumes' tops.
TOP_LANDSCAPE_DRAWING_PROFILE: Final = "exulanica.landscape-drawing/v2"

#: The ground the last drawing realized, by its land's digest and frame (whose seed is the world's):
#: a world's landscape drawn again for a part edit stands over the same ground.
_Ground = tuple[tuple[LandChunk, ...], Backdrop, tuple[WaterBody, ...]]
_grounds: dict[tuple[str, WorldFrame], _Ground] = {}


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
        try:
            field = VolumeField(placement.volume, b"")
        except VolumeRefused as refused:
            # A top land the land realizer refuses is refused here, the first field a site's
            # landscape makes, by its path in the request.
            where = f"landscape.volumes[{index}].volume"
            raise LandscapeRefused(
                refused.detail,
                path=f"{where}.{refused.path}" if refused.path else where,
                code=refused.code,
            ) from refused
        (low_x, low_y, _), (high_x, high_y, _) = field.extent
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
    """The landscape a version 6 or 7 receipt states, under the landscape rules it names, held to
    its digest and to the receipt's land (the landscape's for version 6, the top land of the
    volume its site stands on for version 7); refused by name otherwise."""
    try:
        version = served_landscape_rules(receipt.get("landscape_rules"))
    except LandscapeRefused as exc:
        raise InvalidStructuralData(
            f"generated_world_landscape_rules_changed: {exc.detail}"
        ) from exc
    catalog_version, volume_rules = SERVED_LANDSCAPE_RULES[version]
    try:
        landscape = read_landscape_document(
            receipt.get("landscape"), landscape_catalog(catalog_version), volume_rules=volume_rules
        )
    except LandscapeRefused as exc:
        raise InvalidStructuralData(
            f"generated_world_landscape_changed: its landscape no longer reads: {exc.detail}"
        ) from exc
    if landscape.sha256 != receipt.get("landscape_sha256") or _land_of(
        landscape, receipt
    ) != receipt.get("land"):
        raise InvalidStructuralData(
            "generated_world_landscape_changed: its landscape is not the one its receipt names"
        )
    return landscape


def _land_of(landscape: LandscapeDocument, receipt: Mapping[str, Any]) -> object:
    """The land a receipt's site stands on, as its landscape states it: the landscape's own land,
    or for a site on a volume's top that volume's top land; None where the landscape's site and the
    receipt's composer disagree."""
    from exulanica.world.composers.site_plan import TOP_COMPOSER_VERSION

    on_top = receipt.get("composer", {}).get("version") == TOP_COMPOSER_VERSION
    if (landscape.site is not None) != on_top:
        return None
    if landscape.site is None:
        return landscape.land.canonical()
    stood_on = next(p for p in landscape.placements if p.id == landscape.site.on)
    top = stood_on.volume.top_land
    return None if top is None else top.land.canonical()


def landscape_seed(world_id: str, landscape_sha256: str) -> str:
    """The seed a world's landscape is realized with: its world's identity and its landscape's
    digest, both in its receipt, as the land's seed is drawn (``site_land.land_seed``)."""
    return hashlib.sha256(f"exulanica.landscape:{world_id}:{landscape_sha256}".encode()).hexdigest()


def landscape_drawing(
    world_id: str,
    receipt: Mapping[str, Any],
    receipt_sha256: str,
    site_drawing_sha256: str,
    top: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """The landscape's drawing for a version 6 receipt, or for a version 7 receipt with ``top``,
    the graded top its site drawing keeps (its digest and its bytes), and every document it names
    by its digest."""
    landscape = receipt_landscape(receipt)
    seed = landscape_seed(world_id, landscape.sha256)
    site = landscape.site
    given = None
    if site is not None:
        if top is None:
            raise InvalidStructuralData(
                "generated_world_unreadable: the site's graded top is not kept with its drawing"
            )
        given = _given_top(top)
    placed = compose_volumes(landscape, seed, None if site is None else {site.on: given})
    section = volumes_section(placed)
    for entry, placement in zip(section["volumes"], landscape.placements, strict=True):
        entry["look"] = placement.volume.look
        entry["top_look"] = placement.volume.top_look
    drawing = {
        "profile": LANDSCAPE_DRAWING_PROFILE,
        "world_id": world_id,
        "receipt_sha256": receipt_sha256,
        "site_drawing_sha256": site_drawing_sha256,
        "land_sha256": receipt["land_sha256"],
        "landscape_sha256": landscape.sha256,
        "landscape_rules_version": receipt["landscape_rules"]["version"],
        **section,
    }
    bodies = volume_bodies(placed)
    if site is None or top is None:
        return drawing, bodies
    ground, ground_bodies = _ground(world_id, landscape)
    drawing["profile"] = TOP_LANDSCAPE_DRAWING_PROFILE
    drawing["top_sha256"] = top["sha256"]
    drawing["site_frame"] = _site_frame(landscape, site)
    drawing["ground"] = ground
    return drawing, {**bodies, **ground_bodies}


def _given_top(top: Mapping[str, Any]) -> TopHeights:
    """The heights a site's graded top caps its volume by, read from the ``exulanica.site-top/v1``
    document its site drawing keeps and held to the digest kept with it: the whole square's
    lattice, as the grader grades it."""
    body = top["body"]
    document = json.loads(body)
    if hashlib.sha256(canonical_json(document)).hexdigest() != top["sha256"]:
        raise InvalidStructuralData(
            "generated_world_unreadable: the site's graded top is not the one its drawing names"
        )
    count = int(document["columns"])
    if int(document["rows"]) != count:
        raise InvalidStructuralData(
            "generated_world_unreadable: the site's graded top is not its volume's square"
        )
    return TopHeights(count=count, heights=tuple(int(h) for h in document["height_mm"]))


def _site_frame(landscape: LandscapeDocument, site: LandscapeSite) -> dict[str, Any]:
    """Where the site stands in the landscape's frame: the placement it stands on, its south-west
    corner (the volume's ``at_mm + R(yaw) (site corner)``) and the placement's turn, the site's own,
    so a page whose frame is the site's places the landscape at the inverse."""
    placement = next(p for p in landscape.placements if p.id == site.on)
    sine, cosine = sin_cos(placement.yaw_mdeg)
    east, north = site.at_mm
    x, y, z = placement.at_mm
    return {
        "placement": placement.id,
        "at_mm": [
            x + (cosine * east - sine * north) // TURN_ONE,
            y + (sine * east + cosine * north) // TURN_ONE,
            z,
        ],
        "yaw_mdeg": placement.yaw_mdeg,
    }


def _ground(
    world_id: str, landscape: LandscapeDocument
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """The landscape's own land under a volume a site stands on, ungraded, in the landscape's frame
    (its extent, under the seed a world's land is realized under,
    :func:`~exulanica.world.site_land.land_seed`): its near land as chunks, its backdrop and its
    water, and the documents by digest."""
    from exulanica.world.site_land import land_seed

    land = landscape.land
    width, depth = landscape.extent_mm
    frame = WorldFrame(width_mm=width, depth_mm=depth, seed=land_seed(world_id, land.sha256))
    key = (land.sha256, frame)
    held = _grounds.get(key)
    if held is None:
        held = (
            realize_near(land, frame).chunks(),
            realize_backdrop(land, frame),
            water_bodies(land, frame),
        )
        _grounds.clear()
        _grounds[key] = held
    chunks, backdrop, water = held
    section = {
        "land_sha256": land.sha256,
        "chunk_mm": CHUNK_MM,
        "chunks": [
            {"chunk": [chunk.chunk_x, chunk.chunk_y], "sha256": chunk.sha256} for chunk in chunks
        ],
        "backdrop_sha256": backdrop.sha256,
        "water": [body.document() for body in water],
    }
    bodies = {chunk.sha256: chunk.document() for chunk in chunks}
    bodies[backdrop.sha256] = backdrop.document()
    return section, bodies


def landscape_drawing_sha256(drawing: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(drawing)).hexdigest()
