"""The showcase worlds: worlds made from a person's sentence on real models, kept as data so that
any workspace may hold its own copy of one, made again from what the making decided, with no model
call.

A world made from a sentence (``POST /worlds/drafts``) is decided by models once: the tool, the
town's preset and values or the place's kind, the land the words name, the look and the setting.
Everything after that is code: :meth:`~exulanica.world.saved_entries.SavedWorldEntryRepository.
create_generated` and :meth:`~...create_from_kind` give the same world for the same identity, so a
showcase world's document (``assets/catalogs/showcase-worlds/<key>.v<n>.json``, profile
``exulanica.showcase-world/v1``) holds exactly those decisions, with the made world's identity and
its receipt's digest, and every copy is that world: the same streets, buildings and land, drawn in
the same look and setting.

A document also says how the made world lived, as data a copy is dressed with
(:mod:`exulanica.api.showcase_dressing`): the society engine its people live on, and the cast, the
people given an open model, named by their place in the society (``ordinal``). A society's people
are drawn from a seed of the world and its workspace (:func:`~exulanica.world.society.
world_society_seed`), so a copy's people are its own people, not the showcase world's: the cast
gives the same models to the people at the same places. What the made world did (its history) is
its own record and is not copied; a copy records its own as it plays.

The lock (``showcase-worlds.lock.json``) names the one version of each world served, by digest:
a served document never changes, a changed one is a new version, and a file the lock does not name
at its digest is refused. Whether a world's documents still make that world is the installation's
check (``python -m exulanica.api.showcase_dressing prepare``), which makes each once in the
operator's workspace and compares the receipt's digest.
"""

from __future__ import annotations

import functools
import json
import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from exulanica.canonical import canonical_json, sha256_of_canonical
from exulanica.world.models import StylePackBinding
from exulanica.world.society_engines import RetiredSocietyEngine, creatable_engine
from exulanica.world.worlds import GENERATED, world_kind

__all__ = [
    "PROFILE",
    "SHOWCASE_DIRECTORY",
    "CastMember",
    "ShowcaseWorld",
    "ShowcaseWorldsInvalid",
    "make_showcase_world",
    "showcase_world",
    "showcase_worlds",
]

PROFILE: Final = "exulanica.showcase-world/v1"
LOCK_PROFILE: Final = "exulanica.showcase-world-lock/v1"
SHOWCASE_DIRECTORY: Final = (
    Path(__file__).resolve().parents[2] / "assets" / "catalogs" / "showcase-worlds"
)
SHOWCASE_LOCK: Final = SHOWCASE_DIRECTORY / "showcase-worlds.lock.json"
#: How a showcase world is named in an address: lowercase words joined by hyphens.
KEY: Final = re.compile(r"[a-z][a-z0-9-]{0,63}")
_TOP: Final = frozenset(
    {"profile", "key", "version", "title", "sentence", "world", "look", "society", "cast", "made"}
)
_WORLD: Final = frozenset(
    {"world_id", "made_by", "recipe", "values", "kind", "land", "receipt_sha256"}
)
_DIGEST: Final = re.compile(r"[0-9a-f]{64}")


class ShowcaseWorldsInvalid(ValueError):
    """A showcase world's document, or the lock, does not say what this module reads; named."""


@dataclass(frozen=True, slots=True)
class CastMember:
    #: The person's place in the society's people, as its state numbers them.
    ordinal: int
    model: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class ShowcaseWorld:
    key: str
    version: int
    sha256: str
    title: str
    sentence: str
    world_id: str
    #: ``town`` (a preset and its values) or ``place`` (a world kind and its values).
    made_by: str
    recipe: str | None
    values: Mapping[str, Any]
    kind: Any | None
    land: Mapping[str, Any] | None
    receipt_sha256: str
    look: StylePackBinding | None
    engine: str
    cast: tuple[CastMember, ...]


def _refuse(where: str, detail: str) -> ShowcaseWorldsInvalid:
    return ShowcaseWorldsInvalid(f"{where}: {detail}")


def _fields(where: str, raw: object, allowed: frozenset[str]) -> dict[str, Any]:
    if not isinstance(raw, dict) or set(raw) != allowed:
        raise _refuse(where, f"is an object of exactly {sorted(allowed)}")
    return raw


def _look(where: str, raw: object) -> StylePackBinding | None:
    from exulanica.world.style_pack_library import style_pack_library

    if raw is None:
        return None
    look = _fields(where, raw, frozenset({"pack_id", "version", "manifest_sha256", "setting"}))
    if not style_pack_library().holds(look["pack_id"], look["version"], look["manifest_sha256"]):
        raise _refuse(where, f"{look['pack_id']} v{look['version']} is not in this host's library")
    setting = look["setting"]
    if setting is not None and not isinstance(setting, dict):
        raise _refuse(f"{where}.setting", "is the setting the world wears, an object, or null")
    return StylePackBinding(
        look["pack_id"],
        look["version"],
        look["manifest_sha256"],
        # As a stored setting is read back: its canonical JSON (repository._setting_text).
        setting=None if setting is None else canonical_json(setting).decode(),
    )


def read_showcase_world(document: object) -> ShowcaseWorld:
    """A showcase world's document, read and checked; refused by name otherwise."""
    from exulanica.world.kinds.document import read_kind
    from exulanica.world.world_recipes import town_recipe

    raw = _fields("document", document, _TOP)
    if raw["profile"] != PROFILE:
        raise _refuse("profile", f"is {PROFILE}")
    key = raw["key"]
    if not isinstance(key, str) or KEY.fullmatch(key) is None:
        raise _refuse("key", "is lowercase words joined by hyphens, at most 64 characters")
    version = raw["version"]
    if type(version) is not int or version < 1:
        raise _refuse("version", "is a whole number from 1")
    for name in ("title", "sentence"):
        if not isinstance(raw[name], str) or not 1 <= len(raw[name].strip()) <= 200:
            raise _refuse(name, "is 1 to 200 characters")
    world = _fields("world", raw["world"], _WORLD)
    world_id = world["world_id"]
    prefix = world_kind(GENERATED).id_prefix
    if not isinstance(world_id, str) or not world_id.startswith(prefix):
        raise _refuse("world.world_id", f"is {prefix}<uuid>")
    uuid.UUID(world_id.removeprefix(prefix))
    if not isinstance(world["receipt_sha256"], str) or not _DIGEST.fullmatch(
        world["receipt_sha256"]
    ):
        raise _refuse("world.receipt_sha256", "is a SHA-256 digest")
    values = world["values"]
    if not isinstance(values, dict):
        raise _refuse("world.values", "is an object")
    kind = None
    if world["made_by"] == "town":
        if not isinstance(world["recipe"], str) or world["kind"] is not None:
            raise _refuse("world", "a town names its recipe and no kind")
        town_recipe(world["recipe"], values)
    elif world["made_by"] == "place":
        if world["recipe"] is not None or not isinstance(world["kind"], dict):
            raise _refuse("world", "a place names its kind's document and no recipe")
        kind = read_kind(world["kind"])
        # The making job makes a place from its kind's first preset, with any value it asked.
        values = kind.values(kind.presets[0][0], values)
    else:
        raise _refuse("world.made_by", "is town or place")
    land = world["land"]
    if land is not None:
        stated = _fields("world.land", land, frozenset({"recipe", "document", "sha256"}))
        if sha256_of_canonical(stated["document"]).hex() != stated["sha256"]:
            raise _refuse("world.land", "its document is not the one its digest names")
        land = stated["document"]
    society = _fields("society", raw["society"], frozenset({"engine"}))
    try:
        engine = creatable_engine(society["engine"])
    except (RetiredSocietyEngine, ValueError) as refused:
        raise _refuse("society.engine", f"makes no new society: {refused}") from refused
    if not engine.saved_world:
        raise _refuse("society.engine", f"{engine.engine} is not a society over a saved world")
    cast: list[CastMember] = []
    for index, member in enumerate(raw["cast"] if isinstance(raw["cast"], list) else ()):
        stated = _fields(f"cast[{index}]", member, frozenset({"ordinal", "model"}))
        model = _fields(
            f"cast[{index}].model", stated["model"], frozenset({"provider", "model_id"})
        )
        if type(stated["ordinal"]) is not int or stated["ordinal"] < 0:
            raise _refuse(f"cast[{index}].ordinal", "is a whole number from 0")
        cast.append(CastMember(stated["ordinal"], dict(model)))
    if not isinstance(raw["cast"], list) or len({m.ordinal for m in cast}) != len(cast):
        raise _refuse("cast", "is a list naming each person once")
    if not isinstance(raw["made"], dict):
        raise _refuse("made", "is the making's provenance, an object")
    return ShowcaseWorld(
        key=key,
        version=version,
        sha256=sha256_of_canonical(raw).hex(),
        title=raw["title"].strip(),
        sentence=raw["sentence"],
        world_id=world_id,
        made_by=world["made_by"],
        recipe=world["recipe"],
        values=values,
        kind=kind,
        land=land,
        receipt_sha256=world["receipt_sha256"],
        look=_look("look", raw["look"]),
        engine=engine.engine,
        cast=tuple(cast),
    )


def _lock(path: Path) -> dict[str, tuple[int, str]]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or document.get("profile") != LOCK_PROFILE:
        raise _refuse(path.name, f"is a {LOCK_PROFILE} document")
    locked: dict[str, tuple[int, str]] = {}
    for entry in document.get("worlds", ()):
        stated = _fields(path.name, entry, frozenset({"key", "version", "sha256"}))
        if stated["key"] in locked:
            raise _refuse(
                path.name, f"names {stated['key']} twice: one version of a world is served"
            )
        locked[stated["key"]] = (stated["version"], stated["sha256"])
    return locked


@functools.cache
def showcase_worlds(
    directory: Path = SHOWCASE_DIRECTORY, lock: Path = SHOWCASE_LOCK
) -> Mapping[str, ShowcaseWorld]:
    """Every showcase world the lock serves, by key, each read and checked once per process. A
    file named for another world or version than it states is refused, and so is a served version
    whose file is not at the locked digest, and a lock line with no file."""
    locked = _lock(lock)
    served: dict[str, ShowcaseWorld] = {}
    for key, (version, sha256) in sorted(locked.items()):
        path = directory / f"{key}.v{version}.json"
        if not path.is_file():
            raise _refuse(lock.name, f"names {key} v{version}, with no file")
        world = read_showcase_world(json.loads(path.read_text(encoding="utf-8")))
        if (world.key, world.version) != (key, version):
            raise _refuse(path.name, "names the world and version it states")
        if world.sha256 != sha256:
            raise _refuse(path.name, f"is not the document {lock.name} locks")
        served[key] = world
    identities = [world.world_id for world in served.values()]
    if len(set(identities)) != len(identities):
        raise _refuse(lock.name, "serves two worlds of one identity")
    return served


def showcase_world(key: str) -> ShowcaseWorld | None:
    """The served showcase world ``key`` names, or None for a key the lock does not serve."""
    return showcase_worlds().get(key)


def make_showcase_world(
    repository: Any,
    world: ShowcaseWorld,
    *,
    created_by: uuid.UUID,
    compose: Any = None,
    seconds: float | None = None,
) -> tuple[Any, bool]:
    """Make ``world`` in the repository's workspace under its identity and answer its saved entry
    and True, or the workspace's existing copy and False. ``repository`` is the workspace's
    :class:`~exulanica.world.saved_entries.SavedWorldEntryRepository` on a connection with no
    open transaction; ``compose`` makes a place's world (the kind worker's composer for the land,
    by default), so no generation runs on a request's thread, waiting ``seconds`` for it (a
    request's limit unless the caller holds no request). A place the worker has not finished in
    that time is :class:`~exulanica.world.kinds.worker.KindWorkWaiting`; the worker keeps its work,
    so asking again reads it.

    The world is made as the sentence's draft made it, from its preset and values or its kind and
    values, on its land, then given its look and setting as the draft named them; a look the
    library no longer holds, or a write refused as busy, leaves the world in the host's look. Every
    refusal of the making is the one ``POST /worlds/generated`` or a kind's card answers, by name,
    and nothing is written."""
    from contextlib import suppress

    from exulanica.world.creation_look import name_creation_look
    from exulanica.world.errors import StyleWriteBusy

    for entry in repository.entries():
        if entry.world_id == world.world_id:
            return entry, False
    if world.made_by == "town":
        created = repository.create_generated(
            title=world.title,
            recipe_key=world.recipe,
            created_by=created_by,
            values=world.values,
            fixed_world_id=world.world_id,
            land=world.land,
        )
    else:
        from exulanica.world.kinds.worker import WorkerComposer

        composer = compose or (
            WorkerComposer(repository.workspace_id, land=world.land)
            if seconds is None
            else WorkerComposer(repository.workspace_id, land=world.land, seconds=seconds)
        )
        created = repository.create_from_kind(
            title=world.title,
            kind=world.kind,
            values=world.values,
            created_by=created_by,
            compose=composer,
            fixed_world_id=world.world_id,
        )
        keep = getattr(composer, "keep", None)
        if keep is not None:
            keep()
    if world.look is not None:
        with suppress(StyleWriteBusy):
            created = name_creation_look(repository, created, world.look, created_by)
    return created, True


def document_of(world: ShowcaseWorld) -> bytes:
    """The canonical bytes a world's digest is taken over, for a caller writing the lock."""
    return canonical_json(read_document(world.key, world.version))


def read_document(key: str, version: int, directory: Path = SHOWCASE_DIRECTORY) -> dict[str, Any]:
    return json.loads((directory / f"{key}.v{version}.json").read_text(encoding="utf-8"))
