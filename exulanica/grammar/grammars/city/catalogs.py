"""The eight catalogs the city reads, and the entry schema of each.

The files live in ``assets/catalogs`` at the repository root, one per catalog, named
``<catalog_id>.v<version>.json``. Most of them are empty, deliberately. The target architecture
names each catalog but, except for the ground band, does not name its entries, and entries are
art direction for the operator, not a gap to be filled here. ``docs/grammar-package.md`` records
which catalog is empty and why.

Each schema below is as small as the architecture justifies: a key, a licence, and only the
fields the architecture actually specifies. A field is added by the change that first reads it,
with a catalog version bump.

**Material entries must resolve a texture set.** The caller passes the set of published texture
set ids, and there is no default for it. The texture lane owns those ids and has not published
any, so today the only honest argument is an empty set, under which any material entry is
refused. That is the intended behaviour: a material with no texture is a schema error.

The catalog directory is found relative to this source file, so it is present in a checkout and
absent from an installed wheel. Tiles are baked offline from a checkout.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

from exulanica.grammar.catalogs import (
    Catalog,
    CatalogSchema,
    FieldValue,
    integer_field,
    key_list_field,
    load_catalog_directory,
    reference_field,
    text_field,
)
from exulanica.grammar.errors import CatalogError

__all__ = ["CATALOG_DIRECTORY", "city_catalog_schemas", "load_city_catalogs"]

CATALOG_DIRECTORY: Final = Path(__file__).resolve().parents[4].joinpath("assets", "catalogs")

#: A band's top edge, in millimetres above grade. A sanity bound that catches a unit mistake,
#: not a design value; each band's real bounds are its own catalog entry.
_BAND_TOP = integer_field(1, 100_000)


def _band_bounds_ordered(where: str, values: dict[str, FieldValue]) -> None:
    low, high = values["top_minimum_mm"], values["top_maximum_mm"]
    if not isinstance(low, int) or not isinstance(high, int) or low > high:
        raise CatalogError(f"{where}: top_minimum_mm is at most top_maximum_mm")


def city_catalog_schemas(*, texture_set_ids: frozenset[str]) -> tuple[CatalogSchema, ...]:
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
            "material",
            1,
            (
                ("label", text_field),
                ("texture_set_id", reference_field("a texture set", texture_set_ids)),
            ),
        ),
        CatalogSchema("roof-family", 1, (("label", text_field),)),
        CatalogSchema("signage-lexicon", 1, (("text", text_field),)),
        CatalogSchema(
            "street-hierarchy",
            1,
            (("label", text_field), ("rank", integer_field(0, 1000))),
        ),
        CatalogSchema("tree-species", 1, (("scientific_name", text_field),)),
        CatalogSchema("typology", 1, (("label", text_field),)),
    )


def load_city_catalogs(
    directory: Path = CATALOG_DIRECTORY, *, texture_set_ids: frozenset[str]
) -> tuple[Catalog, ...]:
    return load_catalog_directory(directory, city_catalog_schemas(texture_set_ids=texture_set_ids))
