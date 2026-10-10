"""The committed style pack library: the packs this tree carries, read once and served by digest.

Each folder of ``assets/style-packs/packs/`` is one pack: ``manifest.json`` (its canonical JSON and
one newline) and the files the manifest lists. :func:`load_style_pack_library` reads every folder
and requires, in this order: the manifest written as exactly that canonical JSON; the manifest read
by the authoritative reader (:func:`exulanica.world.style_packs.read_manifest`) against this tree's
look families and texture sets; the folder named by the pack's id; every listed file present as a
regular file with exactly the bytes and digest the manifest states; nothing else in the folder;
and a stated base that is another pack of the library at the version and digest it names. One pack
that breaks a rule refuses the whole library, naming the pack and the rule, because committed data
that fails its own checks is a defect to fix rather than a pack to leave out. A name starting with
a dot (an operating system's folder notes) is passed over: no pack id or listed path can start with
one, so nothing it holds is ever served.

``assets/style-packs/library.v1.json`` names the library's default pack, the look a town is made
in when the person making it names none; a default that is not a pack of the library refuses the
library.

A pack's earlier versions stay servable, so a world drawn in one keeps its look when the pack
moves on. Each is a whole pack folder as it was published, ``assets/style-packs/published/<pack
id>/<version>/``, checked by the same rules as a pack folder, and ``published.v1.json`` beside the
packs folder is their ledger: each one's pack id, version and manifest digest, appended when the
version was retired and never changed. A published folder whose manifest no longer hashes to its
entry, an entry with no folder, a folder with no entry, and a version that is not below its pack's
current one each refuse the library. ``changes.v1.json`` holds the host's own note on what a pack
version changed, one sentence for a person, for any version the library holds.

The library lists each pack's current version with what a person choosing one needs: its id,
version and manifest digest; its title, description and tags; its origin; its licence with the
attribution it requires, and its authors; its preview picture's digest and media type, when it
has one; whether it is the default; the note on what this version changed, or none; and its
earlier versions, oldest first, each with its manifest digest and preview picture. It holds every
version, current and earlier, so a world may name any of them, and serves each manifest as its
canonical bytes, so the digest that identifies a pack names exactly the bytes served, and each
listed file as the media type its manifest states, all as committed content by digest
(:mod:`exulanica.world.committed_content`). The host reads it once, when it starts
(``exulanica.api.app``), and ``exulanica.api.routes.style_packs`` serves it.
"""

from __future__ import annotations

import functools
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from exulanica.world.committed_content import CommittedContent, ServedItem
from exulanica.world.style_packs import (
    StylePackContext,
    StylePackRefused,
    canonical_json,
    load_context,
    read_manifest,
)

__all__ = [
    "CHANGES_PROFILE",
    "LIBRARY_DIRECTORY",
    "LIBRARY_FILE",
    "LIBRARY_PROFILE",
    "LIST_PROFILE",
    "MANIFEST_MEDIA_TYPE",
    "PUBLISHED_PROFILE",
    "EarlierVersion",
    "LibraryPack",
    "StylePackLibrary",
    "StylePackLibraryRefused",
    "load_style_pack_library",
    "style_pack_context",
    "style_pack_library",
]

_ROOT: Final = Path(__file__).resolve().parents[2]
#: Where the committed packs are, one folder each, named by pack id.
LIBRARY_DIRECTORY: Final = _ROOT / "assets" / "style-packs" / "packs"
#: Which pack of the library is its default.
LIBRARY_FILE: Final = _ROOT / "assets" / "style-packs" / "library.v1.json"
#: The profile of that file: its default pack's id and nothing else.
LIBRARY_PROFILE: Final = "exulanica.style-pack-library/v1"
#: The profile of the list ``GET /world/style-packs`` answers.
LIST_PROFILE: Final = "exulanica.style-pack-list/v1"
#: The media type a manifest is served as: its canonical JSON.
MANIFEST_MEDIA_TYPE: Final = "application/json"
#: The profile of the published versions' ledger, beside the packs folder as ``published.v1.json``.
PUBLISHED_PROFILE: Final = "exulanica.style-pack-published/v1"
#: The profile of the notes on what each version changed, beside it as ``changes.v1.json``.
CHANGES_PROFILE: Final = "exulanica.style-pack-changes/v1"
#: A note's length at most: one sentence.
CHANGES_MAX: Final = 200
_MANIFEST: Final = "manifest.json"
_PUBLISHED: Final = "published"
_PUBLISHED_FILE: Final = "published.v1.json"
_CHANGES_FILE: Final = "changes.v1.json"


class StylePackLibraryRefused(ValueError):
    """The committed library breaks a rule: which pack, and which rule."""


@dataclass(frozen=True, slots=True)
class EarlierVersion:
    """An earlier version of a library pack, still served by its digest."""

    version: int
    manifest_sha256: str
    preview_sha256: str | None
    preview_media_type: str | None

    def listing(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "manifest_sha256": self.manifest_sha256,
            "preview_sha256": self.preview_sha256,
            "preview_media_type": self.preview_media_type,
        }


@dataclass(frozen=True, slots=True)
class LibraryPack:
    """One committed pack, at its current version, as the library lists it."""

    pack_id: str
    version: int
    manifest_sha256: str
    title: str
    description: str
    tags: tuple[str, ...]
    origin: str
    licence: str
    attribution: str | None
    authors: tuple[str, ...]
    #: How many files the manifest lists.
    files: int
    #: The bytes of the manifest and every file it lists.
    total_bytes: int
    #: The preview picture's SHA-256 and media type, or None for a pack with no picture.
    preview_sha256: str | None = None
    preview_media_type: str | None = None
    #: The host's note on what this version changed from the one before, or None.
    changes: str | None = None
    #: The pack's earlier versions the library still serves, oldest first.
    earlier_versions: tuple[EarlierVersion, ...] = ()

    def listing(self) -> dict[str, Any]:
        return {
            "pack_id": self.pack_id,
            "version": self.version,
            "manifest_sha256": self.manifest_sha256,
            "title": self.title,
            "description": self.description,
            "tags": list(self.tags),
            "origin": self.origin,
            "licence": {"id": self.licence, "attribution": self.attribution},
            "authors": list(self.authors),
            "files": self.files,
            "total_bytes": self.total_bytes,
            "preview_sha256": self.preview_sha256,
            "preview_media_type": self.preview_media_type,
            "changes": self.changes,
            "earlier_versions": [earlier.listing() for earlier in self.earlier_versions],
        }


@dataclass(frozen=True, slots=True)
class StylePackLibrary:
    """Every committed pack, by id, and every byte the library serves, by digest."""

    packs: tuple[LibraryPack, ...]
    content: CommittedContent
    #: The id of the pack a town is made in when the person making it names none.
    default: str

    def pack(self, pack_id: str) -> LibraryPack | None:
        """The committed pack ``pack_id`` names, at its current version, or None."""
        return next((pack for pack in self.packs if pack.pack_id == pack_id), None)

    def holds(self, pack_id: str, version: int, manifest_sha256: str) -> bool:
        """Whether the library serves ``pack_id`` at exactly ``version`` and ``manifest_sha256``,
        its current version or an earlier one."""
        pack = self.pack(pack_id)
        if pack is None:
            return False
        held = [(pack.version, pack.manifest_sha256)]
        held.extend((old.version, old.manifest_sha256) for old in pack.earlier_versions)
        return (version, manifest_sha256) in held

    def chain(self, manifest_sha256: str) -> tuple[dict[str, Any], ...] | None:
        """The manifest ``manifest_sha256`` names and each base it is drawn on, nearest first, as
        the library holds them; None when it holds no such manifest."""
        found: list[dict[str, Any]] = []
        digest: str | None = manifest_sha256
        while digest is not None:
            item = self.content.get(digest)
            if item is None or item.media_type != MANIFEST_MEDIA_TYPE:
                return None
            manifest = json.loads(item.data)
            found.append(manifest)
            digest = None if manifest["base"] is None else manifest["base"]["manifest_sha256"]
        return tuple(found)

    @property
    def default_pack(self) -> LibraryPack:
        """The library's default pack, which loading held to be one of its packs."""
        found = self.pack(self.default)
        assert found is not None
        return found

    def listing(self) -> dict[str, Any]:
        """The document ``GET /world/style-packs`` answers, packs in id order."""
        return {
            "profile": LIST_PROFILE,
            "packs": [
                {**pack.listing(), "default": pack.pack_id == self.default} for pack in self.packs
            ],
        }


@dataclass(frozen=True, slots=True)
class _Read:
    manifest: dict[str, Any]
    items: tuple[ServedItem, ...]

    @property
    def digest(self) -> str:
        return self.items[0].sha256


def _refuse(folder: str, detail: str) -> StylePackLibraryRefused:
    return StylePackLibraryRefused(f"style pack {folder}: {detail}")


def _read_pack(folder: Path, context: StylePackContext, pack_id: str, name: str) -> _Read:
    """One folder's manifest as read and every item it serves, the manifest first: ``pack_id`` is
    the id the folder's place names, and ``name`` how a refusal names the folder."""
    text = (folder / _MANIFEST).read_text(encoding="utf-8")
    try:
        manifest = json.loads(text)
        canonical = canonical_json(manifest)
    except (json.JSONDecodeError, StylePackRefused) as refused:
        raise _refuse(name, f"its manifest is not canonical JSON: {refused}") from refused
    if text != canonical + "\n":
        raise _refuse(name, "its manifest is not written as its canonical JSON and one newline")
    try:
        read = read_manifest(manifest, context)
    except StylePackRefused as refused:
        raise _refuse(name, f"its manifest is refused: {refused}") from refused
    if read["pack_id"] != pack_id:
        raise _refuse(name, f"its folder is not named by its pack id {read['pack_id']}")
    manifest_bytes = canonical.encode("ascii")
    items = [
        ServedItem(hashlib.sha256(manifest_bytes).hexdigest(), MANIFEST_MEDIA_TYPE, manifest_bytes)
    ]
    listed = {_MANIFEST}
    for file in read["files"]:
        path = folder / file["path"]
        if path.is_symlink() or not path.is_file():
            raise _refuse(name, f"lists {file['path']}, which is not a file in its folder")
        data = path.read_bytes()
        if len(data) != file["bytes"] or hashlib.sha256(data).hexdigest() != file["sha256"]:
            raise _refuse(name, f"{file['path']} is not the bytes its manifest states")
        items.append(ServedItem(file["sha256"], file["media_type"], data))
        listed.add(file["path"])
    for path in sorted(folder.rglob("*")):
        relative = path.relative_to(folder)
        if any(part.startswith(".") for part in relative.parts):
            continue
        if path.is_dir() and not path.is_symlink():
            continue
        if relative.as_posix() not in listed:
            raise _refuse(name, f"holds {relative.as_posix()}, which its manifest does not list")
    return _Read(read, tuple(items))


def _preview(manifest: dict[str, Any]) -> dict[str, str | None]:
    """The listed file a manifest names as its preview, by digest and media type."""
    path = manifest.get("preview")
    file = next((file for file in manifest["files"] if file["path"] == path), None)
    if file is None:
        return {"preview_sha256": None, "preview_media_type": None}
    return {"preview_sha256": file["sha256"], "preview_media_type": file["media_type"]}


def _default(library_file: Path, packs: dict[str, _Read]) -> str:
    """The pack ``library_file`` names as the default, which must be one of ``packs``."""
    try:
        document = json.loads(library_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as unread:
        raise StylePackLibraryRefused(f"{library_file.name} cannot be read: {unread}") from unread
    if (
        not isinstance(document, dict)
        or set(document) != {"profile", "default"}
        or document["profile"] != LIBRARY_PROFILE
    ):
        raise StylePackLibraryRefused(
            f"{library_file.name} is not {LIBRARY_PROFILE}: a profile and a default, nothing else"
        )
    if document["default"] not in packs:
        raise StylePackLibraryRefused(
            f"{library_file.name} names {document['default']!r} the default, "
            "which is not a pack of the library"
        )
    return str(document["default"])


def _records(path: Path, profile: str, key: str, fields: set[str]) -> list[dict[str, Any]]:
    """The records a library file beside the packs folder lists under ``key``, each holding
    exactly ``fields``; none when the file is absent."""
    if not path.exists():
        return []
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as unread:
        raise StylePackLibraryRefused(f"{path.name} cannot be read: {unread}") from unread
    if (
        not isinstance(document, dict)
        or set(document) != {"profile", key}
        or document["profile"] != profile
        or not isinstance(document[key], list)
        or any(not isinstance(record, dict) or set(record) != fields for record in document[key])
    ):
        raise StylePackLibraryRefused(
            f"{path.name} is not {profile}: a profile and a list of {key}, each "
            f"{', '.join(sorted(fields))}, nothing else"
        )
    order = [(record["pack_id"], record["version"]) for record in document[key]]
    if any(
        not isinstance(pack_id, str) or isinstance(version, bool) or not isinstance(version, int)
        for pack_id, version in order
    ) or order != sorted(set(order)):
        raise StylePackLibraryRefused(
            f"{path.name} lists its {key} once each, by pack id and then version"
        )
    return list(document[key])


def _published(directory: Path, context: StylePackContext) -> list[_Read]:
    """Every earlier version the ledger beside ``directory`` lists, read from its folder and held
    to its entry; a folder the ledger does not list refuses the library."""
    root = directory.parent / _PUBLISHED
    entries = _records(
        directory.parent / _PUBLISHED_FILE,
        PUBLISHED_PROFILE,
        "versions",
        {"pack_id", "version", "manifest_sha256"},
    )
    listed = {(entry["pack_id"], str(entry["version"])) for entry in entries}
    if root.is_dir():
        for pack_folder in sorted(root.iterdir()):
            if pack_folder.name.startswith("."):
                continue
            versions = sorted(pack_folder.iterdir()) if pack_folder.is_dir() else [pack_folder]
            for folder in versions:
                if folder.name.startswith("."):
                    continue
                if (pack_folder.name, folder.name) not in listed:
                    raise _refuse(
                        f"{pack_folder.name} published {folder.name}",
                        f"is not a version {_PUBLISHED_FILE} lists",
                    )
    reads = []
    for entry in entries:
        pack_id, version = entry["pack_id"], entry["version"]
        name = f"{pack_id} version {version}"
        folder = root / pack_id / str(version)
        if folder.is_symlink() or not folder.is_dir():
            raise _refuse(name, f"is listed in {_PUBLISHED_FILE} and has no published folder")
        read = _read_pack(folder, context, pack_id, name)
        if read.manifest["version"] != version:
            raise _refuse(name, f"its manifest states version {read.manifest['version']}")
        if read.digest != entry["manifest_sha256"]:
            raise _refuse(name, f"its manifest is not the one {_PUBLISHED_FILE} records")
        reads.append(read)
    return reads


def _notes(directory: Path, held: set[tuple[str, int]]) -> dict[tuple[str, int], str]:
    """The notes beside ``directory`` on what a version changed, each for a version the library
    holds, one sentence of plain text."""
    notes = {}
    for record in _records(
        directory.parent / _CHANGES_FILE,
        CHANGES_PROFILE,
        "notes",
        {"pack_id", "version", "changes"},
    ):
        key = (record["pack_id"], record["version"])
        name = f"{key[0]} version {key[1]}"
        if key not in held:
            raise _refuse(name, f"has a note in {_CHANGES_FILE} and is not a version it holds")
        text = record["changes"]
        if (
            not isinstance(text, str)
            or not 1 <= len(text) <= CHANGES_MAX
            or text != text.strip()
            or any(ord(character) < 0x20 or 0x7F <= ord(character) < 0xA0 for character in text)
        ):
            raise _refuse(
                name, f"its note must be 1 to {CHANGES_MAX} characters of trimmed plain text"
            )
        notes[key] = text
    return notes


def load_style_pack_library(
    directory: Path = LIBRARY_DIRECTORY,
    context: StylePackContext | None = None,
    library_file: Path = LIBRARY_FILE,
) -> StylePackLibrary:
    """Read and check every pack in ``directory``, the default ``library_file`` names, and the
    published versions and notes beside ``directory``; refuse the library at the first broken
    rule."""
    context = load_context(_ROOT) if context is None else context
    packs: dict[str, _Read] = {}
    for folder in sorted(directory.iterdir()):
        if folder.name.startswith("."):
            continue
        if folder.is_symlink() or not folder.is_dir():
            raise _refuse(folder.name, "is not a pack folder")
        read = _read_pack(folder, context, folder.name, folder.name)
        packs[read.manifest["pack_id"]] = read
    published = _published(directory, context)
    earlier: dict[str, list[_Read]] = {}
    for read in published:
        pack_id = read.manifest["pack_id"]
        current = packs.get(pack_id)
        if current is None or read.manifest["version"] >= current.manifest["version"]:
            raise _refuse(
                f"{pack_id} version {read.manifest['version']}",
                "is published and is not below a current version of the library",
            )
        earlier.setdefault(pack_id, []).append(read)
    held = {
        (read.manifest["pack_id"], read.manifest["version"]): read.digest
        for read in (*packs.values(), *published)
    }
    for read in (*packs.values(), *published):
        base = read.manifest["base"]
        if base is None:
            continue
        if held.get((base["pack_id"], base["version"])) != base["manifest_sha256"]:
            raise _refuse(
                read.manifest["pack_id"], f"its base {base['pack_id']} is not a pack of the library"
            )
    default = _default(library_file, packs)
    notes = _notes(directory, set(held))
    return StylePackLibrary(
        packs=tuple(
            LibraryPack(
                pack_id=pack_id,
                version=read.manifest["version"],
                manifest_sha256=read.digest,
                title=read.manifest["title"],
                description=read.manifest["description"],
                tags=tuple(read.manifest["tags"]),
                origin=read.manifest["origin"],
                licence=read.manifest["licence"]["id"],
                attribution=read.manifest["licence"]["attribution"],
                authors=tuple(read.manifest["authors"]),
                files=len(read.manifest["files"]),
                total_bytes=sum(len(item.data) for item in read.items),
                **_preview(read.manifest),
                changes=notes.get((pack_id, read.manifest["version"])),
                earlier_versions=tuple(
                    EarlierVersion(
                        version=old.manifest["version"],
                        manifest_sha256=old.digest,
                        **_preview(old.manifest),
                    )
                    for old in sorted(
                        earlier.get(pack_id, []), key=lambda old: old.manifest["version"]
                    )
                ),
            )
            for pack_id, read in sorted(packs.items())
        ),
        content=CommittedContent(
            item for read in (*packs.values(), *published) for item in read.items
        ),
        default=default,
    )


@functools.cache
def style_pack_context() -> StylePackContext:
    """The look families and texture sets every manifest of this tree is read against, read once."""
    return load_context(_ROOT)


@functools.cache
def style_pack_library() -> StylePackLibrary:
    """The committed library, read and checked once per process."""
    return load_style_pack_library()
