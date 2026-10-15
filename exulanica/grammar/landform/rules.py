"""The rules a world's land is made by, named in the world's receipt so its land rebuilds the same.

A world made on land keeps its land document; its land is realized and graded again from that
document whenever it is asked for. The same document under other rules would be other land, so a
receipt also names the rules that made it: :data:`LAND_RULES_VERSION`, which stands for the
realizer (:mod:`exulanica.grammar.landform.realize`), its grading
(:mod:`exulanica.grammar.landform.grading`) and the grading plan a site's layout asks of its land
(:mod:`exulanica.world.site_land`), and the digest of each catalog that shapes land (the feature
kinds and their values). A world whose receipt names other rules than this code's is refused by
name; it is never drawn as other land.

A change to any of those rules is a new version, and a change to a catalog is a new catalog version
(``landform-value.v2.json``), never an edit of a shipped one: the tests pin both. The land's look
(``landform-surface.v1.json``, colours only) shapes nothing and is not named here.

**Every version this code can make the same land by is served.** The realizer and its grading are
one code for every served version: a later version only adds what an earlier one could not state
(version 2 adds the ``cascade``, version 3 its ``follow`` course), so a document an earlier
version admits is the same land under this code. A receipt's land is read against the catalog
version its rules name, and the tests pin each served version's golden site, so a change that would
move an earlier version's land fails until that version is no longer served. New worlds name
:data:`LAND_RULES_VERSION`.
"""

from __future__ import annotations

import functools
from collections.abc import Mapping
from typing import Any, Final

from exulanica.grammar.catalogs import catalog_digest, load_catalog
from exulanica.grammar.landform.catalog import CATALOG_DIRECTORY, feature_schema, value_schema
from exulanica.grammar.landform.document import LandformRefused

__all__ = ["LAND_RULES_VERSION", "SERVED_LAND_RULES", "check_land_rules", "land_rules"]

#: The rules new land is made by. A change to the realizer, its grading or a site's grading plan
#: that moves land is a new version.
LAND_RULES_VERSION: Final = 3
#: Every rules version this code makes land by, and the landform catalog version each reads.
SERVED_LAND_RULES: Final = {1: 1, 2: 2, 3: 3}


@functools.cache
def _catalog_digests(version: int) -> tuple[tuple[str, str], ...]:
    """Each catalog that shapes land at ``version`` (the feature kinds and their values), by the
    name a receipt gives it, and its digest."""
    shaping = (("feature", feature_schema(version)), ("value", value_schema(version)))
    return tuple(
        (
            f"landform-{part}.v{version}",
            catalog_digest(
                [
                    load_catalog(
                        CATALOG_DIRECTORY.joinpath(f"landform-{part}.v{version}.json"), schema
                    )
                ]
            ),
        )
        for part, schema in shaping
    )


def land_rules(version: int | None = None) -> dict[str, Any]:
    """The rules ``version`` (the newest unless one is named): its number and each shaping
    catalog's digest. A new mapping each time, since a receipt keeps it."""
    named = LAND_RULES_VERSION if version is None else version
    return {"version": named, "catalogs": dict(_catalog_digests(SERVED_LAND_RULES[named]))}


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


def check_land_rules(named: object) -> int:
    """The landform catalog version land made by the rules ``named`` is read against, or a refusal
    of rules this code does not serve, saying both."""
    for version, catalog_version in SERVED_LAND_RULES.items():
        if named == land_rules(version):
            return catalog_version
    served = ", ".join(str(version) for version in SERVED_LAND_RULES)
    raise LandformRefused(
        f"this world's land was made by {_said(named)}; this server makes land by "
        f"{_said(land_rules())} and reads land made by versions {served}",
        code="landform_rules_changed",
    )
