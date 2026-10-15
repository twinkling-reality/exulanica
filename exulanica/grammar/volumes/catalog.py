"""The volume catalogs: the shapes a volume's parts may take, and the bound of every value.

Two reviewed files in ``assets/catalogs/volumes``, read through the grammar's catalog loader so
each entry carries a reason and a licence, as the landform catalogs are.

* ``volume-shape.vN.json``: one entry per shape a part may take, with the plain words a person or
  a model reads (``words``), the operations it may perform (``ops``, the first its default: a part
  adds to the mass, carves from it, or caps it), and whether it states a placement (``placed``: a
  cap is a level in the volume's own frame and has none).
* ``volume-value.vN.json``: one entry per value (``<owner>_<value>``), with its minimum, maximum
  and default, whether it must be stated, how many whole numbers it is (``count``: 1, or 3 for a
  point or a size east, north and up), and for a value stated in words the words it may take (its
  default is then an index into them). The owner is a shape, ``part`` (what every part states),
  ``volume`` (the document itself: its looks, whether it is walked, how many parts it lists),
  ``erosion`` or ``strata``.

A catalog changes only by a new version, and a later version keeps every entry of the one before
it, so a volume an earlier version admits reads the same under a later one. Read on first use,
never at import, and kept for the process.
"""

from __future__ import annotations

import functools
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from exulanica.grammar.catalogs import (
    CatalogSchema,
    integer_field,
    key_list_field,
    load_catalog,
    text_field,
)
from exulanica.grammar.errors import CatalogError

__all__ = [
    "CATALOG_DIRECTORY",
    "CATALOG_VERSION",
    "CATALOG_VERSIONS",
    "OPS",
    "OWNERS",
    "ShapeKind",
    "ValueBound",
    "VolumeCatalog",
    "load_volume_catalog",
    "shape_schema",
    "value_schema",
    "volume_catalog",
]

CATALOG_DIRECTORY: Final = (
    Path(__file__).resolve().parents[3].joinpath("assets", "catalogs", "volumes")
)
#: Every version of the volume catalogs this code reads, and the newest, which reads new volumes.
CATALOG_VERSIONS: Final = (1,)
CATALOG_VERSION: Final = 1
#: What a part may do to the mass: add to it, carve from it, or cap it at a level.
OPS: Final = ("add", "carve", "cap")
#: The owners of values that are not a shape.
OWNERS: Final = ("volume", "erosion", "strata", "part")
#: The values the reader states by name; a catalog without one of them is refused at loading.
_NAMED: Final = (
    ("volume", "parts"),
    ("volume", "look"),
    ("volume", "top_look"),
    ("volume", "walk"),
    ("part", "at_mm"),
    ("part", "yaw_mdeg"),
    ("part", "tilt_mdeg"),
    ("part", "toward_mdeg"),
    ("part", "blend_mm"),
    ("part", "look"),
)
#: Wider than any bound a value states, so the file, not this schema, says what a value may be.
_ANY: Final = 1_000_000_000


@dataclass(frozen=True, slots=True)
class ShapeKind:
    key: str
    words: str
    ops: tuple[str, ...]
    placed: bool


@dataclass(frozen=True, slots=True)
class ValueBound:
    owner: str
    value: str
    minimum: int
    maximum: int
    default: int
    required: bool
    count: int
    words: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class VolumeCatalog:
    shapes: Mapping[str, ShapeKind]
    #: Keyed by (owner, value).
    values: Mapping[tuple[str, str], ValueBound]

    def values_of(self, owner: str) -> dict[str, ValueBound]:
        return {value: bound for (named, value), bound in self.values.items() if named == owner}


def _shape_check(where: str, fields: dict) -> None:
    ops = fields["ops"]
    if not ops or len(set(ops)) != len(ops) or not set(ops) <= set(OPS):
        raise CatalogError(f"{where}: ops are distinct words of {OPS}")
    if "cap" in ops and (len(ops) != 1 or fields["placed"]):
        raise CatalogError(f"{where}: a shape that caps does nothing else and has no placement")


def _value_check(where: str, fields: dict) -> None:
    words = fields["words"]
    if words:
        if fields["minimum"] or fields["maximum"] or fields["count"] != 1:
            raise CatalogError(f"{where}: a value stated in words is one word, with no range")
        if not 0 <= fields["default"] < len(words):
            raise CatalogError(f"{where}: a word value's default indexes its words")
    elif not fields["minimum"] <= fields["default"] <= fields["maximum"]:
        raise CatalogError(f"{where}: the default lies within the bounds")


def shape_schema(version: int) -> CatalogSchema:
    """The shape catalog's schema at ``version``: the same fields at every version."""
    return CatalogSchema(
        "volume-shape",
        version,
        (
            ("words", text_field),
            ("ops", key_list_field),
            ("placed", integer_field(0, 1)),
            ("reason", text_field),
        ),
        entry_check=_shape_check,
    )


def value_schema(version: int) -> CatalogSchema:
    """The value catalog's schema at ``version``: the same fields at every version."""
    return CatalogSchema(
        "volume-value",
        version,
        (
            ("owner", text_field),
            ("value", text_field),
            ("minimum", integer_field(-_ANY, _ANY)),
            ("maximum", integer_field(-_ANY, _ANY)),
            ("default", integer_field(-_ANY, _ANY)),
            ("required", integer_field(0, 1)),
            ("count", integer_field(1, 3)),
            ("words", key_list_field),
            ("reason", text_field),
        ),
        entry_check=_value_check,
    )


def load_volume_catalog(
    directory: Path = CATALOG_DIRECTORY, version: int = CATALOG_VERSION
) -> VolumeCatalog:
    if version not in CATALOG_VERSIONS:
        raise CatalogError(f"volume catalogs are versions {CATALOG_VERSIONS}, not {version}")
    shapes_file = load_catalog(
        directory.joinpath(f"volume-shape.v{version}.json"), shape_schema(version)
    )
    values_file = load_catalog(
        directory.joinpath(f"volume-value.v{version}.json"), value_schema(version)
    )
    shapes = {}
    for entry in shapes_file.entries:
        fields = dict(entry.values)
        if entry.key in OWNERS:
            raise CatalogError(f"volume-shape {entry.key} takes the name of a value owner")
        shapes[entry.key] = ShapeKind(
            key=entry.key,
            words=str(fields["words"]),
            ops=tuple(fields["ops"]),  # type: ignore[arg-type]
            placed=bool(fields["placed"]),
        )
    values = {}
    for entry in values_file.entries:
        fields = dict(entry.values)
        owner, value = str(fields["owner"]), str(fields["value"])
        if owner not in OWNERS and owner not in shapes:
            raise CatalogError(f"volume-value {entry.key} bounds an unknown owner {owner!r}")
        if entry.key != f"{owner}_{value}":
            raise CatalogError(f"volume-value {entry.key} is keyed by its owner and value")
        values[(owner, value)] = ValueBound(
            owner=owner,
            value=value,
            minimum=int(fields["minimum"]),  # type: ignore[arg-type]
            maximum=int(fields["maximum"]),  # type: ignore[arg-type]
            default=int(fields["default"]),  # type: ignore[arg-type]
            required=bool(fields["required"]),
            count=int(fields["count"]),  # type: ignore[arg-type]
            words=tuple(fields["words"]),  # type: ignore[arg-type]
        )
    missing = [f"{owner}_{value}" for owner, value in _NAMED if (owner, value) not in values]
    if missing:
        raise CatalogError(f"volume-value v{version} does not bound {', '.join(missing)}")
    return VolumeCatalog(shapes=shapes, values=values)


@functools.cache
def volume_catalog(version: int = CATALOG_VERSION) -> VolumeCatalog:
    """The shipped catalogs at ``version`` (the newest unless one is named), read once per
    process."""
    return load_volume_catalog(version=version)
