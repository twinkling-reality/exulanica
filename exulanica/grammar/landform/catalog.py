"""The landform catalogs: the features a land document may list, and the bound of every value.

Two reviewed files in ``assets/catalogs/landform``, read through the grammar's catalog loader so
each entry carries a reason and a licence. They have a folder of their own because the city
grammar refuses any file directly in ``assets/catalogs`` it has no schema for.

* ``landform-feature.v1.json``: one entry per kind of feature, with the plain words a person or a
  model reads (``words``), whether it shapes the near land a world stands on or only the far land
  drawn to the horizon (``domain``), how it composes (``additive`` features sum; ``shaping``
  features then carve or hold the land), and the most of it one document may list (``most``).
* ``landform-value.v1.json``: one entry per value a feature states (``<feature>_<value>``), with
  its minimum, maximum and default, whether it must be stated, and for a value stated in words the
  words it may take (its default is then an index into them). The pseudo-feature ``land`` bounds
  the document itself: its level ground and how many features it lists.

Read on first use, never at import, and kept for the process: a catalog is authored data and
changes only with a release.
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
    "COMPOSITIONS",
    "DOMAINS",
    "FeatureKind",
    "LandformCatalog",
    "ValueBound",
    "landform_catalog",
    "load_landform_catalog",
]

CATALOG_DIRECTORY: Final = (
    Path(__file__).resolve().parents[3].joinpath("assets", "catalogs", "landform")
)
DOMAINS: Final = ("near_and_far", "far")
COMPOSITIONS: Final = ("additive", "shaping")
#: Wider than any bound a value states, so the file, not this schema, says what a value may be.
_ANY: Final = 1_000_000_000


@dataclass(frozen=True, slots=True)
class FeatureKind:
    key: str
    words: str
    domain: str
    composition: str
    most: int


@dataclass(frozen=True, slots=True)
class ValueBound:
    feature: str
    value: str
    minimum: int
    maximum: int
    default: int
    required: bool
    words: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class LandformCatalog:
    features: Mapping[str, FeatureKind]
    #: Keyed by (feature, value); the feature ``land`` bounds the document itself.
    values: Mapping[tuple[str, str], ValueBound]

    def values_of(self, feature: str) -> dict[str, ValueBound]:
        return {value: bound for (owner, value), bound in self.values.items() if owner == feature}


def _feature_check(where: str, fields: dict) -> None:
    if fields["domain"] not in DOMAINS:
        raise CatalogError(f"{where}: domain is one of {DOMAINS}")
    if fields["composition"] not in COMPOSITIONS:
        raise CatalogError(f"{where}: composition is one of {COMPOSITIONS}")


def _value_check(where: str, fields: dict) -> None:
    words = fields["words"]
    if words:
        if fields["minimum"] or fields["maximum"]:
            raise CatalogError(f"{where}: a value stated in words has no numeric range")
        if not 0 <= fields["default"] < len(words):
            raise CatalogError(f"{where}: a word value's default indexes its words")
    elif not fields["minimum"] <= fields["default"] <= fields["maximum"]:
        raise CatalogError(f"{where}: the default lies within the bounds")


FEATURE_SCHEMA: Final = CatalogSchema(
    "landform-feature",
    1,
    (
        ("words", text_field),
        ("domain", text_field),
        ("composition", text_field),
        ("most", integer_field(1, 64)),
        ("reason", text_field),
    ),
    entry_check=_feature_check,
)
VALUE_SCHEMA: Final = CatalogSchema(
    "landform-value",
    1,
    (
        ("feature", text_field),
        ("value", text_field),
        ("minimum", integer_field(-_ANY, _ANY)),
        ("maximum", integer_field(-_ANY, _ANY)),
        ("default", integer_field(-_ANY, _ANY)),
        ("required", integer_field(0, 1)),
        ("words", key_list_field),
        ("reason", text_field),
    ),
    entry_check=_value_check,
)


def load_landform_catalog(directory: Path = CATALOG_DIRECTORY) -> LandformCatalog:
    features_file = load_catalog(directory.joinpath("landform-feature.v1.json"), FEATURE_SCHEMA)
    values_file = load_catalog(directory.joinpath("landform-value.v1.json"), VALUE_SCHEMA)
    features = {}
    for entry in features_file.entries:
        fields = dict(entry.values)
        features[entry.key] = FeatureKind(
            key=entry.key,
            words=str(fields["words"]),
            domain=str(fields["domain"]),
            composition=str(fields["composition"]),
            most=int(fields["most"]),  # type: ignore[arg-type]
        )
    values = {}
    for entry in values_file.entries:
        fields = dict(entry.values)
        feature, value = str(fields["feature"]), str(fields["value"])
        if feature != "land" and feature not in features:
            raise CatalogError(f"landform-value {entry.key} bounds an unknown feature {feature!r}")
        if entry.key != f"{feature}_{value}":
            raise CatalogError(f"landform-value {entry.key} is keyed by its feature and value")
        values[(feature, value)] = ValueBound(
            feature=feature,
            value=value,
            minimum=int(fields["minimum"]),  # type: ignore[arg-type]
            maximum=int(fields["maximum"]),  # type: ignore[arg-type]
            default=int(fields["default"]),  # type: ignore[arg-type]
            required=bool(fields["required"]),
            words=tuple(fields["words"]),  # type: ignore[arg-type]
        )
    return LandformCatalog(features=features, values=values)


@functools.cache
def landform_catalog() -> LandformCatalog:
    """The shipped catalogs, read once per process."""
    return load_landform_catalog()
