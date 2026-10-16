"""A floating island as data: ``exulanica.sky-island/v1``.

What a world says about an island that floats: the outline of its top (``radius_mm``, how far it
reaches from its centre, and ``lobes``, how many overlapping lobes make it), how thick its rim slab
is (``rim_mm``), how far its underside hangs below the top (``depth_mm``), the underside's form
(``underside``: ``cone``, ``bowl`` or ``spires``), how many rock limbs hang from it (``fingers``),
its looks and whether it is walked (``look``, ``top_look``, ``walk``, as a volume's), and its
weathering (``erosion`` and ``strata``, a volume's sections exactly). The maker
(:mod:`exulanica.grammar.islands.maker`) turns it and a seed into an unchanged
``exulanica.volume/v1`` document.

**Closed and bounded.** Top keys are ``profile``, ``id``, ``radius_mm``, ``rim_mm`` and
``depth_mm``, and optionally ``lobes``, ``underside``, ``fingers``, ``look``, ``top_look``,
``walk``, ``erosion`` and ``strata``. Every value is held to the sky-island catalog; erosion and
strata are read by the volume reader itself against the volume catalog version the sky-island
catalog names, so they are bounded, defaulted and refused as a volume's are. The depth is at most
three times the radius (``island_too_deep``); the rim is at most the radius and at most half the
depth, so an underside hangs below it (``island_rim_too_thick``). Read against a sky-island
catalog that bounds ``top`` (version 2), an island may state ``top``, an unchanged
``exulanica.landform/v1`` document read by the land reader against the landform catalog its volume
catalog names, refused by its path under ``top``; the maker caps the island by that land instead
of a level. Under a catalog that bounds ``top_fill_mm`` (version 3), an island with a top states
how far its rock reaches above the land's highest point for a site's fills (written in with its
default, and refused without a top). A site, hangings and falls are later versions of the island,
as a top is under version 1 and its fill under version 2, and an island stating one is refused by
its path (``island_later_version``). Any other refusal is ``island_invalid``, by path.

**Defaults are written in.** The canonical document carries every value, with the catalogs'
defaults filled in at reading, so a later default never changes an island made before it. Its
identity is the SHA-256 of its canonical JSON, and it records the sky-island catalog version it was
read against.

Integers, keys and catalog words only; nothing here holds a person's words.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

from exulanica.canonical import canonical_json
from exulanica.grammar.documents import parse_json
from exulanica.grammar.islands.catalog import IslandCatalog, island_catalog
from exulanica.grammar.landform import (
    LandDocument,
    LandformRefused,
    landform_catalog,
    read_land_document,
)
from exulanica.grammar.records import KEY_PATTERN
from exulanica.grammar.volumes import (
    LAND_CATALOGS,
    ValueBound,
    VolumeRefused,
    read_volume_document,
    volume_catalog,
)
from exulanica.grammar.volumes import (
    PROFILE as VOLUME_PROFILE,
)

__all__ = ["LATER", "PROFILE", "IslandDocument", "IslandRefused", "read_island_document"]

PROFILE: Final = "exulanica.sky-island/v1"
_REQUIRED: Final = frozenset({"profile", "id", "radius_mm", "rim_mm", "depth_mm"})
_OPTIONAL: Final = frozenset(
    {"lobes", "underside", "fingers", "look", "top_look", "walk", "erosion", "strata"}
)
#: What later versions of the island state, each refused where its catalog does not bound it: the
#: top's own land (bounded from version 2), the rock left above it for a site's fills (from version
#: 3), a site laid out on it, vines and debris hanging from it, and water falling from its edge.
LATER: Final = ("top", "top_fill_mm", "site", "hangings", "falls")
#: The values the catalog bounds, in the order the document states them.
_VALUES: Final = (
    "radius_mm",
    "lobes",
    "rim_mm",
    "depth_mm",
    "underside",
    "fingers",
    "look",
    "top_look",
    "walk",
)


class IslandRefused(ValueError):
    """A sky-island document cannot be admitted or made. Says where and why."""

    def __init__(self, detail: str, *, path: str = "", code: str = "island_invalid") -> None:
        self.detail = detail
        self.path = path
        self.code = code
        super().__init__(f"{path}: {detail}" if path else detail)


@dataclass(frozen=True, slots=True)
class IslandDocument:
    id: str
    radius_mm: int
    lobes: int
    rim_mm: int
    depth_mm: int
    underside: str
    fingers: int
    look: str
    top_look: str
    walk: str
    erosion: Mapping[str, int | str]
    strata: Mapping[str, int | str]
    canonical_bytes: bytes
    sha256: str
    #: The version of the sky-island catalog it was read against.
    catalog_version: int
    #: The volume catalog version its erosion and strata were read against and its volume is.
    volume_catalog_version: int
    #: The land its top follows, or None where its top is level at its top height.
    top: LandDocument | None = None
    #: How far its rock reaches above its top land's highest point for a site's fills: 0 with no
    #: top land or under a catalog that does not bound it.
    top_fill_mm: int = 0

    def canonical(self) -> dict[str, Any]:
        return parse_json(self.canonical_bytes.decode(), PROFILE)


def _value(raw: Mapping[str, object], bound: ValueBound) -> int | str:
    name = bound.value
    if name not in raw:
        if bound.required:
            raise IslandRefused(f"{name} is required", path=name)
        return bound.words[bound.default] if bound.words else bound.default
    stated = raw[name]
    if bound.words:
        if stated not in bound.words:
            raise IslandRefused(
                f"{name} is one of {', '.join(bound.words)}, got {stated!r}", path=name
            )
        return str(stated)
    if type(stated) is not int:
        raise IslandRefused(f"{name} is one whole number, got {stated!r}", path=name)
    if not bound.minimum <= stated <= bound.maximum:
        raise IslandRefused(
            f"{name} states {stated}, outside {bound.minimum} to {bound.maximum}", path=name
        )
    return stated


def _weathering(
    raw: Mapping[str, object], island_id: str, version: int
) -> tuple[dict[str, int | str], dict[str, int | str]]:
    """The erosion and strata, read by the volume reader as a volume of one part states them."""
    probe: dict[str, object] = {
        "profile": VOLUME_PROFILE,
        "id": island_id,
        "parts": [{"id": "probe", "shape": "sphere", "radius_mm": 500}],
    }
    probe.update({name: raw[name] for name in ("erosion", "strata") if name in raw})
    try:
        read = read_volume_document(probe, volume_catalog(version))
    except VolumeRefused as refused:
        raise IslandRefused(refused.detail, path=refused.path) from refused
    return dict(read.erosion), dict(read.strata)


def _top(raw: object, catalog: IslandCatalog) -> LandDocument:
    """The top's land, read against the landform catalog the island's volume catalog names."""
    try:
        return read_land_document(
            raw, landform_catalog(LAND_CATALOGS[catalog.volume_catalog_version])
        )
    except LandformRefused as refused:
        raise IslandRefused(
            refused.detail, path=f"top.{refused.path}" if refused.path else "top"
        ) from refused


def read_island_document(raw: object, catalog: IslandCatalog | None = None) -> IslandDocument:
    """Admit a sky-island document against the catalog, or refuse it by path."""
    catalog = catalog or island_catalog()
    if not isinstance(raw, dict):
        raise IslandRefused(f"a sky-island document is an object, got {type(raw).__name__}")
    admitted = {name for name in LATER if name in catalog.values}
    later = [name for name in LATER if name in raw and name not in admitted]
    if later:
        raise IslandRefused(
            f"{', '.join(later)} belong to a later version of the sky island; version "
            f"{catalog.version} states its outline, underside, fingers, looks and weathering"
            + (f" and its {', '.join(sorted(admitted))}" if admitted else " only"),
            path=later[0],
            code="island_later_version",
        )
    optional = _OPTIONAL | admitted
    if not _REQUIRED <= set(raw) <= _REQUIRED | optional:
        raise IslandRefused(
            f"a sky-island document has {sorted(_REQUIRED)} and may have {sorted(optional)}, "
            f"got {sorted(raw)}"
        )
    if raw["profile"] != PROFILE:
        raise IslandRefused(f"profile is {PROFILE}, got {raw['profile']!r}", path="profile")
    island_id = raw["id"]
    if type(island_id) is not str or KEY_PATTERN.fullmatch(island_id) is None:
        raise IslandRefused(f"an id is a lowercase key, got {island_id!r}", path="id")
    values = {name: _value(raw, catalog.values[name]) for name in _VALUES}
    radius, rim, depth = (int(values[name]) for name in ("radius_mm", "rim_mm", "depth_mm"))
    if depth > 3 * radius:
        raise IslandRefused(
            f"an underside hangs at most three times the radius ({3 * radius} mm), got {depth}",
            path="depth_mm",
            code="island_too_deep",
        )
    if rim > radius or 2 * rim > depth:
        raise IslandRefused(
            f"a rim slab is at most the radius ({radius} mm) and half the depth "
            f"({depth // 2} mm) thick, got {rim}",
            path="rim_mm",
            code="island_rim_too_thick",
        )
    erosion, strata = _weathering(raw, island_id, catalog.volume_catalog_version)
    top = _top(raw["top"], catalog) if "top" in raw else None
    fill = 0
    if "top_fill_mm" in catalog.values:
        if top is None and "top_fill_mm" in raw:
            raise IslandRefused(
                "top_fill_mm is the rock left above a top land, and this island states no top",
                path="top_fill_mm",
            )
        if top is not None:
            fill = int(_value(raw, catalog.values["top_fill_mm"]))
    canonical: dict[str, Any] = {
        "profile": PROFILE,
        "id": island_id,
        **values,
        "erosion": erosion,
        "strata": strata,
    }
    if top is not None:
        canonical["top"] = top.canonical()
        if "top_fill_mm" in catalog.values:
            canonical["top_fill_mm"] = fill
    encoded = canonical_json(canonical)
    return IslandDocument(
        id=island_id,
        radius_mm=radius,
        lobes=int(values["lobes"]),
        rim_mm=rim,
        depth_mm=depth,
        underside=str(values["underside"]),
        fingers=int(values["fingers"]),
        look=str(values["look"]),
        top_look=str(values["top_look"]),
        walk=str(values["walk"]),
        erosion=erosion,
        strata=strata,
        canonical_bytes=encoded,
        sha256=hashlib.sha256(encoded).hexdigest(),
        catalog_version=catalog.version,
        volume_catalog_version=catalog.volume_catalog_version,
        top=top,
        top_fill_mm=fill,
    )
