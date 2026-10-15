"""Authored fixture vocabulary for drafting, independent of saved-world replay and assets."""

from __future__ import annotations

import functools
import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from exulanica.grammar.catalogs import CatalogSchema, integer_field, load_catalog, text_field
from exulanica.grammar.errors import CatalogError
from exulanica.world.kinds.catalogs import CATALOG_DIRECTORY, load_kind_catalogs

CATALOG_PATH = CATALOG_DIRECTORY / "thing-leaf.v1.json"


@dataclass(frozen=True, slots=True)
class ThingLeaf:
    role: str
    words: str
    box_mm: tuple[int, int, int]


@dataclass(frozen=True, slots=True)
class ThingLeaves:
    sha256: str
    entries: Mapping[str, ThingLeaf]


@functools.cache
def load_thing_leaves(path: Path | None = None, *, version: int = 1) -> ThingLeaves:
    """Read fixture leaves in the house catalog envelope, holding boxes to kind bounds."""
    if version not in (1, 2):
        raise CatalogError(f"unknown thing-leaf version {version}")
    path = CATALOG_DIRECTORY / f"thing-leaf.v{version}.json" if path is None else path
    catalogs = load_kind_catalogs(bounds_version=version)
    size = integer_field(*catalogs.bound("fixture_size_mm"))
    height = integer_field(
        *catalogs.bound("fixture_size_mm" if version == 1 else "fixture_height_mm")
    )
    catalog = load_catalog(
        path,
        CatalogSchema(
            "thing-leaf",
            version,
            (
                ("family", text_field),
                ("words", text_field),
                ("width_mm", size),
                ("depth_mm", size),
                ("height_mm", height),
                ("reason", text_field),
            ),
        ),
    )
    # The document reader's fixture families are the authority for admissible leaves.
    from exulanica.world.kinds.parts import _FORM_LOOKS

    entries = {}
    for entry in catalog.entries:
        values = dict(entry.values)
        family = str(values["family"])
        if family not in _FORM_LOOKS["fixture"]:
            raise CatalogError(f"{entry.key}: {family!r} is not a fixture look family")
        role = f"{family}.{entry.key}"
        entries[role] = ThingLeaf(
            role,
            str(values["words"]),
            (int(values["width_mm"]), int(values["depth_mm"]), int(values["height_mm"])),
        )
    return ThingLeaves(hashlib.sha256(path.read_bytes()).hexdigest(), MappingProxyType(entries))
