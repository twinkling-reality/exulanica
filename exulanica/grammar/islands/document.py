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
depth, so an underside hangs below it (``island_rim_too_thick``). Top land, a site, hangings and
falls are later versions of the island, and an island stating one is refused by its path
(``island_later_version``). Any other refusal is ``island_invalid``, by path.

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
from exulanica.grammar.records import KEY_PATTERN
from exulanica.grammar.volumes import (
    PROFILE as VOLUME_PROFILE,
)
from exulanica.grammar.volumes import (
    ValueBound,
    VolumeRefused,
    read_volume_document,
    volume_catalog,
)

__all__ = ["LATER", "PROFILE", "IslandDocument", "IslandRefused", "read_island_document"]

PROFILE: Final = "exulanica.sky-island/v1"
_REQUIRED: Final = frozenset({"profile", "id", "radius_mm", "rim_mm", "depth_mm"})
_OPTIONAL: Final = frozenset(
    {"lobes", "underside", "fingers", "look", "top_look", "walk", "erosion", "strata"}
)
#: What later versions of the island state and this one refuses: the top's own land, a site laid
#: out on it, vines and debris hanging from it, and water falling from its edge.
LATER: Final = ("top", "site", "hangings", "falls")
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


def read_island_document(raw: object, catalog: IslandCatalog | None = None) -> IslandDocument:
    """Admit a sky-island document against the catalog, or refuse it by path."""
    catalog = catalog or island_catalog()
    if not isinstance(raw, dict):
        raise IslandRefused(f"a sky-island document is an object, got {type(raw).__name__}")
    later = [name for name in LATER if name in raw]
    if later:
        raise IslandRefused(
            f"{', '.join(later)} belong to a later version of the sky island; version 1 states "
            "its outline, underside, fingers, looks and weathering only",
            path=later[0],
            code="island_later_version",
        )
    if not _REQUIRED <= set(raw) <= _REQUIRED | _OPTIONAL:
        raise IslandRefused(
            f"a sky-island document has {sorted(_REQUIRED)} and may have {sorted(_OPTIONAL)}, "
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
    canonical = {
        "profile": PROFILE,
        "id": island_id,
        **values,
        "erosion": erosion,
        "strata": strata,
    }
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
    )
