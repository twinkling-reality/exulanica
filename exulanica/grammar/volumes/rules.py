"""The rules a world's volumes are made by, named in its receipt so they rebuild the same.

A volume is kept as its document and realized again from it whenever it is asked for. The same
document under other rules would be other rock, so a receipt also names the rules that made it,
within the rules of the landscape the volume is placed in:
:data:`VOLUME_RULES_VERSION`, which stands for the field (:mod:`exulanica.grammar.volumes.field`,
with its turns and noise), the chunk realizer (:mod:`exulanica.grammar.volumes.realize`), the
extraction of walkable tops (:mod:`exulanica.grammar.volumes.sheets`), and the digest of each
catalog that shapes a volume (its shapes and its values). Rules a server does not serve are refused
by name; they are never realized as other geometry.

A change to the field, the realizer or the extraction that moves any value, vertex or top is a new
version, and a change to a catalog is a new catalog version (``volume-value.v2.json``), never an
edit of a shipped one: the tests pin both, and each served version's golden field, chunks and tops.
New volumes name :data:`VOLUME_RULES_VERSION`.

Version 1 reads the version 1 catalogs. Version 2 reads the version 2 catalogs, whose strata may
vary the beds; a version 2 volume that states none of that variation is version 1's rock, and a
world made by version 1 is realized by version 1 and names it in every chunk and top.
"""

from __future__ import annotations

import functools
from collections.abc import Mapping
from typing import Any, Final

from exulanica.grammar.catalogs import catalog_digest, load_catalog
from exulanica.grammar.volumes.catalog import CATALOG_DIRECTORY, shape_schema, value_schema
from exulanica.grammar.volumes.document import VolumeRefused

__all__ = [
    "SERVED_VOLUME_RULES",
    "VOLUME_RULES_VERSION",
    "check_volume_rules",
    "rules_reading",
    "volume_rules",
]

#: The rules new volumes are made by. A change to the field that moves a value is a new version.
VOLUME_RULES_VERSION: Final = 2
#: Every rules version this code makes volumes by, and the volume catalog version each reads.
SERVED_VOLUME_RULES: Final = {1: 1, 2: 2}


@functools.cache
def _catalog_digests(version: int) -> tuple[tuple[str, str], ...]:
    """Each catalog that shapes a volume at ``version``, by the name a receipt gives it, and its
    digest."""
    shaping = (("shape", shape_schema(version)), ("value", value_schema(version)))
    return tuple(
        (
            f"volume-{part}.v{version}",
            catalog_digest(
                [load_catalog(CATALOG_DIRECTORY.joinpath(f"volume-{part}.v{version}.json"), schema)]
            ),
        )
        for part, schema in shaping
    )


def volume_rules(version: int | None = None) -> dict[str, Any]:
    """The rules ``version`` (the newest unless one is named): its number and each shaping
    catalog's digest. A new mapping each time, since a receipt keeps it."""
    named = VOLUME_RULES_VERSION if version is None else version
    return {"version": named, "catalogs": dict(_catalog_digests(SERVED_VOLUME_RULES[named]))}


def rules_reading(catalog_version: int) -> int:
    """The newest rules version that reads volumes of ``catalog_version``: the rules a volume is
    realized by when no world's rules name them."""
    served = [rules for rules, catalog in SERVED_VOLUME_RULES.items() if catalog == catalog_version]
    if not served:
        raise VolumeRefused(
            f"no volume rules this server serves read catalog version {catalog_version}",
            code="volume_rules_changed",
        )
    return max(served)


def _said(rules: object) -> str:
    if not isinstance(rules, Mapping):
        return "no volume rules"
    catalogs = rules.get("catalogs")
    named = (
        ", ".join(f"{name} {str(digest)[:12]}" for name, digest in sorted(catalogs.items()))
        if isinstance(catalogs, Mapping)
        else "no catalogs"
    )
    return f"volume rules version {rules.get('version')} ({named})"


def check_volume_rules(named: object) -> int:
    """The volume catalog version volumes made by the rules ``named`` are read against, or a
    refusal of rules this code does not serve, saying both."""
    for version, catalog_version in SERVED_VOLUME_RULES.items():
        if named == volume_rules(version):
            return catalog_version
    served = ", ".join(str(version) for version in SERVED_VOLUME_RULES)
    raise VolumeRefused(
        f"these volumes were made by {_said(named)}; this server makes volumes by "
        f"{_said(volume_rules())} and reads volumes made by versions {served}",
        code="volume_rules_changed",
    )
