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

A document may name its world's paintings (``paintings``): each a painting's record as G1 keeps it
(:class:`~exulanica.world.world_paintings.WorldPaintingRepository`), its camera as JSON text since
a digest takes no decimal, and its bytes in ``paintings/<sha256>.jpg`` beside the documents. A
copy keeps them for its world right after it is made, and again on a later ask where one is missing
(the copy's making runs its own transactions and a place's waits on the kind worker). They are
records only: no page shows a painting (27 October). They are deleted with the copy's world, by its
identity's trigger.

A document may name its world's card picture (``picture``): the engine's own picture of the world
as it opens, the first view a page keeps for a world's card (:mod:`exulanica.world.
saved_entry_pictures`), taken of a copy of that version, with how it was taken, and its bytes in
``pictures/<sha256>.jpg`` beside the documents. A copy keeps it as its own card picture when it is
made, of the copy as it is then, so its card shows the world it opens on before any page has drawn
it; a page puts its own once the copy has changed, as for any world. Before a workspace holds a
copy, the catalog's read serves the same bytes (``GET /worlds/showcase/{showcase}/picture``) for
the card that offers the world.

The lock (``showcase-worlds.lock.json``) names the one version of each world served, by digest:
a served document never changes, a changed one is a new version, and a file the lock does not name
at its digest is refused. Every document is checked when the catalog loads, not at a visitor's
copy: its look's setting is applied to the pack it names
(:func:`~exulanica.world.world_settings.bound_setting`), and each painting's and its picture's
bytes are held to their digest, their media type and their size. Whether a world's documents
still make that world is the installation's check (``python -m exulanica.api.showcase_dressing
prepare``), which makes each once in the operator's workspace and compares the receipt's digest.
"""

from __future__ import annotations

import functools
import json
import logging
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
    "ShowcasePainting",
    "ShowcasePicture",
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
#: What a document may state beside them: a field the profile grew, absent meaning none.
_OPTIONAL: Final = frozenset({"paintings", "picture"})
_PAINTING: Final = frozenset(
    {
        "view",
        "recipe",
        "sha256",
        "media_type",
        "width",
        "height",
        "camera",
        "words",
        "painter",
        "held_permille",
        "cost_microusd",
        "run_id",
    }
)
_PICTURE: Final = frozenset({"sha256", "media_type", "width", "height", "taken"})
#: Where a painting's or a picture's bytes are, by media type.
_BYTES_SUFFIX: Final = {"image/jpeg": ".jpg"}
_WORLD: Final = frozenset(
    {"world_id", "made_by", "recipe", "values", "kind", "land", "receipt_sha256"}
)
_DIGEST: Final = re.compile(r"[0-9a-f]{64}")
_LOG = logging.getLogger(__name__)


class ShowcaseWorldsInvalid(ValueError):
    """A showcase world's document, or the lock, does not say what this module reads; named."""


@dataclass(frozen=True, slots=True)
class CastMember:
    #: The person's place in the society's people, as its state numbers them.
    ordinal: int
    model: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class ShowcasePainting:
    """A card painting of a showcase world, as G1 keeps one, with its bytes."""

    view: str
    recipe: str
    sha256: str
    media_type: str
    data: bytes
    camera: Mapping[str, Any]
    words: Mapping[str, Any]
    painter: Mapping[str, Any]
    held_permille: int
    cost_microusd: int
    run_id: str


@dataclass(frozen=True, slots=True)
class ShowcasePicture:
    """A showcase world's card picture, the engine's own first view of it, with its bytes."""

    sha256: str
    media_type: str
    data: bytes
    #: How it was taken: by what, of which copy, and when.
    taken: Mapping[str, Any]
    #: Its size in pixels, as its record states and its bytes were held to.
    width: int
    height: int


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
    paintings: tuple[ShowcasePainting, ...] = ()
    picture: ShowcasePicture | None = None


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
    if setting is not None:
        from exulanica.world.style_pack_library import style_pack_context
        from exulanica.world.style_packs import StylePackRefused
        from exulanica.world.world_settings import SettingRefused, bound_setting

        chain = style_pack_library().chain(look["manifest_sha256"])
        try:
            if chain is None:
                raise _refuse(where, "names a pack this host's library cannot resolve")
            bound_setting(chain, style_pack_context(), document=setting)
        except (SettingRefused, StylePackRefused) as refused:
            raise _refuse(
                f"{where}.setting", f"is not one the pack can wear: {refused}"
            ) from refused
    return StylePackBinding(
        look["pack_id"],
        look["version"],
        look["manifest_sha256"],
        # As a stored setting is read back: its canonical JSON (repository._setting_text).
        setting=None if setting is None else canonical_json(setting).decode(),
    )


def _held_bytes(where: str, stated: Mapping[str, Any], directory: Path) -> bytes:
    """The bytes a painting's or picture's record names in ``directory``, held as a saved world's
    card picture is held (walked whole), to the size and digest the record states."""
    from exulanica.world.saved_entry_pictures import PictureRefused, checked_picture

    suffix = _BYTES_SUFFIX.get(stated["media_type"])
    named = isinstance(stated["sha256"], str) and _DIGEST.fullmatch(stated["sha256"]) is not None
    if suffix is None or not named:
        raise _refuse(where, f"is a picture of {sorted(_BYTES_SUFFIX)} named by its SHA-256")
    path = directory / f"{stated['sha256']}{suffix}"
    if not path.is_file():
        raise _refuse(where, f"names {path.name}, with no file")
    data = path.read_bytes()
    try:
        width, height, sha256 = checked_picture(data, stated["media_type"])
    except PictureRefused as refused:
        raise _refuse(where, f"{path.name} is not a picture kept as stated: {refused}") from refused
    if (width, height, sha256) != (stated["width"], stated["height"], stated["sha256"]):
        raise _refuse(where, f"{path.name} is not the picture its record states")
    return data


def _picture(where: str, raw: object, directory: Path) -> ShowcasePicture:
    """A card picture's record, its bytes read from ``directory`` and held to it."""
    stated = _fields(where, raw, _PICTURE)
    data = _held_bytes(where, stated, directory)
    if not isinstance(stated["taken"], dict):
        raise _refuse(f"{where}.taken", "is how the picture was taken, an object")
    return ShowcasePicture(
        sha256=stated["sha256"],
        media_type=stated["media_type"],
        data=data,
        taken=stated["taken"],
        width=stated["width"],
        height=stated["height"],
    )


def _painting(where: str, raw: object, directory: Path) -> ShowcasePainting:
    """A painting's record, its bytes read from ``directory`` and held to it as G1 holds them."""
    stated = _fields(where, raw, _PAINTING)
    data = _held_bytes(where, stated, directory)
    try:
        camera = json.loads(stated["camera"]) if isinstance(stated["camera"], str) else None
    except json.JSONDecodeError:
        camera = None
    texts = {"camera": camera, "words": stated["words"], "painter": stated["painter"]}
    for name, value in texts.items():
        if not isinstance(value, dict):
            raise _refuse(f"{where}.{name}", "is an object (the camera as its JSON text)")
    for name in ("held_permille", "cost_microusd"):
        if type(stated[name]) is not int or stated[name] < 0:
            raise _refuse(f"{where}.{name}", "is a whole number from 0")
    return ShowcasePainting(
        view=stated["view"],
        recipe=stated["recipe"],
        sha256=stated["sha256"],
        media_type=stated["media_type"],
        data=data,
        camera=texts["camera"],
        words=texts["words"],
        painter=texts["painter"],
        held_permille=stated["held_permille"],
        cost_microusd=stated["cost_microusd"],
        run_id=stated["run_id"],
    )


def read_showcase_world(
    document: object,
    paintings: Path = SHOWCASE_DIRECTORY / "paintings",
    pictures: Path = SHOWCASE_DIRECTORY / "pictures",
) -> ShowcaseWorld:
    """A showcase world's document, read and checked, its paintings' bytes read from ``paintings``
    and its card picture's from ``pictures``; refused by name otherwise."""
    from exulanica.world.kinds.document import read_kind
    from exulanica.world.world_recipes import town_recipe

    if not isinstance(document, dict) or not _TOP <= set(document) <= _TOP | _OPTIONAL:
        raise _refuse("document", f"is an object of {sorted(_TOP)} and any of {sorted(_OPTIONAL)}")
    raw = document
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
    stated = raw.get("paintings", [])
    if not isinstance(stated, list):
        raise _refuse("paintings", "is a list of the world's paintings")
    painted = tuple(
        _painting(f"paintings[{index}]", one, paintings) for index, one in enumerate(stated)
    )
    picture = None if raw.get("picture") is None else _picture("picture", raw["picture"], pictures)
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
        paintings=painted,
        picture=picture,
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
        world = read_showcase_world(
            json.loads(path.read_text(encoding="utf-8")),
            directory / "paintings",
            directory / "pictures",
        )
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
            _keep_paintings(repository, world)
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
    # The card picture shows the world in the look its document names: a copy left in the host's
    # look keeps none, and its card waits for the first page that draws it.
    looks_as_pictured = world.look is None
    if world.look is not None:
        with suppress(StyleWriteBusy):
            created = name_creation_look(repository, created, world.look, created_by)
            looks_as_pictured = True
    _keep_paintings(repository, world)
    if looks_as_pictured:
        _keep_picture(repository, world, created, created_by)
    return created, True


def _keep_picture(repository: Any, world: ShowcaseWorld, entry: Any, taken_by: uuid.UUID) -> None:
    """Keep ``world``'s card picture as the copy's own, of the copy as it was just made, as a page
    keeps a first view it drew. One refused leaves the card to the first page that draws it."""
    from exulanica.world.saved_entry_pictures import (
        PictureRefused,
        PictureShows,
        SavedEntryPictureRepository,
    )

    if world.picture is None:
        return
    pictures = SavedEntryPictureRepository(repository.connection, repository.workspace_id)
    try:
        with repository.connection.transaction():
            pictures.keep(
                entry,
                world.picture.data,
                world.picture.media_type,
                PictureShows.of(entry),
                taken_by,
            )
    except PictureRefused as refused:
        _LOG.warning(
            "a showcase copy kept no card picture %s: %s", world.picture.sha256[:12], refused
        )


def _keep_paintings(repository: Any, world: ShowcaseWorld) -> None:
    """Keep each of ``world``'s paintings for the repository's copy of it: the same bytes kept again
    are one. One refused leaves the copy without that painting and nothing else."""
    from exulanica.world.saved_entry_pictures import PictureRefused
    from exulanica.world.world_paintings import WorldPaintingRepository

    paintings = WorldPaintingRepository(repository.connection, repository.workspace_id)
    for painting in world.paintings:
        try:
            with repository.connection.transaction():
                paintings.keep(
                    world.world_id,
                    view=painting.view,
                    recipe=painting.recipe,
                    data=painting.data,
                    media_type=painting.media_type,
                    camera=dict(painting.camera),
                    words=dict(painting.words),
                    painter=dict(painting.painter),
                    held_permille=painting.held_permille,
                    cost_microusd=painting.cost_microusd,
                    run_id=painting.run_id,
                )
        except PictureRefused as refused:
            _LOG.warning("a showcase copy kept no painting %s: %s", painting.sha256[:12], refused)


def document_of(world: ShowcaseWorld) -> bytes:
    """The canonical bytes a world's digest is taken over, for a caller writing the lock."""
    return canonical_json(read_document(world.key, world.version))


def read_document(key: str, version: int, directory: Path = SHOWCASE_DIRECTORY) -> dict[str, Any]:
    return json.loads((directory / f"{key}.v{version}.json").read_text(encoding="utf-8"))
