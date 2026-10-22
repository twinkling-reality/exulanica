"""The rules a world's landscape is made by, named in its receipt so it rebuilds the same.

A world made from a landscape keeps its landscape document; its volumes are realized again from it
whenever they are asked for. The receipt names :func:`landscape_rules`: the landscape rules
version, which stands for the composition (:mod:`exulanica.grammar.landscape.compose`: each placed
volume's seed, its levels and its tops), the volume rules it realizes volumes by
(:func:`~exulanica.grammar.volumes.volume_rules`), and the landscape catalog's digest. The land is
named by its own land rules beside them. Rules this code does not serve are refused by name
(``landscape_rules_changed``); a landscape is never realized as other geometry.

A change to the composition is a new version; a change to the volume rules or the catalog is a new
version naming them. The tests pin each served version. Version 2 is version 1 realizing its
volumes by volume rules 2, whose strata may vary the beds. Version 3 is version 1 realizing its
volumes by volume rules 3, whose volumes may state a top land. Version 4 is version 3 reading
landscape catalog version 2, under which a landscape may state a site on a placed volume's top; a
landscape without one is version 3's. Version 5 is version 4 realizing its volumes by volume
rules 4, whose top land is graded by land rules 7, so a site on a top eases its banks at their crest
and toe. Version 6 is version 5 with the ground below a site on a volume's top realized under the
landscape's own seed, from its land's digest alone, where earlier versions realize it under the
world's: every world made on one landscape stands over the same ground below, realized once.
"""

from __future__ import annotations

import functools
from collections.abc import Mapping
from typing import Any, Final

from exulanica.grammar.catalogs import catalog_digest, load_catalog
from exulanica.grammar.landscape.catalog import CATALOG_DIRECTORY, landscape_schema
from exulanica.grammar.landscape.document import LandscapeRefused
from exulanica.grammar.volumes import volume_rules

__all__ = [
    "LANDSCAPE_RULES_VERSION",
    "OWN_GROUND_SEED_FROM",
    "SERVED_LANDSCAPE_RULES",
    "check_landscape_rules",
    "landscape_rules",
    "served_landscape_rules",
]

#: The rules new landscapes are made by.
LANDSCAPE_RULES_VERSION: Final = 6
#: Every rules version this code makes landscapes by: the landscape catalog version it reads and
#: the volume rules version it realizes volumes by.
SERVED_LANDSCAPE_RULES: Final = {1: (1, 1), 2: (1, 2), 3: (1, 3), 4: (2, 3), 5: (2, 4), 6: (2, 4)}
#: The first rules version whose ground below a site on a volume's top is realized under the
#: landscape's own seed rather than its world's.
OWN_GROUND_SEED_FROM: Final = 6


@functools.cache
def _catalog_digest(version: int) -> str:
    return catalog_digest(
        [
            load_catalog(
                CATALOG_DIRECTORY.joinpath(f"landscape-value.v{version}.json"),
                landscape_schema(version),
            )
        ]
    )


def landscape_rules(version: int | None = None) -> dict[str, Any]:
    """The rules ``version`` (the newest unless one is named). A new mapping each time, since a
    receipt keeps it."""
    named = LANDSCAPE_RULES_VERSION if version is None else version
    catalog_version, volumes_version = SERVED_LANDSCAPE_RULES[named]
    return {
        "version": named,
        "volume_rules": volume_rules(volumes_version),
        "catalogs": {f"landscape-value.v{catalog_version}": _catalog_digest(catalog_version)},
    }


def _said(rules: object) -> str:
    if not isinstance(rules, Mapping):
        return "no landscape rules"
    return f"landscape rules version {rules.get('version')}"


def check_landscape_rules(named: object) -> int:
    """The landscape catalog version a landscape made by the rules ``named`` is read against, or a
    refusal of rules this code does not serve, saying both."""
    return SERVED_LANDSCAPE_RULES[served_landscape_rules(named)][0]


def served_landscape_rules(named: object) -> int:
    """Which served version the rules ``named`` are (:data:`SERVED_LANDSCAPE_RULES` gives its
    landscape catalog and volume rules), or a refusal of rules this code does not serve, saying
    both."""
    for version in SERVED_LANDSCAPE_RULES:
        if named == landscape_rules(version):
            return version
    served = ", ".join(str(version) for version in SERVED_LANDSCAPE_RULES)
    raise LandscapeRefused(
        f"this world's landscape was made by {_said(named)}; this server makes landscapes by "
        f"{_said(landscape_rules())} and reads landscapes made by versions {served}",
        code="landscape_rules_changed",
    )
