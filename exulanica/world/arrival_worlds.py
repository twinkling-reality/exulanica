"""The worlds a visitor's workspace starts with: a versioned catalog, and the one way to make them.

An installation that lets people in without an operator (the public server) opens each newcomer's
workspace on a living town rather than an empty menu. Making a generated town is fast; baking its
tiles is not (two tessellator runs a tile, off the request), and a town is drawn only once its
tiles are baked. So each arrival world names a **fixed identity** beside its recipe and values: a
generated town's seed is drawn from the recipe and the identity
(:func:`~exulanica.world.composers.seed_candidate`), so every workspace's copy is the same town
with the same tiles, and a tile already stored queues no bake
(:func:`~exulanica.world.generated_worlds.create_generated_authorities`). The installation makes the
arrival worlds once in its own workspace (``exulanica-arrival-worlds prepare``), its tile worker
bakes them, and every later copy opens baked.

The catalog is data: ``arrival-worlds.v1.json`` beside this module, or the file
``EXULANICA_ARRIVAL_WORLDS`` names, so an operator chooses the content without a code change.
Identities are keyed by workspace (migration 0099), so one identity in many workspaces names many
worlds, each its workspace's own.

An arrival world may name a **scene** (``assets/catalogs/scenes``, by key, version and digest): the
things a visitor finds already placed in front of them, the society they live in and the open
model each being's mind is. Making the world here never lays it; the dressing is the HTTP
surface's (:mod:`exulanica.api.arrival_dressing`), which lays it into each copy, the
installation's own included, through the same edit and society paths a person's choices take.
Without a scene an arrival world is made exactly as before.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from exulanica.env import env_get
from exulanica.world.scenes import Scene, SceneRefused, shipped_scene
from exulanica.world.worlds import GENERATED, world_kind

__all__ = [
    "ARRIVAL_WORLDS_PATH",
    "PROFILE",
    "ArrivalWorld",
    "ArrivalWorldNotBaked",
    "ArrivalWorldsInvalid",
    "arrival_tiles_baked",
    "load_arrival_worlds",
    "main",
    "make_arrival_world",
]

PROFILE: Final = "exulanica.arrival-worlds/v1"
ARRIVAL_WORLDS_PATH: Final = Path(__file__).with_name("arrival-worlds.v1.json")


class ArrivalWorldsInvalid(ValueError):
    """The arrival catalog does not say what this module reads, named."""


@dataclass(frozen=True, slots=True)
class ArrivalWorld:
    key: str
    recipe: str
    values: Mapping[str, object] | None
    title: str
    world_id: str
    #: The scene each copy is dressed with, read at the catalog's digest; None for none.
    scene: Scene | None = None


#: The fields a catalog's scene reference holds, and nothing else.
_SCENE_REFERENCE: Final = frozenset({"scene", "version", "sha256"})


def _arrival_scene(key: object, named: object) -> Scene | None:
    """The shipped scene an arrival world's ``scene`` field names, or None when it names none.

    Refused by name: a reference that is not exactly a scene key, an integer version and a digest;
    a scene not shipped at that digest; and one laid out for another ground than a generated
    town's, which no arrival world is."""
    if named is None:
        return None
    if not isinstance(named, dict) or set(named) != _SCENE_REFERENCE:
        raise ArrivalWorldsInvalid(f"{key}: a scene is {{scene, version, sha256}} or null")
    version = named["version"]
    if not isinstance(version, int) or isinstance(version, bool):
        raise ArrivalWorldsInvalid(f"{key}: a scene's version is an integer")
    try:
        scene = shipped_scene(str(named["scene"]), version, str(named["sha256"]))
    except SceneRefused as refused:
        raise ArrivalWorldsInvalid(f"{key}: {refused.code}: {refused.detail}") from refused
    if scene.ground != GENERATED:
        raise ArrivalWorldsInvalid(
            f"{key}: scene {scene.scene} v{scene.version} is laid out for a {scene.ground}, "
            "not a generated town"
        )
    return scene


def load_arrival_worlds(environ: Mapping[str, str] | None = None) -> tuple[ArrivalWorld, ...]:
    """The catalog ``EXULANICA_ARRIVAL_WORLDS`` names, or the shipped one, checked.

    Refused by name: another profile, no world, a repeated key or identity, an identity that is
    not a generated world's, a title outside 1 to 200 characters, or a scene that is not shipped
    at the digest named or not laid out for a generated town (:func:`_arrival_scene`). Whether
    each recipe and its values generate is the recipe gate's and the composer's to refuse, when the
    world is made.
    """
    named = env_get("ARRIVAL_WORLDS", environ)
    path = Path(named) if named else ARRIVAL_WORLDS_PATH
    document: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or document.get("profile") != PROFILE:
        raise ArrivalWorldsInvalid(f"{path} is not an {PROFILE} document")
    entries = document.get("worlds")
    if not isinstance(entries, list) or not entries:
        raise ArrivalWorldsInvalid(f"{path} names no arrival world")
    prefix = world_kind(GENERATED).id_prefix
    worlds: list[ArrivalWorld] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise ArrivalWorldsInvalid("an arrival world is an object")
        values = entry.get("values")
        world_id = str(entry.get("world_id", ""))
        title = str(entry.get("title", ""))
        if values is not None and not isinstance(values, dict):
            raise ArrivalWorldsInvalid(f"{entry.get('key')}: values are an object or null")
        if not world_id.startswith(prefix):
            raise ArrivalWorldsInvalid(f"{entry.get('key')}: {world_id!r} is not {prefix}<uuid>")
        uuid.UUID(world_id.removeprefix(prefix))
        if not 1 <= len(title.strip()) <= 200:
            raise ArrivalWorldsInvalid(f"{entry.get('key')}: a title is 1 to 200 characters")
        worlds.append(
            ArrivalWorld(
                key=str(entry["key"]),
                recipe=str(entry["recipe"]),
                values=values,
                title=title,
                world_id=world_id,
                scene=_arrival_scene(entry.get("key"), entry.get("scene")),
            )
        )
    for field in ("key", "world_id"):
        seen = [getattr(world, field) for world in worlds]
        if len(set(seen)) != len(seen):
            raise ArrivalWorldsInvalid(f"{path} repeats an arrival world's {field}")
    return tuple(worlds)


class ArrivalWorldNotBaked(RuntimeError):
    """An arrival world's tiles are not all baked yet, so a visitor's copy would wait."""


def arrival_tiles_baked(connection: Any, world: ArrivalWorld) -> bool:
    """Whether every tile of ``world`` is stored and servable under the stage this installation
    runs. Composing the world writes nothing; its tiles are read by the digest of their inputs."""
    from exulanica.world.baked_tiles import current_bake
    from exulanica.world.composers import composer_module
    from exulanica.world.generated_worlds import compose_generated_world
    from exulanica.world.world_recipes import town_recipe

    composed = compose_generated_world(town_recipe(world.recipe, world.values), world.world_id)
    composer = composed.receipt["composer"]
    for _tile, inputs in composer_module(composer["key"], composer["version"]).tile_inputs(
        composed.receipt
    ):
        bake = current_bake(connection, inputs)
        if bake is None or not bake.servable:
            return False
    return True


def make_arrival_world(
    repository: Any, world: ArrivalWorld, *, created_by: uuid.UUID, require_baked: bool = True
) -> Any:
    """Make ``world`` in the repository's workspace under its fixed identity, and answer the
    saved entry; the workspace's existing copy when it already holds that identity.

    A visitor's copy is made only once the arrival world's tiles are baked
    (:class:`ArrivalWorldNotBaked` otherwise), so it opens at once rather than waiting; the
    installation's own copy, which is what bakes them, passes ``require_baked=False``.
    ``repository`` is the workspace's
    :class:`~exulanica.world.saved_entries.SavedWorldEntryRepository`.
    """
    for entry in repository.entries():
        if entry.world_id == world.world_id:
            return entry
    if require_baked and not arrival_tiles_baked(repository.connection, world):
        raise ArrivalWorldNotBaked(f"{world.key}'s tiles are not all baked yet")
    return repository.create_generated(
        title=world.title,
        recipe_key=world.recipe,
        created_by=created_by,
        values=world.values,
        fixed_world_id=world.world_id,
    )


def main(argv: Sequence[str] | None = None, *, stream: Any = None) -> int:
    """``exulanica-arrival-worlds check|prepare``.

    ``check`` loads the catalog and composes each world without writing anything, naming each
    world's scene. ``prepare`` makes each world in ``--workspace`` (the installation's own) as the
    runtime role, so the tile worker draining that workspace bakes its tiles once for every later
    copy, and prints each world's tiles and their states; it lays no scene, which the HTTP
    surface's ``python -m exulanica.api.arrival_dressing prepare`` does as well. Both exit 1 when a
    world is refused.
    """
    from exulanica.db.roles import assert_runtime_role
    from exulanica.db.session import Database
    from exulanica.store.configured import content_stores
    from exulanica.world.generated_worlds import compose_generated_world, generated_tiles
    from exulanica.world.saved_entries import SavedWorldEntryRepository
    from exulanica.world.world_recipes import town_recipe

    parser = argparse.ArgumentParser(prog="exulanica-arrival-worlds", description=main.__doc__)
    parser.add_argument("command", choices=("check", "prepare"))
    parser.add_argument("--workspace", type=uuid.UUID, help="the installation's own workspace")
    args = parser.parse_args(argv)
    output = stream or sys.stdout
    worlds = load_arrival_worlds()
    if args.command == "check":
        for world in worlds:
            recipe = town_recipe(world.recipe, world.values)
            composed = compose_generated_world(recipe, world.world_id)
            scene = None if world.scene is None else world.scene.reference()
            print(
                json.dumps({"key": world.key, "tiles": composed.receipt["tiles"], "scene": scene}),
                file=output,
            )
        return 0
    if args.workspace is None:
        parser.error("prepare needs --workspace")
    database = Database.from_env()
    with database.unscoped() as connection:
        assert_runtime_role(connection)
    #: The installation's own actor: its arrival worlds are made by no person.
    actor = uuid.uuid5(uuid.NAMESPACE_URL, "exulanica:installation:arrival-worlds")
    with database.session(args.workspace) as connection:
        repository = SavedWorldEntryRepository(connection, args.workspace, content_stores().blobs)
        for world in worlds:
            entry = make_arrival_world(repository, world, created_by=actor, require_baked=False)
            tiles = generated_tiles(
                connection, args.workspace, world.world_id, entry.source_snapshot_id
            )
            print(
                json.dumps(
                    {
                        "key": world.key,
                        "world_id": world.world_id,
                        "tiles": [[t.tile_x, t.tile_y, t.state] for t in tiles],
                    }
                ),
                file=output,
            )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
