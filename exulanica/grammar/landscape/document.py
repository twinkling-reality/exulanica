"""A world's landscape as data: ``exulanica.landscape/v1``.

What a world says about everything it stands on: its extent, its land (an unchanged
``exulanica.landform/v1`` document) and the volumes it places on and over that land (each an
unchanged ``exulanica.volume/v1`` document, placed by its own origin in the world and turned about
the vertical). Later versions add sky islands, spans, landmark flora and far layers beside them;
the land and volume documents inside never change for it.

**Closed and bounded.** Top keys are ``profile``, ``extent_mm`` and ``land``, and optionally
``volumes`` and ``finest_cell_mm``. A placement states ``id``, ``volume`` and ``at_mm``, and
optionally ``yaw_mdeg`` and ``volume_sha256`` (which must be its volume's digest). Values are held
to the landscape catalog; the land and each volume are read by their own readers, and a refusal of
either is passed on with its path inside the landscape (``land.features[2].height_mm``,
``volumes[1].volume.parts[0].radius_mm``) and its own code. A placement's origin lies on the land
near the world: the extent and the ring of land chunks round it that the land realizer realizes
(:func:`~exulanica.grammar.landform.near_domain`), so a sea stack may stand in the bay beyond a
site's edge (``landscape_outside_near_land``); ids are unique; the finest cell is one the volume
realizer meshes at.

**Defaults are written in**, and every piece is carried whole with its digest, so one volume placed
twice is the same document twice and a world rebuilds from its receipt alone. Its identity is the
SHA-256 of its canonical JSON. Its volumes are read against the volume catalogs of one version of
the volume rules (the newest unless a world's landscape rules name another), which the document
records so its volumes are realized by the same rules.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

from exulanica.canonical import canonical_json
from exulanica.grammar.documents import parse_json
from exulanica.grammar.landform import (
    LandDocument,
    LandformRefused,
    WorldFrame,
    near_domain,
    read_land_document,
)
from exulanica.grammar.landscape.catalog import LandscapeCatalog, landscape_catalog
from exulanica.grammar.records import KEY_PATTERN
from exulanica.grammar.volumes import (
    LEVELS,
    SERVED_VOLUME_RULES,
    VOLUME_RULES_VERSION,
    ValueBound,
    VolumeCatalog,
    VolumeDocument,
    VolumeRefused,
    read_volume_document,
    volume_catalog,
)

__all__ = [
    "PROFILE",
    "LandscapeDocument",
    "LandscapeRefused",
    "Placement",
    "read_landscape_document",
]

PROFILE: Final = "exulanica.landscape/v1"
_REQUIRED: Final = frozenset({"profile", "extent_mm", "land"})
_OPTIONAL: Final = frozenset({"volumes", "finest_cell_mm"})
_PLACEMENT_REQUIRED: Final = frozenset({"id", "volume", "at_mm"})
_PLACEMENT_OPTIONAL: Final = frozenset({"yaw_mdeg", "volume_sha256"})


class LandscapeRefused(ValueError):
    """A landscape document or its realization cannot be admitted. Says where and why."""

    def __init__(self, detail: str, *, path: str = "", code: str = "landscape_invalid") -> None:
        self.detail = detail
        self.path = path
        self.code = code
        super().__init__(f"{path}: {detail}" if path else detail)


@dataclass(frozen=True, slots=True)
class Placement:
    id: str
    volume: VolumeDocument
    at_mm: tuple[int, int, int]
    yaw_mdeg: int


@dataclass(frozen=True, slots=True)
class LandscapeDocument:
    extent_mm: tuple[int, int]
    land: LandDocument
    finest_cell_mm: int
    placements: tuple[Placement, ...]
    canonical_bytes: bytes
    sha256: str
    #: The volume rules its volumes were read against and are realized by.
    volume_rules: int

    def canonical(self) -> dict[str, Any]:
        return parse_json(self.canonical_bytes.decode(), PROFILE)

    @property
    def levels(self) -> tuple[int, ...]:
        """The cells its volumes are meshed at, coarsest first, down to the finest it states."""
        return tuple(cell for cell in sorted(LEVELS, reverse=True) if cell >= self.finest_cell_mm)


def _numbers(raw: object, bound: ValueBound, path: str) -> tuple[int, ...]:
    listed = [raw] if bound.count == 1 else raw
    if not isinstance(listed, list) or len(listed) != bound.count:
        raise LandscapeRefused(
            f"{bound.value} is {bound.count} whole numbers, got {raw!r}", path=path
        )
    for index, value in enumerate(listed):
        where = path if bound.count == 1 else f"{path}[{index}]"
        if type(value) is not int:
            raise LandscapeRefused(f"a whole number is stated here, got {value!r}", path=where)
        if not bound.minimum <= value <= bound.maximum:
            raise LandscapeRefused(
                f"{bound.value} states {value}, outside {bound.minimum} to {bound.maximum}",
                path=where,
            )
    return tuple(listed)


def _stated(raw: Mapping[str, object], name: str, bound: ValueBound, path: str) -> tuple[int, ...]:
    if name in raw:
        return _numbers(raw[name], bound, path)
    if bound.required:
        raise LandscapeRefused(f"{name} is required", path=path)
    return (bound.default,) * bound.count


def _placement(
    raw: object,
    index: int,
    bounds: Mapping[str, ValueBound],
    near: tuple[int, int, int, int],
    volumes: VolumeCatalog,
) -> Placement:
    path = f"volumes[{index}]"
    if not isinstance(raw, dict) or not (
        _PLACEMENT_REQUIRED <= set(raw) <= _PLACEMENT_REQUIRED | _PLACEMENT_OPTIONAL
    ):
        keys = sorted(raw) if isinstance(raw, dict) else type(raw).__name__
        raise LandscapeRefused(
            f"a placement has {sorted(_PLACEMENT_REQUIRED)} and may have "
            f"{sorted(_PLACEMENT_OPTIONAL)}, got {keys}",
            path=path,
        )
    placement_id = raw["id"]
    if type(placement_id) is not str or KEY_PATTERN.fullmatch(placement_id) is None:
        raise LandscapeRefused(f"an id is a lowercase key, got {placement_id!r}", path=f"{path}.id")
    try:
        volume = read_volume_document(raw["volume"], volumes)
    except VolumeRefused as refused:
        inner = f"{path}.volume.{refused.path}" if refused.path else f"{path}.volume"
        raise LandscapeRefused(refused.detail, path=inner, code=refused.code) from refused
    if "volume_sha256" in raw and raw["volume_sha256"] != volume.sha256:
        raise LandscapeRefused(
            f"{placement_id}: volume_sha256 is not its volume's digest {volume.sha256}",
            path=f"{path}.volume_sha256",
            code="landscape_digest_mismatch",
        )
    x, y, z = _stated(raw, "at_mm", bounds["at_mm"], f"{path}.at_mm")
    if not (near[0] <= x <= near[2] and near[1] <= y <= near[3]):
        raise LandscapeRefused(
            f"{placement_id} stands at ({x}, {y}), off the land near the world, {near[0]} to "
            f"{near[2]} east and {near[1]} to {near[3]} north",
            path=f"{path}.at_mm",
            code="landscape_outside_near_land",
        )
    (yaw,) = _stated(raw, "yaw_mdeg", bounds["yaw_mdeg"], f"{path}.yaw_mdeg")
    return Placement(id=placement_id, volume=volume, at_mm=(x, y, z), yaw_mdeg=yaw)


def read_landscape_document(
    raw: object, catalog: LandscapeCatalog | None = None, *, volume_rules: int | None = None
) -> LandscapeDocument:
    """Admit a landscape document against the catalogs, its volumes against those of
    ``volume_rules`` (the newest unless named), or refuse it by path."""
    catalog = catalog or landscape_catalog()
    rules = VOLUME_RULES_VERSION if volume_rules is None else volume_rules
    volumes = volume_catalog(SERVED_VOLUME_RULES[rules])
    if not isinstance(raw, dict) or not _REQUIRED <= set(raw) <= _REQUIRED | _OPTIONAL:
        keys = sorted(raw) if isinstance(raw, dict) else type(raw).__name__
        raise LandscapeRefused(
            f"a landscape document has {sorted(_REQUIRED)} and may have {sorted(_OPTIONAL)}, "
            f"got {keys}"
        )
    if raw["profile"] != PROFILE:
        raise LandscapeRefused(f"profile is {PROFILE}, got {raw['profile']!r}", path="profile")
    own = catalog.values_of("landscape")
    width, depth = _stated(raw, "extent_mm", own["extent_mm"], "extent_mm")
    (finest,) = _stated(raw, "finest_cell_mm", own["finest_cell_mm"], "finest_cell_mm")
    if finest not in LEVELS:
        raise LandscapeRefused(
            f"finest_cell_mm is one of the realizer's cells {LEVELS}, got {finest}",
            path="finest_cell_mm",
        )
    try:
        land = read_land_document(raw["land"])
    except LandformRefused as refused:
        inner = f"land.{refused.path}" if refused.path else "land"
        raise LandscapeRefused(refused.detail, path=inner, code=refused.code) from refused
    listed = raw.get("volumes", [])
    if not isinstance(listed, list):
        raise LandscapeRefused("volumes is a list", path="volumes")
    if len(listed) > own["volumes"].maximum:
        raise LandscapeRefused(
            f"a landscape places at most {own['volumes'].maximum} volumes, got {len(listed)}",
            path="volumes",
        )
    bounds = catalog.values_of("placement")
    near = near_domain(WorldFrame(width_mm=width, depth_mm=depth, seed=""))
    placements: list[Placement] = []
    for index, item in enumerate(listed):
        placement = _placement(item, index, bounds, near, volumes)
        if any(placement.id == other.id for other in placements):
            raise LandscapeRefused(f"id {placement.id} is used twice", path=f"volumes[{index}].id")
        placements.append(placement)
    canonical = {
        "profile": PROFILE,
        "extent_mm": [width, depth],
        "land": land.canonical(),
        "finest_cell_mm": finest,
        "volumes": [
            {
                "id": placement.id,
                "volume": placement.volume.canonical(),
                "volume_sha256": placement.volume.sha256,
                "at_mm": list(placement.at_mm),
                "yaw_mdeg": placement.yaw_mdeg,
            }
            for placement in placements
        ],
    }
    encoded = canonical_json(canonical)
    return LandscapeDocument(
        extent_mm=(width, depth),
        land=land,
        finest_cell_mm=finest,
        placements=tuple(placements),
        canonical_bytes=encoded,
        sha256=hashlib.sha256(encoded).hexdigest(),
        volume_rules=rules,
    )
