"""The catalogs the city reads, the entry schema of each, and the checks across them.

The files live in ``assets/catalogs`` at the repository root, one per catalog, named
``<catalog_id>.v<version>.json``. Subdirectories belong to other lanes (``society``, ``traffic``)
and to retained sources (``sources``), and the loader does not read them.

**What an entry is.** A key, a licence stated the way ``docs/license-matrix.md`` states one, and
the fields its schema declares, always including ``reason``: why the entry exists and where its
content came from. Authored design vocabulary says that it is authored and why; a derived entry
names the retained source it was derived from, which its licence's ``content_source`` points at.

**Keys are labels.** No reader draws a shape from a catalog key: the geometry a key implies is
resolved into the record that uses it (a furniture class's parts, a roof family's form, a
material's texture set and modules). Catalog entries are where those values come from, reviewed.

**Material entries resolve a texture set.** The sets are the texture lane's published manifest,
read by :func:`exulanica.grammar.textures.read_texture_manifest` unless the caller passes others.
A resolved entry carries its set's version and content digest into the catalog digest, while the
file keeps the id alone, so a rebaked set moves the digest with every catalog file unchanged.

**Across catalogs**, :func:`check_city_catalogs` holds every cross reference: an era's wall
materials dress a wall, a typology's uses, eras and roof families exist, every signed use class
has a sign and every sign names a signed use class, a fitout's use classes and a street name's
hierarchies exist.

The catalog directory is found relative to this source file, so it is present in a checkout and
absent from an installed wheel. Tiles are baked offline from a checkout.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Final

from exulanica.grammar.catalogs import (
    Catalog,
    CatalogSchema,
    FieldCheck,
    FieldValue,
    ReferenceField,
    integer_field,
    key_list_field,
    load_catalog_directory,
    text_field,
)
from exulanica.grammar.errors import CatalogError, GrammarError
from exulanica.grammar.grammars.city.common import (
    APPROACH_CONTROLS,
    FORM_PART_SHAPE,
    OBJECT_ROLES,
    SURFACE_ROLES,
    FormPart,
)
from exulanica.grammar.shapes import validate_record
from exulanica.grammar.textures import TEXTURE_SET_ID, TextureSet, read_texture_manifest

__all__ = [
    "CATALOG_DIRECTORY",
    "CITY_CATALOG_IDS",
    "check_city_catalogs",
    "city_catalog_schemas",
    "city_vocabularies",
    "entry_fields",
    "form_parts",
    "load_city_catalogs",
]

CATALOG_DIRECTORY: Final = Path(__file__).resolve().parents[4].joinpath("assets", "catalogs")
_MILLIMETRES: Final = integer_field(0, 100_000_000)
_BAND_TOP: Final = integer_field(1, 100_000)
_FORM_PART_FIELDS: Final = tuple(field.name for field in dataclasses.fields(FormPart))


def choice_field(values: Sequence[str]) -> FieldCheck:
    closed = tuple(values)

    def check(where: str, value: object) -> FieldValue:
        if type(value) is not str or value not in closed:
            raise CatalogError(f"{where} is one of {closed}, got {value!r}")
        return value

    return check


def closed_list_field(values: Sequence[str]) -> FieldCheck:
    """A list of distinct values from a closed set, in the set's own order."""
    closed = tuple(values)

    def check(where: str, value: object) -> FieldValue:
        items = key_list_field(where, value)
        assert isinstance(items, tuple)
        for item in items:
            if item not in closed:
                raise CatalogError(f"{where}: {item!r} is not one of {closed}")
        if list(items) != sorted(items, key=closed.index):
            raise CatalogError(f"{where} lists its values in the order {closed}")
        return items

    return check


def sorted_key_list_field(where: str, value: object) -> FieldValue:
    items = key_list_field(where, value)
    if not items or list(items) != sorted(items):  # type: ignore[arg-type]
        raise CatalogError(f"{where} is a non-empty list of keys, sorted")
    return items


def form_parts_field(where: str, value: object) -> FieldValue:
    """A non-empty list of parts, each exactly a :class:`FormPart`'s fields, checked as one."""
    if not isinstance(value, list) or not value:
        raise CatalogError(f"{where} is a non-empty list of parts")
    parts = []
    for index, item in enumerate(value):
        if not isinstance(item, dict) or set(item) != set(_FORM_PART_FIELDS):
            raise CatalogError(f"{where}[{index}] has exactly the fields {list(_FORM_PART_FIELDS)}")
        try:
            validate_record(FormPart(**item), FORM_PART_SHAPE)
        except GrammarError as error:
            raise CatalogError(f"{where}[{index}]: {error}") from error
        if item["surface_role"] not in OBJECT_ROLES:
            raise CatalogError(f"{where}[{index}] takes an object role, one of {OBJECT_ROLES}")
        parts.append(tuple((name, item[name]) for name in _FORM_PART_FIELDS))
    return tuple(parts)  # type: ignore[arg-type]


def form_parts(value: object) -> tuple[FormPart, ...]:
    """The parts a :func:`form_parts_field` value holds."""
    return tuple(FormPart(**dict(part)) for part in value)  # type: ignore[arg-type,union-attr]


def _ordered(*pairs: tuple[str, str]) -> Callable[[str, dict[str, FieldValue]], None]:
    def check(where: str, values: dict[str, FieldValue]) -> None:
        for low, high in pairs:
            if values[low] > values[high]:  # type: ignore[operator]
                raise CatalogError(f"{where}: {low} is at most {high}")

    return check


def _band_bounds_ordered(where: str, values: dict[str, FieldValue]) -> None:
    _ordered(("top_minimum_mm", "top_maximum_mm"))(where, values)


def _roof_rise(where: str, values: dict[str, FieldValue]) -> None:
    _ordered(("rise_minimum_mm", "rise_maximum_mm"))(where, values)
    flat = values["form"] == "flat"
    if flat != (values["rise_maximum_mm"] == 0):
        raise CatalogError(f"{where}: a flat roof has no rise and a ridge roof has one")


REASON: Final = ("reason", text_field)


def city_catalog_schemas(*, texture_sets: Mapping[str, TextureSet]) -> tuple[CatalogSchema, ...]:
    texture_pins = {set_id: texture_set.pin() for set_id, texture_set in texture_sets.items()}
    return (
        CatalogSchema("action-vocabulary", 1, (("label", text_field),)),
        CatalogSchema(
            "band",
            1,
            (
                ("label", text_field),
                ("top_minimum_mm", _BAND_TOP),
                ("top_maximum_mm", _BAND_TOP),
                ("elements", key_list_field),
            ),
            entry_check=_band_bounds_ordered,
        ),
        CatalogSchema(
            "crossing-type",
            1,
            (
                ("label", text_field),
                ("kerb", choice_field(("flush", "dropped"))),
                ("marking", choice_field(("zebra", "parallel_lines", "none"))),
                ("signal", choice_field(("required", "none"))),
                ("width_minimum_mm", _MILLIMETRES),
                ("width_maximum_mm", _MILLIMETRES),
                REASON,
            ),
            entry_check=_ordered(("width_minimum_mm", "width_maximum_mm")),
        ),
        CatalogSchema(
            "era",
            1,
            (
                ("label", text_field),
                ("start_year", integer_field(1000, 3000)),
                ("end_year", integer_field(1000, 3000)),
                ("wall_materials", sorted_key_list_field),
                ("roof_families", sorted_key_list_field),
                ("upper_storey_minimum_mm", _MILLIMETRES),
                ("upper_storey_maximum_mm", _MILLIMETRES),
                ("cornice", choice_field(("required", "optional", "none"))),
                REASON,
            ),
            entry_check=_ordered(
                ("start_year", "end_year"),
                ("upper_storey_minimum_mm", "upper_storey_maximum_mm"),
            ),
        ),
        CatalogSchema(
            "fitout",
            1,
            (
                ("label", text_field),
                ("use_classes", sorted_key_list_field),
                ("light", choice_field(("dim", "warm", "bright"))),
                ("parts", form_parts_field),
                REASON,
            ),
        ),
        CatalogSchema(
            "junction-control",
            1,
            (
                ("label", text_field),
                ("signal", choice_field(("required", "none"))),
                ("approach_controls", closed_list_field(APPROACH_CONTROLS)),
                REASON,
            ),
        ),
        CatalogSchema(
            "lane-use",
            1,
            (
                ("label", text_field),
                ("traffic", choice_field(("carries", "none"))),
                ("width_minimum_mm", _MILLIMETRES),
                ("width_maximum_mm", _MILLIMETRES),
                REASON,
            ),
            entry_check=_ordered(("width_minimum_mm", "width_maximum_mm")),
        ),
        CatalogSchema(
            "material",
            2,
            (
                ("label", text_field),
                (
                    "category",
                    choice_field(
                        ("masonry", "stone", "render", "concrete", "metal", "asphalt", "paving")
                    ),
                ),
                ("texture_set_id", ReferenceField("a texture set", TEXTURE_SET_ID, texture_pins)),
                ("surfaces", closed_list_field(SURFACE_ROLES)),
                ("course_module_mm", _MILLIMETRES),
                ("mortar_module_mm", _MILLIMETRES),
                ("unit_length_mm", _MILLIMETRES),
                ("bond", choice_field(("running", "half", "stack", "none"))),
                REASON,
            ),
        ),
        CatalogSchema(
            "parking-kind",
            1,
            (
                ("label", text_field),
                ("placement", choice_field(("carriageway", "footway"))),
                ("length_minimum_mm", _MILLIMETRES),
                ("length_maximum_mm", _MILLIMETRES),
                ("width_minimum_mm", _MILLIMETRES),
                ("width_maximum_mm", _MILLIMETRES),
                REASON,
            ),
            entry_check=_ordered(
                ("length_minimum_mm", "length_maximum_mm"),
                ("width_minimum_mm", "width_maximum_mm"),
            ),
        ),
        CatalogSchema(
            "roof-family",
            2,
            (
                ("label", text_field),
                ("form", choice_field(("flat", "ridge"))),
                ("rise_minimum_mm", _MILLIMETRES),
                ("rise_maximum_mm", _MILLIMETRES),
                ("parapet", choice_field(("required", "optional", "none"))),
                ("rooftop_objects", choice_field(("allowed", "none"))),
                REASON,
            ),
            entry_check=_roof_rise,
        ),
        CatalogSchema(
            "rooftop-object",
            1,
            (
                ("label", text_field),
                ("clearance_minimum_mm", _MILLIMETRES),
                ("parts", form_parts_field),
                REASON,
            ),
        ),
        CatalogSchema(
            "signage-lexicon",
            2,
            (("text", text_field), ("use_class", text_field), REASON),
        ),
        CatalogSchema(
            "street-furniture",
            2,
            (
                ("label", text_field),
                (
                    "category",
                    choice_field(
                        (
                            "lighting",
                            "seating",
                            "waste",
                            "bollard",
                            "cycle_parking",
                            "signal",
                            "signage",
                            "utility",
                        )
                    ),
                ),
                ("bicycles_per_stand", integer_field(0, 16)),
                ("exclusion_radius_mm", _MILLIMETRES),
                ("kerb_offset_minimum_mm", _MILLIMETRES),
                ("kerb_offset_maximum_mm", _MILLIMETRES),
                # Where a class stands, and how far apart. ``kerb_line`` reads the spacing band;
                # every other placement states 0 and 0, since its place is not a rhythm.
                ("placement", choice_field(("kerb_line", "at_crossing", "at_junction", "none"))),
                ("spacing_minimum_mm", _MILLIMETRES),
                ("spacing_maximum_mm", _MILLIMETRES),
                # Another class that stands beside this one where both are placed, or "none".
                ("pairs_with", text_field),
                ("parts", form_parts_field),
                REASON,
            ),
            entry_check=_ordered(("kerb_offset_minimum_mm", "kerb_offset_maximum_mm")),
        ),
        CatalogSchema(
            "street-hierarchy",
            2,
            (
                ("label", text_field),
                ("rank", integer_field(0, 1000)),
                ("lanes_minimum", integer_field(1, 16)),
                ("lanes_maximum", integer_field(1, 16)),
                ("lane_width_minimum_mm", _MILLIMETRES),
                ("lane_width_maximum_mm", _MILLIMETRES),
                ("footway_width_minimum_mm", _MILLIMETRES),
                ("footway_width_maximum_mm", _MILLIMETRES),
                ("speed_limit_minimum_mm_s", _MILLIMETRES),
                ("speed_limit_maximum_mm_s", _MILLIMETRES),
                ("kerb_height_minimum_mm", _MILLIMETRES),
                ("kerb_height_maximum_mm", _MILLIMETRES),
                REASON,
            ),
            entry_check=_ordered(
                ("lanes_minimum", "lanes_maximum"),
                ("lane_width_minimum_mm", "lane_width_maximum_mm"),
                ("footway_width_minimum_mm", "footway_width_maximum_mm"),
                ("speed_limit_minimum_mm_s", "speed_limit_maximum_mm_s"),
                ("kerb_height_minimum_mm", "kerb_height_maximum_mm"),
            ),
        ),
        CatalogSchema(
            "street-name",
            1,
            (("text", text_field), ("hierarchies", sorted_key_list_field), REASON),
        ),
        CatalogSchema(
            "tree-species",
            2,
            (
                ("scientific_name", text_field),
                ("common_name", text_field),
                ("census_count", integer_field(1, 100_000_000)),
                REASON,
            ),
        ),
        CatalogSchema(
            "typology",
            2,
            (
                ("label", text_field),
                ("storeys_minimum", integer_field(1, 120)),
                ("storeys_maximum", integer_field(1, 120)),
                ("frontage_minimum_mm", _MILLIMETRES),
                ("frontage_maximum_mm", _MILLIMETRES),
                ("attachment", choice_field(("terraced", "semi_detached", "detached"))),
                ("ground_floor_uses", sorted_key_list_field),
                ("upper_floor_uses", sorted_key_list_field),
                ("eras", sorted_key_list_field),
                ("roof_families", sorted_key_list_field),
                REASON,
            ),
            entry_check=_ordered(
                ("storeys_minimum", "storeys_maximum"),
                ("frontage_minimum_mm", "frontage_maximum_mm"),
            ),
        ),
        CatalogSchema(
            "use-class",
            1,
            (
                ("label", text_field),
                (
                    "category",
                    choice_field(
                        ("retail", "food_service", "office", "civic", "residential", "workshop")
                    ),
                ),
                ("signage", choice_field(("required", "none"))),
                REASON,
            ),
        ),
    )


CITY_CATALOG_IDS: Final = tuple(
    schema.catalog_id for schema in city_catalog_schemas(texture_sets={})
)


def entry_fields(catalog: Catalog, key: str) -> dict[str, FieldValue]:
    for entry in catalog.entries:
        if entry.key == key:
            return dict(entry.values)
    raise CatalogError(f"{catalog.catalog_id} has no entry {key!r}")


def _by_id(catalogs: Sequence[Catalog]) -> dict[str, Catalog]:
    return {catalog.catalog_id: catalog for catalog in catalogs}


def _require_keys(where: str, keys: object, catalog: Catalog) -> None:
    known = set(catalog.keys())
    for key in keys:  # type: ignore[union-attr]
        if key not in known:
            raise CatalogError(f"{where} names {key!r}, which is not a key of {catalog.catalog_id}")


def check_city_catalogs(catalogs: Sequence[Catalog]) -> None:
    """Every reference from one city catalog into another resolves, and means what it says."""
    by_id = _by_id(catalogs)
    materials = by_id["material"]
    wall_materials = {
        entry.key for entry in materials.entries if "wall" in dict(entry.values)["surfaces"]
    }
    for entry in by_id["era"].entries:
        values = dict(entry.values)
        where = f"era {entry.key}"
        _require_keys(f"{where} wall_materials", values["wall_materials"], materials)
        for key in values["wall_materials"]:  # type: ignore[union-attr]
            if key not in wall_materials:
                raise CatalogError(f"{where}: material {key!r} does not dress a wall")
        _require_keys(f"{where} roof_families", values["roof_families"], by_id["roof-family"])
    for entry in by_id["typology"].entries:
        values = dict(entry.values)
        where = f"typology {entry.key}"
        _require_keys(f"{where} ground_floor_uses", values["ground_floor_uses"], by_id["use-class"])
        _require_keys(f"{where} upper_floor_uses", values["upper_floor_uses"], by_id["use-class"])
        _require_keys(f"{where} eras", values["eras"], by_id["era"])
        _require_keys(f"{where} roof_families", values["roof_families"], by_id["roof-family"])
    signed = {
        entry.key
        for entry in by_id["use-class"].entries
        if dict(entry.values)["signage"] == "required"
    }
    lexicon_classes = set()
    for entry in by_id["signage-lexicon"].entries:
        use_class = dict(entry.values)["use_class"]
        if use_class not in signed:
            raise CatalogError(f"sign {entry.key} names {use_class!r}, which takes no sign")
        lexicon_classes.add(use_class)
    if signed - lexicon_classes:
        raise CatalogError(
            f"use classes with no sign in the lexicon: {sorted(signed - lexicon_classes)}"
        )
    for entry in by_id["fitout"].entries:
        _require_keys(
            f"fitout {entry.key} use_classes",
            dict(entry.values)["use_classes"],
            by_id["use-class"],
        )
    for entry in by_id["street-name"].entries:
        _require_keys(
            f"street name {entry.key} hierarchies",
            dict(entry.values)["hierarchies"],
            by_id["street-hierarchy"],
        )


def load_city_catalogs(
    directory: Path = CATALOG_DIRECTORY,
    *,
    texture_sets: Mapping[str, TextureSet] | None = None,
) -> tuple[Catalog, ...]:
    """Every city catalog, each checked against its schema and all of them against each other.

    ``texture_sets`` defaults to the published manifest, read strictly: a missing or malformed
    manifest is refused, never read as empty.
    """
    published = read_texture_manifest() if texture_sets is None else texture_sets
    catalogs = load_catalog_directory(directory, city_catalog_schemas(texture_sets=published))
    check_city_catalogs(catalogs)
    return catalogs


def city_vocabularies(catalogs: Sequence[Catalog]) -> dict[str, frozenset[str]]:
    """Every catalog's keys, by catalog id: what a record's key fields may name."""
    return {catalog.catalog_id: frozenset(catalog.keys()) for catalog in catalogs}
