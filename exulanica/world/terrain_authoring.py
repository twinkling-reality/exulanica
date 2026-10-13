"""Closed terrain source admission, with exact entry contact and explicit capabilities."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from exulanica.canonical import canonical_json, round_half_down
from exulanica.world.heightfield_contact import HeightfieldContact, at, read_heightfield_contact
from exulanica.world.heightfield_geometry import (
    FRAME,
    HeightfieldInvalid,
    digest,
    keys,
    position,
    read_heightfield_geometry,
    require,
)

PROFILE = "exulanica.terrain-authoring/v1"
DRESSED_PROFILE = "exulanica.terrain-authoring/v2"
TERRAIN_COMPOSER_VERSIONS = (3, 4)
CAPABILITIES = {
    "person_navigation": True,
    "passive_flat_patch": True,
    "society_projection": "unavailable",
}


class TerrainAuthoringRefused(ValueError):
    """The terrain source cannot safely admit a stationary visitor."""

    code = "terrain_authoring_invalid"

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)


@dataclass(frozen=True)
class TerrainAuthoring:
    canonical_bytes: bytes
    sha256: str
    contact: HeightfieldContact
    arrival_bytes: bytes

    def document(self) -> dict:
        return json.loads(self.canonical_bytes)

    @property
    def composer_version(self) -> int:
        return 4 if self.document()["profile"] == DRESSED_PROFILE else 3

    def arrival(self) -> dict:
        return json.loads(self.arrival_bytes)


def read_terrain_authoring(raw: object) -> TerrainAuthoring:
    """Admit declared source data; later placements still need current obstruction authority."""
    try:
        dressed = isinstance(raw, dict) and raw.get("profile") == DRESSED_PROFILE
        doc = keys(
            raw,
            "profile region_id geometry geometry_sha256 contact contact_sha256 "
            "bounds_mm entry capabilities" + (" dressing dressing_sha256" if dressed else ""),
        )
        require(
            doc["profile"] in (PROFILE, DRESSED_PROFILE) and doc["region_id"] == "region:generated",
            "unknown terrain authoring profile or region",
        )
        if dressed:
            from exulanica.world.terrain_dressing import read_terrain_dressing

            read_terrain_dressing(doc["dressing"], digest(doc["dressing_sha256"]))
        caps = keys(doc["capabilities"], "person_navigation passive_flat_patch society_projection")
        require(
            caps["person_navigation"] is True
            and caps["passive_flat_patch"] is True
            and caps["society_projection"] == "unavailable",
            "terrain capability declaration differs",
        )
        geometry = read_heightfield_geometry(doc["geometry"], digest(doc["geometry_sha256"]))
        contact = read_heightfield_contact(doc["contact"], geometry, digest(doc["contact_sha256"]))
        bounds = keys(doc["bounds_mm"], "east south")
        east, south = position(bounds["east"]), position(bounds["south"])
        require(
            east == (0, geometry.east_mm[-1])
            and south == (geometry.south_mm[0], 0)
            and geometry.east_mm[0] == 0
            and geometry.south_mm[-1] == 0,
            "terrain bounds must match east 0..width and south -depth..0",
        )
        entry = keys(doc["entry"], "position_mm facing_mm")
        point, facing = position(entry["position_mm"]), position(entry["facing_mm"])
        require(facing != (0, 0), "entry facing must be nonzero")
        result = at(contact, point)
        require(result["status"] == "clear", f"terrain entry refused: {result['reason']}")
        exact = result["contact"]
        fraction = exact["height_mm"]
        up = round_half_down(int(fraction["numerator"]), int(fraction["denominator"]))
        arrival = {
            "position_mm": [point[0], up, point[1]],
            "facing_mm": list(facing),
            "contact": exact,
        }
        encoded = canonical_json(doc)
        return TerrainAuthoring(
            encoded, hashlib.sha256(encoded).hexdigest(), contact, canonical_json(arrival)
        )
    except (HeightfieldInvalid, TypeError, ValueError) as exc:
        raise TerrainAuthoringRefused(str(exc)) from exc


def terrain_drawing(source: TerrainAuthoring, world_id: str, receipt_sha256: str) -> dict:
    """Publish the admitted terrain without synthesizing flat site records."""
    doc = source.document()
    drawing = {
        "profile": f"exulanica.site-drawing/v{source.composer_version}",
        "world_id": world_id,
        "region_id": doc["region_id"],
        "receipt_sha256": receipt_sha256,
        "composer": {"key": "site-plan", "version": source.composer_version},
        "frame": FRAME,
        "bounds_mm": doc["bounds_mm"],
        "terrain": {
            key: doc[key] for key in ("geometry", "geometry_sha256", "contact", "contact_sha256")
        },
        "arrival": source.arrival(),
        "capabilities": doc["capabilities"],
    }

    if source.composer_version == 4:
        drawing["terrain"].update({key: doc[key] for key in ("dressing", "dressing_sha256")})
    return drawing
