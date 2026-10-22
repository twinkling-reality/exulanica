"""The landform catalogs: the features a land document may list, and the bound of every value.

Two reviewed files in ``assets/catalogs/landform``, read through the grammar's catalog loader so
each entry carries a reason and a licence. They have a folder of their own because the city
grammar refuses any file directly in ``assets/catalogs`` it has no schema for.

* ``landform-feature.vN.json``: one entry per kind of feature, with the plain words a person or a
  model reads (``words``), whether it shapes the near land a world stands on or only the far land
  drawn to the horizon (``domain``), how it composes (``additive`` features sum; ``shaping``
  features then carve or hold the land), and the most of it one document may list (``most``).
* ``landform-value.vN.json``: one entry per value a feature states (``<feature>_<value>``), with
  its minimum, maximum and default, whether it must be stated, and for a value stated in words the
  words it may take (its default is then an index into them). The pseudo-feature ``land`` bounds
  the document itself: its level ground and how many features it lists.

Each version is a pair of files (``landform-feature.vN.json``, ``landform-value.vN.json``), and a
catalog changes only by a new version. A later version keeps every entry of the one before it
unchanged and adds to it, so a document an earlier version admits reads the same under a later
one; a world is read against the version its receipt's land rules name
(:mod:`exulanica.grammar.landform.rules`). Version 2 adds the ``cascade``; version 3 adds its
``course`` and ``least_fall_mm``.

A third file, ``landform-grading.vN.json``, states the figures a layout's grading of its land is
held to (the bank grade, the deepest cut or fill, the most a terrace's retaining wall holds), one
entry each with its bounds and its value. It shapes no land document and is versioned on its own;
land rules from version 6 name it (:mod:`exulanica.grammar.landform.rules`), and earlier rules
grade by the figures the grading module states.

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
    "CATALOG_VERSION",
    "CATALOG_VERSIONS",
    "COMPOSITIONS",
    "DOMAINS",
    "GRADING_CATALOG_VERSIONS",
    "FeatureKind",
    "GradingFigures",
    "LandformCatalog",
    "ValueBound",
    "feature_schema",
    "grading_figures",
    "grading_schema",
    "landform_catalog",
    "load_landform_catalog",
    "value_schema",
]

CATALOG_DIRECTORY: Final = (
    Path(__file__).resolve().parents[3].joinpath("assets", "catalogs", "landform")
)
#: Every version of the landform catalogs this code reads, and the newest, which reads new land.
CATALOG_VERSIONS: Final = (1, 2, 3)
CATALOG_VERSION: Final = 3
#: Every version of the grading figures' catalog this code reads.
GRADING_CATALOG_VERSIONS: Final = (1, 2)
#: The figures a grading catalog states, every version: version 2 adds a bank's ease grade.
GRADING_FIGURES: Final = ("bank_grade_permille", "cut_fill_most_mm", "held_most_mm")
#: The figures each version states beyond :data:`GRADING_FIGURES`.
GRADING_FIGURES_ADDED: Final = {1: (), 2: ("bank_ease_permille",)}
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
class GradingFigures:
    """The figures a layout's grading of its land is held to: the bank grade, the deepest a cell
    may be cut or filled, the most a terrace's retaining wall holds where its bank would pass
    that, and from version 2 the grade a bank eases to at its crest and toe (0 before)."""

    bank_grade_permille: int
    cut_fill_most_mm: int
    held_most_mm: int
    bank_ease_permille: int = 0

    def __post_init__(self) -> None:
        if self.bank_ease_permille > self.bank_grade_permille:
            raise CatalogError(
                f"a bank eases at {self.bank_ease_permille} per mille, steeper than its grade of "
                f"{self.bank_grade_permille}: its crest and toe would stand steeper than the bank"
            )


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


def feature_schema(version: int) -> CatalogSchema:
    """The feature catalog's schema at ``version``: the same fields at every version."""
    return CatalogSchema(
        "landform-feature",
        version,
        (
            ("words", text_field),
            ("domain", text_field),
            ("composition", text_field),
            ("most", integer_field(1, 64)),
            ("reason", text_field),
        ),
        entry_check=_feature_check,
    )


def value_schema(version: int) -> CatalogSchema:
    """The value catalog's schema at ``version``: the same fields at every version."""
    return CatalogSchema(
        "landform-value",
        version,
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


def load_landform_catalog(
    directory: Path = CATALOG_DIRECTORY, version: int = CATALOG_VERSION
) -> LandformCatalog:
    if version not in CATALOG_VERSIONS:
        raise CatalogError(f"landform catalogs are versions {CATALOG_VERSIONS}, not {version}")
    features_file = load_catalog(
        directory.joinpath(f"landform-feature.v{version}.json"), feature_schema(version)
    )
    values_file = load_catalog(
        directory.joinpath(f"landform-value.v{version}.json"), value_schema(version)
    )
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


def _grading_check(where: str, fields: dict) -> None:
    if not fields["minimum"] <= fields["value"] <= fields["maximum"]:
        raise CatalogError(f"{where}: the value lies within the bounds")


def grading_schema(version: int) -> CatalogSchema:
    """The grading figures' catalog schema at ``version``: the same fields at every version."""
    return CatalogSchema(
        "landform-grading",
        version,
        (
            ("minimum", integer_field(0, _ANY)),
            ("maximum", integer_field(0, _ANY)),
            ("value", integer_field(0, _ANY)),
            ("reason", text_field),
        ),
        entry_check=_grading_check,
    )


@functools.cache
def grading_figures(version: int) -> GradingFigures:
    """The grading figures the shipped catalog states at ``version``, read once per process; a
    catalog that states other figures than :data:`GRADING_FIGURES` and those its version adds is
    refused."""
    if version not in GRADING_CATALOG_VERSIONS:
        raise CatalogError(
            f"landform grading catalogs are versions {GRADING_CATALOG_VERSIONS}, not {version}"
        )
    catalog = load_catalog(
        CATALOG_DIRECTORY.joinpath(f"landform-grading.v{version}.json"), grading_schema(version)
    )
    stated = {entry.key: int(dict(entry.values)["value"]) for entry in catalog.entries}  # type: ignore[arg-type]
    figures = sorted((*GRADING_FIGURES, *GRADING_FIGURES_ADDED[version]))
    if sorted(stated) != figures:
        raise CatalogError(f"landform-grading v{version} states {sorted(stated)}, not {figures}")
    return GradingFigures(**stated)


@functools.cache
def landform_catalog(version: int = CATALOG_VERSION) -> LandformCatalog:
    """The shipped catalogs at ``version`` (the newest unless one is named), read once per
    process."""
    return load_landform_catalog(version=version)
