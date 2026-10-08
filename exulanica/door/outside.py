"""Who outside programs decide for in a world version now, as a person reading the world's models
is told.

A society's subject is decided for from outside in one of two ways: it is one of the world's own
people an owner's grant names (``run``: its current choice in the choice record is the grant's
external decider), or a visitor that crossed in through the door (``crossed``: its arrival names its
program, as the society's state records it). :func:`outside_deciders` lists each such subject whose
grant stands, by subject id, with what the grant's view says of its program: the bridge and its
label, who runs it, whether it is an AI, whether it is connected, and what the program declared
itself to be. A subject whose grant ended is not listed: the routine decides for it.

A subject's current choice is one decider, the latest recorded: a model, the routine or a grant's
external decider, so a subject listed here never also runs by a model, and an owner's choice of a
model for it is refused (``decided_from_outside``) until its grant ends.

Read on a connection scoped to the world's workspace; nothing here writes.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any

import psycopg

from exulanica.door.bridges import BridgeDirectory
from exulanica.door.channel import presence_of, presence_window
from exulanica.door.grants import GrantRepository, grant_actor
from exulanica.world.deciders import arrival_deciders

__all__ = ["outside_deciders"]


def outside_deciders(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    *,
    state: Mapping[str, Any],
    choices: Mapping[str, Mapping[str, Any]],
    bridges: BridgeDirectory | None,
) -> list[dict[str, Any]]:
    """Every subject an active door grant decides for now, by subject id: the world's own people a
    grant names (``run``) and the visitors that crossed in (``crossed``)."""
    held: dict[str, tuple[str, uuid.UUID]] = {}
    for subject, choice in choices.items():
        decider = choice["decider"]
        if decider.get("kind") == "external":
            held[subject] = ("run", uuid.UUID(decider["grant_id"]))
    for subject, decider in arrival_deciders(state).items():
        held[subject] = ("crossed", uuid.UUID(decider["grant_id"]))
    views: dict[uuid.UUID, dict[str, Any] | None] = {}
    for _came, grant_id in held.values():
        if grant_id not in views:
            views[grant_id] = _program(connection, workspace_id, grant_id, bridges)
    entries = []
    for subject, (came, grant_id) in sorted(held.items()):
        program = views[grant_id]
        if program is not None:
            entries.append({"subject_id": subject, "came": came, **program})
    return entries


def _program(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    grant_id: uuid.UUID,
    bridges: BridgeDirectory | None,
) -> dict[str, Any] | None:
    """What the grant view says of the program a standing grant opens to, or None once it ended."""
    grants = GrantRepository(connection, workspace_id, grant_actor(grant_id))
    grant = grants.current(grant_id)
    now = grants.now()
    if grant is None or grant.ended(now) is not None:
        return None
    bridge = None if bridges is None else bridges.get(grant.bridge)
    presence = presence_of(connection, workspace_id, grant_id)
    declared = None if presence is None else presence.declared
    return {
        "grant_id": str(grant_id),
        "bridge": grant.bridge,
        "bridge_label": None if bridge is None else bridge.label,
        "run_by": None if bridge is None else bridge.run_by,
        "ai": None if bridge is None else bridge.ai,
        "connected": presence is not None
        and bridge is not None
        and presence.admitted_by(bridge)
        and presence.connected(now, presence_window(bridge)),
        "declared": None
        if declared is None
        else {
            "name": declared["name"],
            "maker": declared["maker"],
            "mind": declared.get("mind"),
        },
    }
