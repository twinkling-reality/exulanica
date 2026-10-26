"""A showcase world's copy brought to life as the made world was: its people and the cast's models.

:mod:`exulanica.world.showcase_worlds` makes the world; this lays what its document says of how the
made world lived, through the paths a person's own choices take, in the copy's workspace and as
its actor:

1.  the version's society, made on the document's engine in the region the world's arrival names,
    exactly as ``POST /world/versions/{version_id}/society`` makes one
    (:func:`~exulanica.api.society_making.make_society`), and opened awake;
2.  each member of the cast given its open model, recorded as the world owner's choice for the
    person at that place in the society (``ordinal``), so the copy's own allowance pays for what
    those minds decide and the routine decides once it is spent.

It runs only for a copy just made: a copy the workspace already holds is the visitor's own, with
whatever they chose since, and is never dressed again. What did not happen is answered as
``incomplete`` steps, never raised, so the world stands with what was laid: ``{"step":
"society", "code": ...}`` by the code the society routes answer with, and ``{"step": "cast",
"code": ..., "ordinal": n}`` for a person the society does not hold (``person_not_in_this_world``)
or a choice refused by its own code.

It checks no permission. The caller has found the actor allowed to change the world and to cause
what its minds spend (``world.write`` and ``model.invoke``).

``python -m exulanica.api.showcase_dressing prepare --workspace <uuid>`` is the installation's
check: it makes every served showcase world in the operator's workspace, so the tile worker bakes
its tiles once for every later copy, and compares each made world's receipt with the digest its
document names. It exits 1 when one differs, so a host whose code no longer makes a showcase world
says so before any visitor asks for it.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from collections.abc import Sequence
from typing import Any, Final

from exulanica.api.society_making import SocietyHooks, make_society, society_refusal
from exulanica.models.manifest import load_manifest
from exulanica.world.saved_entries import SavedWorldEntryRepository
from exulanica.world.scenes import SceneRefused, scene_arrival
from exulanica.world.showcase_worlds import ShowcaseWorld
from exulanica.world.society_decision_contract import person_role
from exulanica.world.society_model_choice_repository import (
    ModelChoiceRefused,
    SocietyModelChoiceRepository,
)

__all__ = ["CAST_NAMESPACE", "INSTALLATION_ACTOR", "dress_showcase", "main"]

#: The namespace a cast member's recorded choice is keyed under: one key per society and person.
CAST_NAMESPACE: Final = uuid.uuid5(uuid.NAMESPACE_URL, "exulanica:showcase-worlds:cast")
#: How long the installation's check waits for a place to be composed: it holds no request, so
#: twice as long as a draft's job waits for a place on land (``LAND_COMPOSE_SECONDS``).
PREPARE_COMPOSE_SECONDS: Final = 120.0
#: The installation's own actor for its prepared copies, made by no person.
INSTALLATION_ACTOR: Final = uuid.uuid5(uuid.NAMESPACE_URL, "exulanica:installation:showcase-worlds")


def dress_showcase(
    hooks: SocietyHooks, connection: Any, session: Any, entry_id: uuid.UUID, world: ShowcaseWorld
) -> list[dict[str, Any]]:
    """Make the copy's society on ``world.engine`` and record the cast's models; answer what did
    not happen, an empty list when everything was done. ``connection`` is the workspace's, idle."""
    entry = SavedWorldEntryRepository(connection, session.workspace_id, hooks.services.store).entry(
        entry_id
    )
    try:
        made = make_society(
            hooks,
            connection,
            session,
            entry.world_id,
            entry.authored_version_id,
            region_id=scene_arrival(entry).region_id,
            profile=world.engine,
        )
    except SceneRefused as refused:
        return [{"step": "society", "code": refused.code}]
    except Exception as exc:
        refusal = society_refusal(exc)
        if refusal is None:
            raise
        return [{"step": "society", "code": refusal.code}]
    people = {
        person.get("ordinal"): person["id"]
        for person in made["state"]["inhabitants"]
        if person.get("came_by", "populated") == "populated"
    }
    role = person_role()
    manifest = load_manifest()
    contract = role.contract()
    choices = SocietyModelChoiceRepository(
        connection, session.workspace_id, world_id=entry.world_id
    )
    problems: list[dict[str, Any]] = []
    for member in world.cast:
        person = people.get(member.ordinal)
        if person is None:
            problems.append(
                {"step": "cast", "code": "person_not_in_this_world", "ordinal": member.ordinal}
            )
            continue
        try:
            choices.record_choice(
                entry.authored_version_id,
                role,
                request_id=uuid.uuid5(
                    CAST_NAMESPACE, f"{world.sha256}:{made['society_id']}:{member.ordinal}"
                ),
                subjects=[person],
                model=dict(member.model),
                chosen_by=session.actor,
                manifest=manifest,
                contract=contract,
            )
        except ModelChoiceRefused as exc:
            problems.append({"step": "cast", "code": exc.code, "ordinal": member.ordinal})
    return problems


def main(argv: Sequence[str] | None = None, *, stream: Any = None) -> int:
    """``python -m exulanica.api.showcase_dressing prepare --workspace <uuid>``: make every served
    showcase world in the installation's own workspace as the runtime role, dress each one made
    now, and print each world's receipt digest beside its document's. Exits 1 when one differs or
    a dressing is incomplete."""
    from exulanica.api.arrival_dressing import _hooks
    from exulanica.api.services import build_services
    from exulanica.db.roles import assert_runtime_role
    from exulanica.selection.validation import Session
    from exulanica.world.generated_worlds import generation_receipt
    from exulanica.world.showcase_worlds import make_showcase_world, showcase_worlds

    parser = argparse.ArgumentParser(
        prog="python -m exulanica.api.showcase_dressing", description=main.__doc__
    )
    parser.add_argument("command", choices=("prepare",))
    parser.add_argument("--workspace", type=uuid.UUID, required=True)
    args = parser.parse_args(argv)
    output = stream or sys.stdout
    services = build_services(spending_label="showcase-dressing")
    database = services.database
    with database.unscoped() as connection:
        assert_runtime_role(connection)
    hooks = _hooks(services)
    session = Session(workspace_id=args.workspace, actor=INSTALLATION_ACTOR)
    failed = False
    for world in showcase_worlds().values():
        with database.session(args.workspace) as connection:
            repository = SavedWorldEntryRepository(connection, args.workspace, services.store)
            entry, made_now = make_showcase_world(
                repository, world, created_by=INSTALLATION_ACTOR, seconds=PREPARE_COMPOSE_SECONDS
            )
            digest, _receipt = generation_receipt(
                connection, args.workspace, entry.world_id, entry.source_snapshot_id
            )
        problems: list[dict[str, Any]] = []
        if made_now:
            with database.session(args.workspace) as connection:
                problems = dress_showcase(hooks, connection, session, entry.entry_id, world)
        same = digest == world.receipt_sha256
        failed = failed or not same or bool(problems)
        print(
            json.dumps(
                {
                    "key": world.key,
                    "world_id": world.world_id,
                    "receipt_sha256": digest,
                    "same_world": same,
                    "incomplete": problems,
                }
            ),
            file=output,
        )
    return 1 if failed else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
