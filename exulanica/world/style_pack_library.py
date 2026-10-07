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
library. The library lists each pack with what a person choosing one needs: its id, version and
manifest digest; its title, description and tags; its origin; its licence with the attribution it
requires, and its authors; its preview picture's digest and media type, when it has one; and
whether it is the default. It serves each
manifest as its canonical bytes, so the digest that identifies a pack names exactly the bytes
served, and each listed file as the media type its manifest states, all as committed content by
digest (:mod:`exulanica.world.committed_content`). The host reads it once, when it starts
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
    "LIBRARY_DIRECTORY",
    "LIBRARY_FILE",
    "LIBRARY_PROFILE",
    "LIST_PROFILE",
    "MANIFEST_MEDIA_TYPE",
    "LibraryPack",
    "StylePackLibrary",
    "StylePackLibraryRefused",
    "load_style_pack_library",
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
_MANIFEST: Final = "manifest.json"


class StylePackLibraryRefused(ValueError):
    """The committed library breaks a rule: which pack, and which rule."""


@dataclass(frozen=True, slots=True)
class LibraryPack:
    """One committed pack as the library lists it."""

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
        }


@dataclass(frozen=True, slots=True)
class StylePackLibrary:
    """Every committed pack, by id, and every byte the library serves, by digest."""

    packs: tuple[LibraryPack, ...]
    content: CommittedContent
    #: The id of the pack a town is made in when the person making it names none.
    default: str

    def pack(self, pack_id: str) -> LibraryPack | None:
        """The committed pack ``pack_id`` names, or None."""
        return next((pack for pack in self.packs if pack.pack_id == pack_id), None)

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


def _read_pack(folder: Path, context: StylePackContext) -> _Read:
    """One folder's manifest as read and every item it serves, the manifest first."""
    name = folder.name
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
    if read["pack_id"] != name:
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
    path = manifest["preview"]
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


def load_style_pack_library(
    directory: Path = LIBRARY_DIRECTORY,
    context: StylePackContext | None = None,
    library_file: Path = LIBRARY_FILE,
) -> StylePackLibrary:
    """Read and check every pack in ``directory`` and the default ``library_file`` names; refuse
    the library at the first broken rule."""
    context = load_context(_ROOT) if context is None else context
    packs: dict[str, _Read] = {}
    for folder in sorted(directory.iterdir()):
        if folder.name.startswith("."):
            continue
        if folder.is_symlink() or not folder.is_dir():
            raise _refuse(folder.name, "is not a pack folder")
        read = _read_pack(folder, context)
        packs[read.manifest["pack_id"]] = read
    for pack_id, read in packs.items():
        base = read.manifest["base"]
        if base is None:
            continue
        found = packs.get(base["pack_id"])
        if (
            found is None
            or found.manifest["version"] != base["version"]
            or found.digest != base["manifest_sha256"]
        ):
            raise _refuse(pack_id, f"its base {base['pack_id']} is not a pack of the library")
    default = _default(library_file, packs)
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
            )
            for pack_id, read in sorted(packs.items())
        ),
        content=CommittedContent(item for read in packs.values() for item in read.items),
        default=default,
    )


@functools.cache
def style_pack_library() -> StylePackLibrary:
    """The committed library, read and checked once per process."""
    return load_style_pack_library()
