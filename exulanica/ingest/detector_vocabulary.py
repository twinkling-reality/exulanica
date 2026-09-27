"""The words the local open-vocabulary detector may box, as a versioned catalog.

``assets/catalogs/detection/detector-vocabulary.v<n>.json`` holds one entry per word, each with the
reason it is there, in the order the detector is prompted with them. The segmentation stage's
parameters carry the words themselves, so a new version of the vocabulary re-keys every mask made
under it and an unchanged one re-keys nothing. No word may name a person: a test runs the vision
stage's own person filter over it.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path
from typing import Final

from exulanica.grammar.catalogs import CatalogSchema, load_catalog, text_field

__all__ = ["DETECTOR_VOCABULARY_VERSION", "detector_vocabulary"]

CATALOG_ID: Final = "detector-vocabulary"
#: The version the segmentation stage prompts with.
DETECTOR_VOCABULARY_VERSION: Final = 1
DIRECTORY: Final = Path(__file__).resolve().parents[2].joinpath("assets", "catalogs", "detection")


@cache
def detector_vocabulary(version: int = DETECTOR_VOCABULARY_VERSION) -> tuple[str, ...]:
    """The words of one vocabulary version, in the catalog's order."""
    schema = CatalogSchema(CATALOG_ID, version, (("reason", text_field),))
    catalog = load_catalog(DIRECTORY / f"{CATALOG_ID}.v{version}.json", schema)
    return tuple(entry.key for entry in catalog.entries)
