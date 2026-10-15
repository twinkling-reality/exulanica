"""A solid mass as data: ``exulanica.volume/v1``.

What a world says about rock the land cannot state: a cliff that overhangs, a sea stack with an
arch through it, a spire. A volume is a short list of bounded parts in its own frame (x east,
y north, z up, whole millimetres), each a shape from the volume catalog that adds to the mass,
carves from it or caps it at a level, placed, turned and leaned, and joined to what comes before
it with a stated blend; then weathered by erosion and bedded by strata. The field that realizes it
is :mod:`exulanica.grammar.volumes.field`.

**Closed and bounded.** Top keys are ``profile``, ``id`` and ``parts``, and optionally ``look``,
``top_look``, ``walk``, ``erosion`` and ``strata``. A part states ``id`` and ``shape`` and only
values its shape and every part may state; a shape without a placement (a cap) states none; a
required value must be stated; every integer is held to its bound and every word to its words; a
bed is at least 1 m, so the strata's spread is at most its period less 1 m. A refusal names the
path of what it refused, the bound it broke and a code:
``volume_too_many_parts``, ``volume_part_wrong_op`` (an operation its shape does not perform, or a
placement on a shape that has none), ``volume_rounding_too_large``, or ``volume_invalid``.

**Defaults are written in.** The canonical document carries every value of the volume and of every
part, with the catalog's defaults filled in at reading, so a later catalog default never changes a
volume that was made before it. Its identity is the SHA-256 of its canonical JSON. A volume is read
against one version of the catalogs (the newest unless a world's rules name another) and records
it, so the values it carries are that version's.

Integers, keys and catalog words only; nothing here holds a person's words.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final, TypeAlias

from exulanica.canonical import canonical_json
from exulanica.grammar.documents import parse_json
from exulanica.grammar.records import KEY_PATTERN
from exulanica.grammar.volumes.catalog import ValueBound, VolumeCatalog, volume_catalog

__all__ = [
    "PLACEMENT",
    "PROFILE",
    "PartValue",
    "VolumeDocument",
    "VolumePart",
    "VolumeRefused",
    "number",
    "point",
    "read_volume_document",
]

PROFILE: Final = "exulanica.volume/v1"
_REQUIRED: Final = frozenset({"profile", "id", "parts"})
_OPTIONAL: Final = frozenset({"look", "top_look", "walk", "erosion", "strata"})
#: The values a placed part states and a shape without a placement does not.
PLACEMENT: Final = ("at_mm", "yaw_mdeg", "tilt_mdeg", "toward_mdeg")

PartValue: TypeAlias = int | str | tuple[int, ...]


class VolumeRefused(ValueError):
    """A volume document or its realization cannot be admitted. Says where and why."""

    def __init__(self, detail: str, *, path: str = "", code: str = "volume_invalid") -> None:
        self.detail = detail
        self.path = path
        self.code = code
        super().__init__(f"{path}: {detail}" if path else detail)


def number(value: PartValue) -> int:
    """A value its catalog bounds as one whole number."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise VolumeRefused(f"one whole number is expected here, got {value!r}")
    return value


def point(value: PartValue) -> tuple[int, int, int]:
    """A value its catalog bounds as three whole numbers: a point or a size east, north and up."""
    if not isinstance(value, tuple) or len(value) != 3:
        raise VolumeRefused(f"three whole numbers are expected here, got {value!r}")
    return value[0], value[1], value[2]


@dataclass(frozen=True, slots=True)
class VolumePart:
    id: str
    shape: str
    op: str
    #: Every value its shape and every placed part names, stated or defaulted.
    values: Mapping[str, PartValue]


@dataclass(frozen=True, slots=True)
class VolumeDocument:
    id: str
    look: str
    top_look: str
    walk: str
    erosion: Mapping[str, int | str]
    strata: Mapping[str, int | str]
    parts: tuple[VolumePart, ...]
    canonical_bytes: bytes
    sha256: str
    #: The version of the catalogs it was read against.
    catalog_version: int

    def canonical(self) -> dict[str, Any]:
        return parse_json(self.canonical_bytes.decode(), PROFILE)


def _integer(raw: object, bound: ValueBound, path: str, owner: str) -> int:
    if type(raw) is not int:
        raise VolumeRefused(f"{owner} states a whole number here, got {raw!r}", path=path)
    if not bound.minimum <= raw <= bound.maximum:
        raise VolumeRefused(
            f"{owner} states {raw}, outside {bound.minimum} to {bound.maximum}", path=path
        )
    return raw


def _value(raw: object, bound: ValueBound, path: str, owner: str) -> PartValue:
    if bound.words:
        if raw not in bound.words:
            raise VolumeRefused(
                f"{owner}: {bound.value} is one of {', '.join(bound.words)}, got {raw!r}",
                path=path,
            )
        return str(raw)
    if bound.count == 1:
        return _integer(raw, bound, path, owner)
    if not isinstance(raw, list) or len(raw) != bound.count:
        raise VolumeRefused(
            f"{owner}: {bound.value} is a list of {bound.count} whole numbers, got {raw!r}",
            path=path,
        )
    return tuple(_integer(item, bound, f"{path}[{index}]", owner) for index, item in enumerate(raw))


def _default(bound: ValueBound) -> PartValue:
    if bound.words:
        return bound.words[bound.default]
    return bound.default if bound.count == 1 else (bound.default,) * bound.count


def _values(
    raw: Mapping[str, object], bounds: Mapping[str, ValueBound], path: str, owner: str
) -> dict[str, PartValue]:
    """Every value ``bounds`` names, read from ``raw`` or defaulted; a missing required value is
    refused. Keys of ``raw`` outside ``bounds`` are the caller's to refuse."""
    values: dict[str, PartValue] = {}
    for name, bound in sorted(bounds.items()):
        where = f"{path}.{name}" if path else name
        if name in raw:
            values[name] = _value(raw[name], bound, where, owner)
        elif bound.required:
            raise VolumeRefused(f"{owner}: {name} is required", path=where)
        else:
            values[name] = _default(bound)
    return values


def _section(raw: Mapping[str, object], name: str, catalog: VolumeCatalog) -> dict[str, int | str]:
    stated = raw.get(name, {})
    if not isinstance(stated, dict):
        raise VolumeRefused(f"{name} is an object", path=name)
    bounds = catalog.values_of(name)
    unknown = sorted(set(stated) - set(bounds))
    if unknown:
        raise VolumeRefused(
            f"{name} states no {', '.join(unknown)}; it states {sorted(bounds)}", path=name
        )
    return _values(stated, bounds, name, name)  # type: ignore[return-value]


def _shape_rules(part: VolumePart, path: str) -> None:
    values = part.values
    if part.shape == "box":
        size = point(values["size_mm"])
        if 2 * number(values["round_mm"]) > min(size):
            raise VolumeRefused(
                f"{part.id}: a box's rounding is at most half its smallest side ({min(size)} mm), "
                f"got {values['round_mm']}",
                path=f"{path}.round_mm",
                code="volume_rounding_too_large",
            )
    elif part.shape == "column":
        rounding = number(values["round_mm"])
        smaller = min(number(values["base_radius_mm"]), number(values["top_radius_mm"]))
        if 2 * rounding >= number(values["height_mm"]) or rounding > smaller:
            raise VolumeRefused(
                f"{part.id}: a column's rounding is below half its height "
                f"({values['height_mm']} mm) and at most its smaller radius ({smaller} mm), "
                f"got {rounding}",
                path=f"{path}.round_mm",
                code="volume_rounding_too_large",
            )
    elif part.shape == "capsule" and values["to_mm"] == (0, 0, 0):
        raise VolumeRefused(
            f"{part.id}: a capsule's far end is not its own point", path=f"{path}.to_mm"
        )


def _part(raw: object, index: int, catalog: VolumeCatalog) -> VolumePart:
    path = f"parts[{index}]"
    if not isinstance(raw, dict):
        raise VolumeRefused("a part is an object", path=path)
    part_id = raw.get("id")
    if type(part_id) is not str or KEY_PATTERN.fullmatch(part_id) is None:
        raise VolumeRefused(f"an id is a lowercase key, got {part_id!r}", path=f"{path}.id")
    shape_key = raw.get("shape")
    shape = catalog.shapes.get(shape_key) if isinstance(shape_key, str) else None
    if shape is None:
        raise VolumeRefused(
            f"{part_id}: shape {shape_key!r} is not one of {sorted(catalog.shapes)}",
            path=f"{path}.shape",
        )
    op = raw.get("op", shape.ops[0])
    if op not in shape.ops:
        raise VolumeRefused(
            f"{part_id}: the {shape.key} shape does {' or '.join(shape.ops)}, not {op!r}",
            path=f"{path}.op",
            code="volume_part_wrong_op",
        )
    common = catalog.values_of("part")
    if not shape.placed:
        stated = sorted(set(raw) & set(PLACEMENT))
        if stated:
            raise VolumeRefused(
                f"{part_id}: the {shape.key} shape is a level in the volume's own frame and "
                f"states no {', '.join(stated)}",
                path=f"{path}.{stated[0]}",
                code="volume_part_wrong_op",
            )
        common = {name: bound for name, bound in common.items() if name not in PLACEMENT}
    own = catalog.values_of(shape.key)
    bounds = {**common, **own}
    unknown = sorted(set(raw) - {"id", "shape", "op"} - set(bounds))
    if unknown:
        raise VolumeRefused(
            f"{part_id}: the {shape.key} shape states no {', '.join(unknown)}; it states "
            f"{sorted(bounds)}",
            path=path,
        )
    part = VolumePart(
        id=part_id, shape=shape.key, op=str(op), values=_values(raw, bounds, path, part_id)
    )
    _shape_rules(part, path)
    return part


def _plain(value: PartValue) -> object:
    return list(value) if isinstance(value, tuple) else value


def read_volume_document(raw: object, catalog: VolumeCatalog | None = None) -> VolumeDocument:
    """Admit a volume document against the catalog, or refuse it by path."""
    catalog = catalog or volume_catalog()
    if not isinstance(raw, dict) or not _REQUIRED <= set(raw) <= _REQUIRED | _OPTIONAL:
        keys = sorted(raw) if isinstance(raw, dict) else type(raw).__name__
        raise VolumeRefused(
            f"a volume document has {sorted(_REQUIRED)} and may have {sorted(_OPTIONAL)}, "
            f"got {keys}"
        )
    if raw["profile"] != PROFILE:
        raise VolumeRefused(f"profile is {PROFILE}, got {raw['profile']!r}", path="profile")
    volume_id = raw["id"]
    if type(volume_id) is not str or KEY_PATTERN.fullmatch(volume_id) is None:
        raise VolumeRefused(f"an id is a lowercase key, got {volume_id!r}", path="id")
    own = catalog.values_of("volume")
    stated = {name: raw[name] for name in ("look", "top_look", "walk") if name in raw}
    looks = _values(
        stated, {name: own[name] for name in ("look", "top_look", "walk")}, "", "volume"
    )
    erosion = _section(raw, "erosion", catalog)
    strata = _section(raw, "strata", catalog)
    if "spread_mm" in strata and number(strata["spread_mm"]) > number(strata["period_mm"]) - 1000:
        raise VolumeRefused(
            f"strata: a bed is at least 1 m, so the spread is at most the period less 1 m "
            f"({number(strata['period_mm']) - 1000} mm), got {strata['spread_mm']}",
            path="strata.spread_mm",
        )
    parts_raw = raw["parts"]
    if not isinstance(parts_raw, list):
        raise VolumeRefused("parts is a list", path="parts")
    most = own["parts"]
    if len(parts_raw) > most.maximum:
        raise VolumeRefused(
            f"a volume lists at most {most.maximum} parts, got {len(parts_raw)}; a larger mass is "
            "two volumes",
            path="parts",
            code="volume_too_many_parts",
        )
    if len(parts_raw) < most.minimum:
        raise VolumeRefused(f"a volume lists at least {most.minimum} part", path="parts")
    parts: list[VolumePart] = []
    seen: set[str] = set()
    for index, item in enumerate(parts_raw):
        part = _part(item, index, catalog)
        if part.id in seen:
            raise VolumeRefused(f"id {part.id} is used twice", path=f"parts[{index}].id")
        seen.add(part.id)
        parts.append(part)
    if not any(part.op == "add" for part in parts):
        raise VolumeRefused("a volume adds at least one part; carves and caps alone are empty")
    canonical = {
        "profile": PROFILE,
        "id": volume_id,
        **looks,
        "erosion": erosion,
        "strata": strata,
        "parts": [
            {
                "id": part.id,
                "shape": part.shape,
                "op": part.op,
                **{name: _plain(value) for name, value in part.values.items()},
            }
            for part in parts
        ],
    }
    encoded = canonical_json(canonical)
    return VolumeDocument(
        id=volume_id,
        look=str(looks["look"]),
        top_look=str(looks["top_look"]),
        walk=str(looks["walk"]),
        erosion=erosion,
        strata=strata,
        parts=tuple(parts),
        canonical_bytes=encoded,
        sha256=hashlib.sha256(encoded).hexdigest(),
        catalog_version=catalog.version,
    )
