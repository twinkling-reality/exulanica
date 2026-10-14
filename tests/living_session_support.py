"""Opening a living session for a test that asks a world's chosen models.

The host asks a model for a society's beings only while it has an open living session
(``docs/synthetic-society-contract.md#living-sessions``). A test whose subject is what a model is
asked, or what its answer does, opens one where it chooses the model, the way the session route
does: through the society's playback controls, with the runtime's input authority, at the
society's current tick and digest.
"""

from __future__ import annotations

import uuid
from typing import Any

from exulanica.selection.validation import Session
from exulanica.world.society_control_repository import SocietyControlRepository

#: Limits large enough that no test's asking reaches one.
LIMITS: dict[str, Any] = {
    "wall_seconds": 24 * 60 * 60,
    "minutes": 1440,
    "decisions": 10_000,
    "usd": "100",
    "calls": 10_000,
}


def open_living_session(
    database: Any,
    runtime: Any,
    workspace_id: uuid.UUID,
    world_id: str,
    version_id: uuid.UUID,
    actor: uuid.UUID,
    *,
    limits: dict[str, Any] | None = None,
) -> dict:
    """Open a living session over the society of ``version_id`` and answer it, or answer the one
    already open.

    A society the test left playing is paused first, as a session opens only on a paused one, and
    plays again at its speed once the session opens it.
    """
    with database.session(workspace_id) as connection:
        controls = SocietyControlRepository(
            connection,
            workspace_id,
            world_id=world_id,
            input_authorizer=lambda who, document: runtime.authorize(
                connection, Session(workspace_id=workspace_id, actor=who), document
            ),
        )
        held = [one for one in controls.sessions(version_id) if one["state"] == "open"]
        if held:
            return held[0]
        read = controls.read(version_id)
        if read["mode"] == "playing":
            controls.configure(
                version_id,
                actor=actor,
                base_revision=read["revision"],
                mode="paused",
                speed=read["speed"],
            )
            read = controls.read(version_id)
        return controls.open_session(
            version_id,
            actor=actor,
            request_id=uuid.uuid4(),
            base_revision=read["revision"],
            base_tick=read["current_tick"],
            base_state_sha256=read["state_sha256"],
            limits=LIMITS if limits is None else limits,
            speed=read["speed"],
        )


def open_for_saved_world(services: Any, world: dict) -> dict:
    """:func:`open_living_session` over a saved world's society, as its owner, with the running
    application's services."""
    binding = world["binding"]
    return open_living_session(
        services.database,
        services.society_runtime,
        world["workspace"],
        binding.world_id,
        binding.version_id,
        world["session"].actor,
    )
