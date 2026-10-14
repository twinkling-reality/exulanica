"""The rules a world's land is made by, named in the world's receipt so its land rebuilds the same.

A world made on land keeps its land document; its land is realized and graded again from that
document whenever it is asked for. The same document under other rules would be other land, so a
receipt also names the rules that made it: :data:`LAND_RULES_VERSION`, which stands for the
realizer (:mod:`exulanica.grammar.landform.realize`), its grading
(:mod:`exulanica.grammar.landform.grading`) and the grading plan a site's layout asks of its land
(:mod:`exulanica.world.site_land`), and the digest of each catalog that shapes land (the feature
kinds and their values). A world whose receipt names other rules than this code's is refused by
name; it is never drawn as other land.

A change to any of those rules is a new version, and a change to a catalog is a new catalog file
(``landform-value.v2.json``), never an edit of a shipped one: the tests pin both. The land's look
(``landform-surface.v1.json``, colours only) shapes nothing and is not named here.
"""

from __future__ import annotations

import functools
from collections.abc import Mapping
from typing import Any, Final

from exulanica.grammar.catalogs import catalog_digest, load_catalog
from exulanica.grammar.landform.catalog import CATALOG_DIRECTORY, FEATURE_SCHEMA, VALUE_SCHEMA
from exulanica.grammar.landform.document import LandformRefused

__all__ = ["LAND_RULES_VERSION", "check_land_rules", "land_rules"]

#: The realizer, its grading and a site's grading plan as they stand. A change to any of them is
#: a new version.
LAND_RULES_VERSION: Final = 1

#: The catalogs that shape land, by the name a receipt gives them.
_SHAPING_CATALOGS: Final = (
    ("landform-feature.v1", "landform-feature.v1.json", FEATURE_SCHEMA),
    ("landform-value.v1", "landform-value.v1.json", VALUE_SCHEMA),
)


@functools.cache
def _catalog_digests() -> tuple[tuple[str, str], ...]:
    return tuple(
        (name, catalog_digest([load_catalog(CATALOG_DIRECTORY.joinpath(file), schema)]))
        for name, file, schema in _SHAPING_CATALOGS
    )


def land_rules() -> dict[str, Any]:
    """The rules this code makes land by: its version and each shaping catalog's digest. A new
    mapping each time, since a receipt keeps it."""
    return {"version": LAND_RULES_VERSION, "catalogs": dict(_catalog_digests())}


def _said(rules: object) -> str:
    if not isinstance(rules, Mapping):
        return "no land rules"
    catalogs = rules.get("catalogs")
    named = (
        ", ".join(f"{name} {str(digest)[:12]}" for name, digest in sorted(catalogs.items()))
        if isinstance(catalogs, Mapping)
        else "no catalogs"
    )
    return f"land rules version {rules.get('version')} ({named})"


def check_land_rules(named: object) -> None:
    """Refuse land whose receipt names other rules than this code's, saying both."""
    if named != land_rules():
        raise LandformRefused(
            f"this world's land was made by {_said(named)}; this server makes land by "
            f"{_said(land_rules())}",
            code="landform_rules_changed",
        )
