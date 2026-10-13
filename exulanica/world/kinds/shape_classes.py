"""Versioned structural content classes, validated independently of their labels."""

from __future__ import annotations

import functools
import hashlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, cast

from exulanica.grammar.catalogs import CatalogSchema, integer_field, load_catalog, text_field
from exulanica.grammar.errors import CatalogError
from exulanica.grammar.grammars.site.plan import ROOF_FORMS
from exulanica.world.kinds.catalogs import CATALOG_DIRECTORY, load_kind_catalogs

_NUMBERS = (
    "default_width_mm",
    "default_depth_mm",
    "default_storeys",
    "default_storey_height_mm",
    "default_height_mm",
    "default_thickness_mm",
    "minimum_width_mm",
    "maximum_width_mm",
    "minimum_depth_mm",
    "maximum_depth_mm",
    "minimum_height_mm",
    "maximum_height_mm",
    "minimum_thickness_mm",
    "maximum_thickness_mm",
    "minimum_height_to_short_side_permille",
    "maximum_height_to_short_side_permille",
)


class ShapeRefused(ValueError):
    """A declared structural class is unknown or its shape does not meet the class."""


@dataclass(frozen=True, slots=True)
class ShapeClass:
    key: str
    form: str
    words: str
    values: Mapping[str, int | str]

    def number(self, field: str) -> int:
        return cast(int, self.values[field])


@dataclass(frozen=True, slots=True)
class ShapeClasses:
    version: int
    sha256: str
    entries: Mapping[str, ShapeClass]

    def reference(self, key: str) -> dict[str, int | str]:
        return {"key": key, "version": self.version, "sha256": self.sha256}


def _entry(where: str, values: Mapping[str, Any]) -> None:
    form = values["form"]
    if form not in ("structure", "boundary"):
        raise CatalogError(f"{where}: a shape class is a structure or boundary")
    for axis in ("width", "depth", "height", "thickness"):
        if values[f"minimum_{axis}_mm"] > values[f"maximum_{axis}_mm"]:
            raise CatalogError(f"{where}: {axis} range is reversed")
    if (
        values["minimum_height_to_short_side_permille"]
        > values["maximum_height_to_short_side_permille"]
    ):
        raise CatalogError(f"{where}: height proportion range is reversed")
    if form == "structure":
        limits = load_kind_catalogs(bounds_version=2)
        for axis in ("width", "depth"):
            low, high = limits.bound(f"structure_{axis}_mm")
            if (
                not low
                <= values[f"minimum_{axis}_mm"]
                <= values[f"default_{axis}_mm"]
                <= (values[f"maximum_{axis}_mm"])
                <= high
            ):
                raise CatalogError(f"{where}: default {axis} and range fit the kind bounds")
        for field in ("storeys", "storey_height_mm"):
            low, high = limits.bound(field)
            if not low <= values[f"default_{field}"] <= high:
                raise CatalogError(f"{where}: default {field} fits the kind bounds")
        if values["default_roof_form"] not in ROOF_FORMS:
            raise CatalogError(f"{where}: default roof is a supported form")
        height = values["default_storeys"] * values["default_storey_height_mm"]
        if not values["minimum_height_mm"] <= height <= values["maximum_height_mm"]:
            raise CatalogError(f"{where}: default structure height fits its class")
        short = min(values["default_width_mm"], values["default_depth_mm"])
        if not (
            values["minimum_height_to_short_side_permille"] * short
            <= height * 1000
            <= values["maximum_height_to_short_side_permille"] * short
        ):
            raise CatalogError(f"{where}: default proportions fit their class")
    else:
        limits = load_kind_catalogs(bounds_version=2)
        for field in ("height_mm", "thickness_mm"):
            axis = field.removesuffix("_mm")
            low, high = limits.bound(f"boundary_{field}")
            if (
                not low
                <= values[f"minimum_{axis}_mm"]
                <= values[f"default_{field}"]
                <= (values[f"maximum_{axis}_mm"])
                <= high
            ):
                raise CatalogError(f"{where}: default {axis} and range fit the kind bounds")


@functools.cache
def load_shape_classes(version: int = 1) -> ShapeClasses:
    if type(version) is not int or version != 1:
        raise ShapeRefused("unknown shape-class catalog version")
    path = CATALOG_DIRECTORY / f"shape-class.v{version}.json"
    catalog = load_catalog(
        path,
        CatalogSchema(
            "shape-class",
            version,
            (
                ("form", text_field),
                ("words", text_field),
                ("default_roof_form", text_field),
                *((name, integer_field(0, 60000)) for name in _NUMBERS),
                ("reason", text_field),
            ),
            entry_check=_entry,
        ),
    )
    entries = {}
    for entry in catalog.entries:
        values = dict(entry.values)
        entries[entry.key] = ShapeClass(
            entry.key,
            str(values["form"]),
            str(values["words"]),
            MappingProxyType(cast(dict[str, int | str], values)),
        )
    return ShapeClasses(
        version, hashlib.sha256(path.read_bytes()).hexdigest(), MappingProxyType(entries)
    )


def read_shape_reference(raw: object, form: str) -> ShapeClass:
    if not isinstance(raw, dict) or set(raw) != {"key", "version", "sha256"}:
        raise ShapeRefused("a shape class names exactly key, version and catalog sha256")
    if type(raw["version"]) is not int:
        raise ShapeRefused("shape class version is an integer")
    catalog = load_shape_classes(raw["version"])
    if raw["sha256"] != catalog.sha256 or type(raw["key"]) is not str:
        raise ShapeRefused("shape class catalog digest or key does not match")
    entry = catalog.entries.get(raw["key"])
    if entry is None or entry.form != form:
        raise ShapeRefused("shape class is unknown or belongs to another form")
    return entry


def check_shape(
    shape: ShapeClass,
    fields: Mapping[str, Any],
    limits: Callable[[Any], tuple[int, int]],
) -> None:
    """Every parameter/span outcome meets the shape, not just a sampled seed."""
    if shape.form == "structure":
        width, depth, storeys = (limits(fields[k]) for k in ("width_mm", "depth_mm", "storeys"))
        height = tuple(n * fields["storey_height_mm"] for n in storeys)
        for axis, bounds in (("width", width), ("depth", depth), ("height", height)):
            if (
                not shape.number(f"minimum_{axis}_mm")
                <= bounds[0]
                <= bounds[1]
                <= (shape.number(f"maximum_{axis}_mm"))
            ):
                raise ShapeRefused(f"{axis} range does not meet the declared shape class")
        # For all combinations: smallest height / largest short side, and the converse.
        if height[0] * 1000 < shape.number("minimum_height_to_short_side_permille") * min(
            width[1], depth[1]
        ) or height[1] * 1000 > shape.number("maximum_height_to_short_side_permille") * min(
            width[0], depth[0]
        ):
            raise ShapeRefused("height proportions do not meet the declared shape class")
    else:
        for axis in ("height", "thickness"):
            if (
                not shape.number(f"minimum_{axis}_mm")
                <= fields[f"{axis}_mm"]
                <= (shape.number(f"maximum_{axis}_mm"))
            ):
                raise ShapeRefused(f"{axis} does not meet the declared shape class")
