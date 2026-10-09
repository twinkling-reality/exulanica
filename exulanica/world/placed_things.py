"""A thing placed in an authored version: a thing kind, where it stands, and nothing else.

A placed thing is the authored plane's record of a thing a world's author put in a version: a
knight by the well, a sword on the ground, the gate visitors arrive through, a creature drafted
from a person's words. It names a shipped kind by key, version and digest
(:mod:`exulanica.things.kinds`), or a kind its workspace keeps (:mod:`exulanica.world.thing_store`)
by the digest of the kind's document alone, never by a key a person's words made
(:class:`WorkspaceKindReference`); never a look and never an asset: how it is drawn is a look
chosen for it, and what it does is its kind's and the simulation's. Its id is the author's, unique
within the version, and it is posed in a region of the source snapshot like every authored object
(:class:`~exulanica.world.objects.Transform`, region-local), at its kind's own size: a kind's
figures are its own, so a placed thing's scale is always unscaled.

Whether a workspace still holds a placed thing's own kind is read with the thing and never stored
with it (:attr:`PlacedThing.kind_gone`): a kind the workspace erased, or erased after the thing was
placed, leaves the thing gone wherever it is read, and its document says nothing of it.

Its document is the ``things`` section of the version's authored delta
(:mod:`exulanica.world.authored_delta`), written only when the version holds a placed thing, so
the token of every version that holds none keeps its bytes.

Pure: no connection and no SQL, so a verifier can rebuild the document.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from functools import cache
from typing import Any, Final

from exulanica.things.kinds import ThingKind, shipped_thing_kinds
from exulanica.world.errors import InvalidObjectData, InvalidThingPlacement
from exulanica.world.objects import ObjectOrigin, Transform, validate_origin, validate_transform

__all__ = [
    "PLACED_THINGS_MAXIMUM",
    "PLACED_THING_ID_PATTERN",
    "UNSCALED_MILLI",
    "KindReference",
    "PlacedThing",
    "ThingKindReference",
    "ThingPlacement",
    "WorkspaceKindReference",
    "named_kind",
    "placeable_by_author",
    "placed_thing_document",
    "shipped_kind",
    "validate_placed_thing",
    "workspace_kind_reference",
]

#: A placed thing's id, the author's: the shape every authored id in a version has.
PLACED_THING_ID_PATTERN: Final = "^[a-z0-9]([a-z0-9:._-]{0,198}[a-z0-9])?$"
_THING_ID: Final = re.compile(PLACED_THING_ID_PATTERN)
_KIND_KEY: Final = re.compile(r"[a-z][a-z0-9_]{0,47}")
_HEX64: Final = re.compile(r"[0-9a-f]{64}")
#: A thing stands at its kind's own size: its pose's scale is always one to one.
UNSCALED_MILLI: Final = 1000
#: The most things one version holds, removed ones included, since its delta keeps them: a scene's
#: worth, so the delta every edit digests again stays small however a session uses the version.
#: One more is refused by name (``ThingLimitReached``), and undoing a placement makes room again.
PLACED_THINGS_MAXIMUM: Final = 256


@dataclass(frozen=True, slots=True)
class ThingKindReference:
    """A thing kind by key, version and the digest of its document."""

    kind: str
    version: int
    sha256: str

    def document(self) -> dict[str, Any]:
        return {"kind": self.kind, "sha256": self.sha256, "version": self.version}


@dataclass(frozen=True, slots=True)
class WorkspaceKindReference:
    """A kind the placing workspace keeps, by the SHA-256 of its document alone: its key and
    version are the workspace's and may have been made from a person's words, so a world never
    names them."""

    sha256: str

    def document(self) -> dict[str, Any]:
        return {"sha256": self.sha256, "source": "workspace"}


#: What a placed thing names its kind by: a shipped kind, or the workspace's own.
KindReference = ThingKindReference | WorkspaceKindReference


def workspace_kind_reference(sha256: object) -> WorkspaceKindReference:
    """A workspace kind named by ``sha256``, a document digest, or
    :class:`~exulanica.world.errors.InvalidThingPlacement`."""
    if type(sha256) is not str or _HEX64.fullmatch(sha256) is None:
        raise InvalidThingPlacement("a workspace's own kind is named by its document's digest")
    return WorkspaceKindReference(sha256)


@dataclass(frozen=True, slots=True)
class ThingPlacement:
    """What an author asks to place: an id, a kind, a region, a pose and the origin they state."""

    thing_id: str
    kind: KindReference
    region_id: str
    transform: Transform
    origin: ObjectOrigin


@dataclass(frozen=True, slots=True)
class PlacedThing:
    """A thing as a version holds it. ``kind_gone`` is read with it, never stored or digested: a
    workspace's own kind its workspace no longer holds, or erased after the thing was placed."""

    thing_id: str
    kind: KindReference
    region_id: str
    transform: Transform
    origin: ObjectOrigin
    removed: bool = False
    kind_gone: bool = False


def placed_thing_document(thing: PlacedThing) -> dict[str, Any]:
    """The canonical document of one placed thing, what its edits store before and after. A
    shipped kind's is the document it always was; whether a workspace kind is gone is not in it."""
    return {
        "kind": thing.kind.document(),
        "origin": thing.origin.document(),
        "region_id": thing.region_id,
        "removed": thing.removed,
        "thing_id": thing.thing_id,
        "transform": thing.transform.document(),
    }


@cache
def _library() -> Mapping[tuple[str, int], ThingKind]:
    return shipped_thing_kinds()


def shipped_kind(
    reference: ThingKindReference, kinds: Mapping[tuple[str, int], ThingKind] | None = None
) -> ThingKind:
    """The shipped kind ``reference`` names, at exactly its digest, or
    :class:`~exulanica.world.errors.InvalidThingPlacement`, a workspace's own kind included."""
    if isinstance(reference, WorkspaceKindReference):
        raise InvalidThingPlacement("a workspace's own kind is not a shipped kind")
    if (
        not isinstance(reference, ThingKindReference)
        or type(reference.kind) is not str
        or _KIND_KEY.fullmatch(reference.kind) is None
        or type(reference.version) is not int
        or type(reference.sha256) is not str
        or _HEX64.fullmatch(reference.sha256) is None
    ):
        raise InvalidThingPlacement("a thing names its kind by key, version and digest")
    library = _library() if kinds is None else kinds
    kind = library.get((reference.kind, reference.version))
    if kind is None:
        raise InvalidThingPlacement(
            f"no thing kind {reference.kind} version {reference.version} is shipped"
        )
    if kind.sha256 != reference.sha256:
        raise InvalidThingPlacement(
            f"thing kind {reference.kind} version {reference.version} has another digest"
        )
    return kind


def placeable_by_author(kind: ThingKind) -> ThingKind:
    """``kind``, when an author may place a thing of it, or
    :class:`~exulanica.world.errors.InvalidThingPlacement`: a being an author places is decided
    for by its routine until somebody chooses otherwise, so a kind whose deciders exclude the
    routine (a visitor, decided for only by the program that sends it) is never placed."""
    deciders = kind.document["deciders"]
    if kind.klass == "being" and (deciders is None or "routine" not in deciders["allowed"]):
        raise InvalidThingPlacement(
            f"a {kind.kind} is decided for only from outside, so an author does not place one"
        )
    return kind


def named_kind(kind: str, version: int, sha256: str | None = None) -> ThingKindReference:
    """The shipped kind ``kind`` at ``version``, by its digest: ``sha256`` when a caller states
    it, which must then be the shipped one, else the shipped one's."""
    if sha256 is not None:
        return ThingKindReference(
            kind, version, shipped_kind(ThingKindReference(kind, version, sha256)).sha256
        )
    found = _library().get((kind, version))
    if found is None:
        raise InvalidThingPlacement(f"no thing kind {kind} version {version} is shipped")
    return ThingKindReference(kind, version, found.sha256)


def validate_placed_thing(
    thing: PlacedThing,
    *,
    region_ids: frozenset[str],
    kinds: Mapping[tuple[str, int], ThingKind] | None = None,
) -> PlacedThing:
    """``thing`` held to its id, region, pose, origin and a shipped kind at its digest, or a
    workspace kind's digest (whether the workspace holds it is the repository's to read), or
    :class:`~exulanica.world.errors.InvalidThingPlacement` naming the field."""
    if type(thing.thing_id) is not str or _THING_ID.fullmatch(thing.thing_id) is None:
        raise InvalidThingPlacement(
            "thing_id must be lowercase letters, digits, colon, dot, underscore or hyphen, "
            "starting and ending with a letter or digit, at most 200 characters"
        )
    if thing.region_id not in region_ids:
        raise InvalidThingPlacement(f"{thing.region_id} is not a region of the source snapshot")
    try:
        validate_transform(thing.transform)
        validate_origin(thing.origin)
    except InvalidObjectData as exc:
        raise InvalidThingPlacement(str(exc)) from exc
    if thing.transform.scale_milli != UNSCALED_MILLI:
        raise InvalidThingPlacement(
            f"a thing stands at its kind's own size: transform.scale_milli is {UNSCALED_MILLI}"
        )
    if isinstance(thing.kind, WorkspaceKindReference):
        workspace_kind_reference(thing.kind.sha256)
    else:
        shipped_kind(thing.kind, kinds)
    return thing
