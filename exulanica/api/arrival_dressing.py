"""An arrival world dressed with its scene, for a visitor's copy and for the installation's own.

The arrival catalog (:mod:`exulanica.world.arrival_worlds`) may name a scene for an arrival world.
:func:`dress_arrival` lays it into a workspace's copy with the scene dressing a server runs
(:func:`~exulanica.api.scene_dressing.dress_saved_world`): the things placed through the things
route's edit, the version's society made on the scene's engine as the society route makes it, and
each being's mind recorded as the owner's choice, so a guest's own allowance pays for those minds
and the routine decides once it is spent. Asking again finishes a dressing stopped part way and
places or records nothing twice.

Where no scene is laid, because the world names none or the host does not offer its engine, the
copy is not left empty: the arrival version's living society is made on the engine the arrival list
names for it (``exulanica-society/v5`` unless it names another) through
:func:`~exulanica.api.society_making.make_society`, exactly as ``POST
/world/versions/{version_id}/society`` makes one, in the arrival's own region. Asking again reads
the society back and makes nothing new.

What did not happen is answered as the guest entry's ``incomplete`` steps (``{"step": "scene",
"code": ...}``), never raised, so the world stands with what was laid:

*   a host that does not offer the scene's engine (``society_engine_not_offered``) is told before
    anything is placed, so a world is never left holding beings that no society seats, and the
    copy lives on its living engine instead;
*   a living society refused comes back as ``{"step": "society", "code": ...}``, by the code the
    society routes answer with;
*   a refusal of the dressing itself comes back by its code (``scene_ground_mismatch``,
    ``thing_limit_reached``, ...), with what was placed before it kept;
*   a society refused after the things are placed comes back by its code, the things kept;
*   a mind refused for one being comes back by its code with that being's ``thing_id``; the
    routine decides for it.

It checks no permission. The caller has found the actor allowed to change the world and to cause
what its minds spend (``world.write`` and ``model.invoke`` on the workspace): a guest's own
workspace holds both, and the installation's command runs as the runtime role in the operator's.

``python -m exulanica.api.arrival_dressing prepare --workspace <uuid>`` is the installation's step
(``deploy/public/public.sh prepare-towns``): it makes every arrival world in the operator's
workspace, as ``exulanica-arrival-worlds prepare`` does, so the tile worker bakes them once for
every later copy, then dresses each one naming a scene. It exits 1 when a dressing is incomplete,
so a host that cannot dress what a visitor's copy will be dressed with says so before any visitor
arrives; a host that does not offer the scene's engine is the operator's stated choice, printed and
not counted, and its visitors' copies open undressed.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import uuid
from collections.abc import Sequence
from typing import Any, Final

from exulanica.api.scene_dressing import dress_saved_world
from exulanica.api.society_making import (
    SOCIETY_ENGINE_NOT_OFFERED,
    SocietyHooks,
    make_society,
    society_refusal,
)
from exulanica.world.arrival_worlds import ArrivalWorld
from exulanica.world.saved_entries import SavedWorldEntryRepository
from exulanica.world.scenes import SceneRefused, scene_arrival
from exulanica.world.society_engines import society_engine

__all__ = ["INSTALLATION_ACTOR", "dress_arrival", "main"]

_LOG = logging.getLogger(__name__)

#: The installation's own actor: its arrival worlds are made and dressed by no person. The same
#: one ``exulanica-arrival-worlds prepare`` makes them as.
INSTALLATION_ACTOR: Final = uuid.uuid5(uuid.NAMESPACE_URL, "exulanica:installation:arrival-worlds")


def dress_arrival(
    hooks: SocietyHooks, connection: Any, session: Any, entry_id: uuid.UUID, world: ArrivalWorld
) -> list[dict[str, str]]:
    """Lay ``world``'s scene into the saved world ``entry_id`` names, in ``session``'s workspace and
    as its actor, or, where no scene is laid, make its living society; and answer what did not
    happen as ``incomplete`` steps, an empty list when everything was done. ``connection`` is the
    workspace's, idle."""
    scene = world.scene
    if scene is None:
        return _live(hooks, connection, session, entry_id, world)
    if (
        society_engine(scene.document["engine"]).state_family == "things"
        and not hooks.services.societies_of_things
    ):
        return [
            {"step": "scene", "code": SOCIETY_ENGINE_NOT_OFFERED},
            *_live(hooks, connection, session, entry_id, world),
        ]
    try:
        dressed = dress_saved_world(hooks, connection, session, entry_id, scene)
    except SceneRefused as refused:
        _LOG.warning("an arrival world was not dressed: %s", refused.code)
        return [{"step": "scene", "code": refused.code}]
    problems: list[dict[str, str]] = []
    if dressed.society["refused"] is not None:
        problems.append({"step": "scene", "code": str(dressed.society["refused"])})
    problems.extend(
        {"step": "scene", "code": str(mind["refused"]), "thing_id": str(mind["thing_id"])}
        for mind in dressed.minds
        if mind["refused"] is not None
    )
    return problems


def _live(
    hooks: SocietyHooks, connection: Any, session: Any, entry_id: uuid.UUID, world: ArrivalWorld
) -> list[dict[str, str]]:
    """The arrival version's living society on ``world.society_engine``, made as the society route
    makes one, in the region the world's arrival names; or the step that refused it."""
    try:
        entry = SavedWorldEntryRepository(
            connection, session.workspace_id, hooks.services.store
        ).entry(entry_id)
        make_society(
            hooks,
            connection,
            session,
            entry.world_id,
            entry.authored_version_id,
            region_id=scene_arrival(entry).region_id,
            profile=world.society_engine,
        )
    except SceneRefused as refused:
        return [{"step": "society", "code": refused.code}]
    except Exception as exc:
        refusal = society_refusal(exc)
        if refusal is None:
            raise
        _LOG.warning("an arrival world's society was not made: %s", refusal.code)
        return [{"step": "society", "code": refusal.code}]
    return []


def _hooks(services: Any) -> SocietyHooks:
    """The hooks an application built on ``services`` holds (:meth:`SocietyHooks.of_app`), for a
    command that runs without one."""
    runtime = services.society_runtime
    return SocietyHooks(
        services=services,
        authored_edit=None if runtime is None else runtime.authored_edit,
        input_authorizer=None if runtime is None else runtime.authorize,
        initial_input=None if runtime is None else runtime.initial_input,
    )


def main(argv: Sequence[str] | None = None, *, stream: Any = None) -> int:
    """``python -m exulanica.api.arrival_dressing prepare --workspace <uuid>``: make every arrival
    world in the installation's own workspace as the runtime role, dress each one naming a scene,
    and print each world's tiles and states and what its dressing left incomplete. Exits 1 when
    anything other than the host not offering the scene's engine is incomplete."""
    from exulanica.api.services import build_services
    from exulanica.db.roles import assert_runtime_role
    from exulanica.selection.validation import Session
    from exulanica.world.arrival_worlds import load_arrival_worlds, make_arrival_world
    from exulanica.world.generated_worlds import generated_tiles
    from exulanica.world.saved_entries import SavedWorldEntryRepository

    parser = argparse.ArgumentParser(
        prog="python -m exulanica.api.arrival_dressing", description=main.__doc__
    )
    parser.add_argument("command", choices=("prepare",))
    parser.add_argument("--workspace", type=uuid.UUID, required=True)
    args = parser.parse_args(argv)
    output = stream or sys.stdout
    worlds = load_arrival_worlds()
    services = build_services(spending_label="arrival-dressing")
    database = services.database
    with database.unscoped() as connection:
        assert_runtime_role(connection)
    hooks = _hooks(services)
    session = Session(workspace_id=args.workspace, actor=INSTALLATION_ACTOR)
    incomplete = False
    for world in worlds:
        with database.session(args.workspace) as connection:
            repository = SavedWorldEntryRepository(connection, args.workspace, services.store)
            entry = make_arrival_world(
                repository, world, created_by=INSTALLATION_ACTOR, require_baked=False
            )
        with database.session(args.workspace) as connection:
            problems = dress_arrival(hooks, connection, session, entry.entry_id, world)
            tiles = generated_tiles(
                connection, args.workspace, world.world_id, entry.source_snapshot_id
            )
        incomplete = incomplete or any(
            problem["code"] != SOCIETY_ENGINE_NOT_OFFERED for problem in problems
        )
        print(
            json.dumps(
                {
                    "key": world.key,
                    "world_id": world.world_id,
                    "tiles": [[t.tile_x, t.tile_y, t.state] for t in tiles],
                    "scene": None if world.scene is None else world.scene.reference(),
                    "incomplete": problems,
                }
            ),
            file=output,
        )
    return 1 if incomplete else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
