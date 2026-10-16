"""A sea stack as data: ``exulanica.sea-stack/v1``.

What a world says about one sea stack, in whole millimetres and millidegrees, in its own frame
(x east, y north, z up), whose level 0 is the sea's surface where it is placed: how high its level
top stands, how far its trunk reaches down to the sea floor, its trunk's radius at its foot and at
its top, how its trunk leans, how many shoulders swell from its flanks, the passage through it if
any, and its weathering and bedding. The maker (:mod:`exulanica.grammar.stacks.maker`) turns it
into an unchanged ``exulanica.volume/v1`` document.

**Closed and bounded.** Top keys are ``profile``, ``id``, ``height_mm``, ``foot_mm``,
``base_radius_mm`` and ``top_radius_mm``, and optionally ``shoulders``, ``look``, ``top_look``,
``walk``, ``lean`` (``tilt_mdeg``, ``toward_mdeg``), ``arch`` (``none``, or ``width_mm``,
``rise_mm``, ``floor_mm``, ``bearing_mdeg``), ``erosion`` and ``strata``. Every value is held to the
sea stack catalog; the erosion and strata are a volume's own sections, held to the volume catalog
the stack's volume is read against, a bed at least 1 m as a volume's is. A refusal names the path
of what it refused and a code: ``stack_invalid`` for a shape or a bound, and by rule:

* ``stack_flank_faces_up``: the trunk's flank away from its lean faces up by more than 1 in 4
  (about 14 degrees), its taper and its lean together, so its rock under the water would face up.
* ``stack_arch_too_wide``: a passage wider than the trunk's radius where it passes (each pier keeps
  at least a quarter of the trunk's width), or a round head taller than the passage's floor depth
  and rise.
* ``stack_arch_too_high``: less rock over the passage's crown than the passage is wide.
* ``stack_arch_below_foot``: a passage floor less than the weathering and 3 m above the foot, so
  the passage would cut the stack from the sea floor.

**Defaults are written in.** The canonical document carries every value, with the catalog's
defaults filled in at reading, so a later default never changes a stack made before it. Its
identity is the SHA-256 of its canonical JSON. Integers, keys and catalog words only; nothing here
holds a person's words.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

from exulanica.canonical import canonical_json
from exulanica.grammar.documents import parse_json
from exulanica.grammar.records import KEY_PATTERN
from exulanica.grammar.stacks.catalog import (
    VOLUME_CATALOG_VERSION,
    SeaStackCatalog,
    sea_stack_catalog,
)
from exulanica.grammar.volumes import ValueBound, sin_cos, volume_catalog

__all__ = [
    "FLANK_PERMILLE",
    "PROFILE",
    "SECTIONS",
    "SILL_MM",
    "SeaStackArch",
    "SeaStackDocument",
    "SeaStackRefused",
    "read_sea_stack_document",
    "trunk_radius",
]

PROFILE: Final = "exulanica.sea-stack/v1"
#: A stack's sections that are a volume's own, bounded by the volume catalog.
SECTIONS: Final = ("erosion", "strata")
_NESTED: Final = ("lean", "arch")
#: The steepest its flank away from its lean may face up, per thousand: 1 in 4, about 14 degrees,
#: below the 17 degrees past which shallow rock that faces up reads as a bright block in water.
FLANK_PERMILLE: Final = 250
#: The least rock under a passage's floor above the foot, besides the weathering.
SILL_MM: Final = 3_000


class SeaStackRefused(ValueError):
    """A sea stack document cannot be admitted. Says where and why."""

    def __init__(self, detail: str, *, path: str = "", code: str = "stack_invalid") -> None:
        self.detail = detail
        self.path = path
        self.code = code
        super().__init__(f"{path}: {detail}" if path else detail)


@dataclass(frozen=True, slots=True)
class SeaStackArch:
    width_mm: int
    rise_mm: int
    floor_mm: int
    bearing_mdeg: int


@dataclass(frozen=True, slots=True)
class SeaStackDocument:
    id: str
    height_mm: int
    foot_mm: int
    base_radius_mm: int
    top_radius_mm: int
    shoulders: int
    look: str
    top_look: str
    walk: str
    tilt_mdeg: int
    toward_mdeg: int
    #: The passage through it, or None.
    arch: SeaStackArch | None
    erosion: Mapping[str, int | str]
    strata: Mapping[str, int | str]
    canonical_bytes: bytes
    sha256: str

    def canonical(self) -> dict[str, Any]:
        return parse_json(self.canonical_bytes.decode(), PROFILE)

    @property
    def weathering_mm(self) -> int:
        """The most its erosion and strata move a face."""
        return _whole(self.erosion["amplitude_mm"]) + _whole(self.strata["amplitude_mm"])


def _whole(value: int | str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise SeaStackRefused(f"one whole number is expected here, got {value!r}")
    return value


def _value(raw: object, bound: ValueBound, path: str) -> int | str:
    if bound.words:
        if raw not in bound.words:
            raise SeaStackRefused(
                f"{bound.value} is one of {', '.join(bound.words)}, got {raw!r}", path=path
            )
        return str(raw)
    if type(raw) is not int:
        raise SeaStackRefused(f"{bound.value} is a whole number, got {raw!r}", path=path)
    if not bound.minimum <= raw <= bound.maximum:
        raise SeaStackRefused(
            f"{bound.value} states {raw}, outside {bound.minimum} to {bound.maximum}", path=path
        )
    return raw


def _values(
    raw: Mapping[str, object], bounds: Mapping[str, ValueBound], path: str
) -> dict[str, int | str]:
    """Every value ``bounds`` names, read from ``raw`` or defaulted, after refusing a key it does
    not name; a missing required value is refused."""
    unknown = sorted(set(raw) - set(bounds))
    if unknown:
        raise SeaStackRefused(
            f"{path or 'a sea stack'} states no {', '.join(unknown)}; it states {sorted(bounds)}",
            path=path,
        )
    values: dict[str, int | str] = {}
    for name, bound in sorted(bounds.items()):
        where = f"{path}.{name}" if path else name
        if name in raw:
            values[name] = _value(raw[name], bound, where)
        elif bound.required:
            raise SeaStackRefused(f"{name} is required", path=where)
        else:
            values[name] = bound.words[bound.default] if bound.words else bound.default
    return values


def _object(raw: Mapping[str, object], name: str) -> Mapping[str, object]:
    stated = raw.get(name, {})
    if not isinstance(stated, dict):
        raise SeaStackRefused(f"{name} is an object", path=name)
    return stated


def _arch(raw: Mapping[str, object], catalog: SeaStackCatalog) -> dict[str, int | str] | None:
    stated = raw.get("arch", "none")
    if stated == "none":
        return None
    if not isinstance(stated, dict):
        raise SeaStackRefused(f"arch is none or an object, got {stated!r}", path="arch")
    return _values(stated, catalog.values_of("arch"), "arch")


def trunk_radius(document: SeaStackDocument, height_mm: int) -> int:
    """The trunk's radius at ``height_mm`` above level 0, between its foot and its top."""
    span = document.foot_mm + document.height_mm
    rise = height_mm + document.foot_mm
    return (
        document.base_radius_mm + (document.top_radius_mm - document.base_radius_mm) * rise // span
    )


def _rules(document: SeaStackDocument) -> None:
    if document.top_radius_mm > 2 * document.base_radius_mm:
        raise SeaStackRefused(
            f"a top is at most twice its base ({2 * document.base_radius_mm} mm), got "
            f"{document.top_radius_mm}",
            path="top_radius_mm",
        )
    sine, cosine = sin_cos(document.tilt_mdeg)
    taper = (
        (document.base_radius_mm - document.top_radius_mm)
        * 1000
        // (document.foot_mm + document.height_mm)
    )
    lean = sine * 1000 // cosine
    if taper + lean > FLANK_PERMILLE:
        raise SeaStackRefused(
            f"the trunk's flank away from its lean faces up by {taper + lean} per thousand (its "
            f"taper {taper} and its lean {lean}), more than {FLANK_PERMILLE}: its rock under the "
            "water would face up",
            path="top_radius_mm",
            code="stack_flank_faces_up",
        )
    arch = document.arch
    if arch is None:
        return
    narrowest = min(trunk_radius(document, -arch.floor_mm), trunk_radius(document, arch.rise_mm))
    if arch.width_mm > narrowest:
        raise SeaStackRefused(
            f"the trunk carries a passage at most its radius where it passes ({narrowest} mm) "
            f"wide, got {arch.width_mm}",
            path="arch.width_mm",
            code="stack_arch_too_wide",
        )
    if arch.width_mm > 2 * (arch.floor_mm + arch.rise_mm):
        raise SeaStackRefused(
            f"a passage's round head is half its width, so it is at most twice its floor depth "
            f"and rise ({2 * (arch.floor_mm + arch.rise_mm)} mm) wide, got {arch.width_mm}",
            path="arch.width_mm",
            code="stack_arch_too_wide",
        )
    if arch.rise_mm + arch.width_mm > document.height_mm:
        raise SeaStackRefused(
            f"the rock over a passage's crown is at least its width ({arch.width_mm} mm), so its "
            f"rise is at most {document.height_mm - arch.width_mm}, got {arch.rise_mm}",
            path="arch.rise_mm",
            code="stack_arch_too_high",
        )
    least = arch.floor_mm + document.weathering_mm + SILL_MM
    if document.foot_mm < least:
        raise SeaStackRefused(
            f"the foot lies at least the weathering and {SILL_MM} mm below the passage's floor "
            f"({least} mm), got {document.foot_mm}",
            path="foot_mm",
            code="stack_arch_below_foot",
        )


def read_sea_stack_document(
    raw: object, catalog: SeaStackCatalog | None = None
) -> SeaStackDocument:
    """Admit a sea stack document against the catalogs, or refuse it by path."""
    catalog = catalog or sea_stack_catalog()
    if not isinstance(raw, dict):
        raise SeaStackRefused(f"a sea stack document is an object, got {type(raw).__name__}")
    if raw.get("profile") != PROFILE:
        raise SeaStackRefused(f"profile is {PROFILE}, got {raw.get('profile')!r}", path="profile")
    stack_id = raw.get("id")
    if type(stack_id) is not str or KEY_PATTERN.fullmatch(stack_id) is None:
        raise SeaStackRefused(f"an id is a lowercase key, got {stack_id!r}", path="id")
    own = {
        name: value
        for name, value in raw.items()
        if name not in {"profile", "id", *_NESTED, *SECTIONS}
    }
    values = _values(own, catalog.values_of("stack"), "")
    lean = _values(_object(raw, "lean"), catalog.values_of("lean"), "lean")
    arch = _arch(raw, catalog)
    bounds = volume_catalog(VOLUME_CATALOG_VERSION)
    sections = {
        name: _values(_object(raw, name), bounds.values_of(name), name) for name in SECTIONS
    }
    strata = sections["strata"]
    if _whole(strata["spread_mm"]) > _whole(strata["period_mm"]) - 1000:
        raise SeaStackRefused(
            f"strata: a bed is at least 1 m, so the spread is at most the period less 1 m "
            f"({_whole(strata['period_mm']) - 1000} mm), got {strata['spread_mm']}",
            path="strata.spread_mm",
        )
    canonical = {
        "profile": PROFILE,
        "id": stack_id,
        **values,
        "lean": lean,
        "arch": "none" if arch is None else arch,
        **sections,
    }
    encoded = canonical_json(canonical)
    document = SeaStackDocument(
        id=stack_id,
        height_mm=_whole(values["height_mm"]),
        foot_mm=_whole(values["foot_mm"]),
        base_radius_mm=_whole(values["base_radius_mm"]),
        top_radius_mm=_whole(values["top_radius_mm"]),
        shoulders=_whole(values["shoulders"]),
        look=str(values["look"]),
        top_look=str(values["top_look"]),
        walk=str(values["walk"]),
        tilt_mdeg=_whole(lean["tilt_mdeg"]),
        toward_mdeg=_whole(lean["toward_mdeg"]),
        arch=None
        if arch is None
        else SeaStackArch(
            width_mm=_whole(arch["width_mm"]),
            rise_mm=_whole(arch["rise_mm"]),
            floor_mm=_whole(arch["floor_mm"]),
            bearing_mdeg=_whole(arch["bearing_mdeg"]),
        ),
        erosion=sections["erosion"],
        strata=strata,
        canonical_bytes=encoded,
        sha256=hashlib.sha256(encoded).hexdigest(),
    )
    _rules(document)
    return document
