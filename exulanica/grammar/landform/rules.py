"""The rules a world's land is made by, named in the world's receipt so its land rebuilds the same.

A world made on land keeps its land document; its land is realized and graded again from that
document whenever it is asked for. The same document under other rules would be other land, so a
receipt also names the rules that made it: :data:`LAND_RULES_VERSION`, which stands for the realizer
(:mod:`exulanica.grammar.landform.realize`), its grading (:mod:`exulanica.grammar.landform.grading`)
and the grading plan a site's layout asks of its land (:mod:`exulanica.world.site_land`), and the
digest of each catalog that shapes land (the feature kinds and their values, and from version 6 the
figures a grading is held to). A world whose receipt names other rules than this code's is refused
by name; it is never drawn as other land.

A change to any of those rules is a new version, and a change to a catalog is a new catalog version
(``landform-value.v2.json``), never an edit of a shipped one: the tests pin both. The land's look
(``landform-surface.v1.json``, colours only) shapes nothing and is not named here.

**Every version this code can make the same land by is served.** The realizer and its grading are
one code for every served version: a later version only adds what an earlier one could not state
(version 2 adds the ``cascade``, version 3 its ``follow`` course), so a document an earlier version
admits is the same land under this code. Version 4 is the first that states an admitted document
differently: a site's grading plan names each pond by its zone (``zone 1 pond 0``), where earlier
versions name it by its area's number in its zone alone (``pond 0``), and moves no height. Version 5
lists a retaining wall wherever a site's terraces and paths meet at levels a bank cannot join over
one cell, in its grading and in what its drawing states, and moves no height either. Version 6
grades by the figures ``landform-grading.v1.json`` states, today's bank grade and deepest cut and
fill among them, and lets a terrace stand in a retaining wall where its bank would cut or fill past
the deepest it may: a layout that grades within the bound grades the same land as under version 5,
and one that earlier versions refused may grade. Version 7 grades by ``landform-grading.v2.json``,
which adds a bank's ease grade: a bank's first cell off its level ground and the land's first cell
past it step no steeper than the ease, so a bank rounds into the ground above and below it; the
bank grade's cones still bound every cell, so no wall stands where version 6 has none, and cells
more than two cells beyond a bank keep version 6's heights. So a site's grading plan takes the rules
version its receipt names, and such a change applies from its version on. A receipt's land is read
against the catalog version its rules name, and the tests pin each served version's golden site, so
a change that would move an earlier version's land or what its drawing states fails until that
version is no longer served. New worlds name :data:`LAND_RULES_VERSION`.
"""

from __future__ import annotations

import functools
from collections.abc import Mapping
from typing import Any, Final

from exulanica.grammar.catalogs import catalog_digest, load_catalog
from exulanica.grammar.landform.catalog import (
    CATALOG_DIRECTORY,
    feature_schema,
    grading_schema,
    value_schema,
)
from exulanica.grammar.landform.document import LandformRefused

__all__ = [
    "GRADING_OF_LAND_RULES",
    "LAND_RULES_VERSION",
    "SERVED_LAND_RULES",
    "check_land_rules",
    "land_rules",
]

#: The rules new land is made by. A change to the realizer, its grading or a site's grading plan
#: that moves land, or what a site's drawing states of it, is a new version.
LAND_RULES_VERSION: Final = 7
#: Every rules version this code makes land by, and the landform catalog version each reads.
#: Versions 4 to 7 change no feature or value catalog, so they read version 3's.
SERVED_LAND_RULES: Final = {1: 1, 2: 2, 3: 3, 4: 3, 5: 3, 6: 3, 7: 3}
#: The rules versions that grade by a grading catalog, and its version. Earlier versions grade by
#: the figures the grading module states, which version 1 of the catalog repeats.
GRADING_OF_LAND_RULES: Final = {6: 1, 7: 2}


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


@functools.cache
def _grading_digest(version: int) -> tuple[str, str]:
    """The grading catalog at ``version``, by the name a receipt gives it, and its digest."""
    path = CATALOG_DIRECTORY.joinpath(f"landform-grading.v{version}.json")
    return f"landform-grading.v{version}", catalog_digest(
        [load_catalog(path, grading_schema(version))]
    )


def land_rules(version: int | None = None) -> dict[str, Any]:
    """The rules ``version`` (the newest unless one is named): its number and each shaping
    catalog's digest. A new mapping each time, since a receipt keeps it."""
    named = LAND_RULES_VERSION if version is None else version
    catalogs = dict(_catalog_digests(SERVED_LAND_RULES[named]))
    if named in GRADING_OF_LAND_RULES:
        catalogs.update([_grading_digest(GRADING_OF_LAND_RULES[named])])
    return {"version": named, "catalogs": catalogs}


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
