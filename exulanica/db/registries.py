"""The registry tables: reviewed vocabularies that migrations fill and no workspace owns.

Each is a global table a migration inserts reviewed rows into: the predicate vocabulary, the
interaction and style capability registries, the art profiles, the object behaviours and the
pinned asset and texture catalogs. No row carries a workspace, a runtime process reads them and
never writes them, and a new entry is a new migration.

Three places act on that one fact, and each derives its list from :data:`REGISTRY_TABLES`:

*   ``READ_ONLY_TABLES`` in :mod:`exulanica.db.roles`: provisioning revokes the runtime roles'
    writes on them.
*   ``GLOBAL_TABLES`` in :mod:`exulanica.orchestration.judge_seed`: a workspace seed carries a
    digest of them rather than their rows, because the destination's migrations recreate them.
*   ``_PRESERVED_TABLES`` in ``tests/conftest.py``: the per-test truncation leaves them alone,
    because emptying one empties a vocabulary every later insert is checked against.

Each of those adds tables of its own, named beside it with its reason. A registry table named
here reaches all three, so a migration that adds one edits this mapping and nothing else.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

__all__ = ["REGISTRY_TABLES"]

#: Every registry table, with what it holds.
REGISTRY_TABLES: Final[Mapping[str, str]] = {
    "interaction_capability_registry": "migration-provided interaction vocabulary",
    "predicate": "migration-provided predicate vocabulary",
    "world_art_profile_module": "migration-provided reviewed art profile",
    "world_art_profile_parameter": "migration-provided reviewed art profile",
    "world_art_profile_registry": "migration-provided reviewed art profile",
    "world_object_behaviour_registry": "migration-provided reviewed object behaviours",
    "world_reviewed_asset": "migration-provided reviewed object assets",
    "world_style_capability_registry": "migration-provided style capability vocabulary",
    "world_style_module_capability": "migration-provided style capability vocabulary",
    "world_style_module_registry": "migration-provided style capability vocabulary",
    "world_texture_set": "migration-provided reviewed texture set pins",
    "world_texture_set_class": "migration-provided reviewed texture set classes",
}
