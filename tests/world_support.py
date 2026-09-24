"""Registering the worlds a test writes into, the way the product's creation paths do.

Every world table names a registered world (migration 0099), so a test that writes structure,
style, authored or interaction rows for a world registers it first, exactly as an authored starter
or a composition of personal sources does in the product. Not loaded by the application.

``FIXTURE_WORLD_ID`` is the world the synthetic structural candidates in
``world_structure_fixtures`` are written for. It is fixture data: the product resolves worlds
from the registry and never names this id, which ``tests/test_world_identity_inventory.py``
holds, and ``tests/test_two_worlds_stay_apart.py`` runs two worlds with minted ids so nothing
passes because of this value.
"""

from __future__ import annotations

import uuid
from typing import Final

from exulanica.world.worlds import PERSONAL_SOURCE, register_world

__all__ = ["FIXTURE_WORLD_ID", "registered_world"]

#: The world id the synthetic candidates and older fixtures are written for.
FIXTURE_WORLD_ID: Final = "atlas:default"


def registered_world(
    connection,
    workspace_id: uuid.UUID,
    world_id: str = FIXTURE_WORLD_ID,
    *,
    kind: str = PERSONAL_SOURCE,
    actor: uuid.UUID | None = None,
) -> str:
    """Register ``world_id`` in the workspace (or find it registered) and return it."""
    return register_world(
        connection,
        workspace_id,
        world_id=world_id,
        kind=kind,
        created_by=actor or uuid.uuid4(),
        reason="test fixture",
    ).world_id
