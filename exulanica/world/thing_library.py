"""The shipped thing library, served by digest: every kind, look, body plan and look container.

A renderer draws a thing from its look, and a card says what it is from its kind; both read them
here, by the SHA-256 of the exact bytes, the same for every workspace
(:class:`~exulanica.world.committed_content.CommittedContent`):

*   each shipped kind and look as its canonical JSON (its digest is the document's own, so the
    address checks itself), and the body plans catalog as its file;
*   each look's container: an authored look's as :mod:`exulanica.things.authored` writes it, a
    furniture look's as the reviewed asset the world object catalog generates, and an imported
    look's as the file committed under ``assets/things``; each is held to the digest its look pins,
    and a look whose container none of them gives is refused when the library is made.

A look file named for another look or version than it states is refused, and so is a kind that
suggests a look the library does not hold at the digest the kind names, so every look a kind
suggests can be fetched.

The listing (``exulanica.thing-library/v1``) names every kind with the looks it suggests, every
look with its container, and the body plans catalog, so a reader fetches only what it draws.
"""

from __future__ import annotations

import functools
import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from exulanica.canonical import canonical_json
from exulanica.grammar.documents import read_json
from exulanica.things.authored import AUTHORED_LOOKS, container_of
from exulanica.things.kinds import KINDS_DIRECTORY, shipped_thing_kinds
from exulanica.things.looks import Look, read_look
from exulanica.world.assets import reviewed_assets
from exulanica.world.committed_content import CommittedContent, ServedItem

__all__ = [
    "BODY_PLANS",
    "IMPORTED_CONTAINERS",
    "LIBRARY_PROFILE",
    "LOOKS_DIRECTORY",
    "ThingLibrary",
    "ThingLibraryRefused",
    "load_thing_library",
    "thing_library",
]

LIBRARY_PROFILE: Final = "exulanica.thing-library/v1"
_ROOT: Final = KINDS_DIRECTORY.parents[3]
LOOKS_DIRECTORY: Final = KINDS_DIRECTORY.parent / "looks"
BODY_PLANS: Final = KINDS_DIRECTORY.parent / "body-plans.v1.json"
#: Where an imported look's container is committed, read by the digest its look pins.
IMPORTED_CONTAINERS: Final = _ROOT / "assets" / "things"
_JSON: Final = "application/json"
_GLB: Final = "model/gltf-binary"


class ThingLibraryRefused(ValueError):
    """A shipped look misnamed or whose container no source gives at the digest it pins, or a
    kind suggesting a look the library does not hold."""


@dataclass(frozen=True)
class ThingLibrary:
    """What the library lists, and everything it serves by digest."""

    document: Mapping[str, Any]
    content: CommittedContent

    def listing(self) -> dict[str, Any]:
        return dict(self.document)


def _looks(directory: Path) -> list[Look]:
    found = []
    for path in sorted(directory.glob("*.v*.json")):
        look = read_look(read_json(path))
        if path.name != f"{look.look}.v{look.version}.json":
            raise ThingLibraryRefused(f"{path.name} does not name the look and version it states")
        found.append(look)
    return found


def _imported(directory: Path) -> dict[str, bytes]:
    """Every container committed for an imported look, by the SHA-256 of its bytes."""
    if not directory.is_dir():
        return {}
    found = {}
    for path in sorted(directory.rglob("*.glb")):
        data = path.read_bytes()
        found[hashlib.sha256(data).hexdigest()] = data
    return found


def _container(look: Look, generated: Mapping[str, bytes], imported: Mapping[str, bytes]) -> bytes:
    """A look's container bytes, from the source that makes it, held to the digest it pins."""
    pinned = look.document["container"]["sha256"]
    if look.look in AUTHORED_LOOKS:
        data = container_of(look.look)
    else:
        data = generated.get(pinned) or imported.get(pinned)
        if data is None:
            raise ThingLibraryRefused(f"no source gives the container look {look.look} pins")
    if hashlib.sha256(data).hexdigest() != pinned:
        raise ThingLibraryRefused(f"look {look.look}'s container is not the one it pins")
    return data


def load_thing_library(
    *, looks_directory: Path = LOOKS_DIRECTORY, imported_directory: Path = IMPORTED_CONTAINERS
) -> ThingLibrary:
    """The library, read and checked: every shipped kind and look, the body plans and every
    container a look pins."""
    kinds = [kind for _key, kind in sorted(shipped_thing_kinds().items())]
    looks = _looks(looks_directory)
    generated = {asset.content_sha256: asset.payload for asset in reviewed_assets()}
    imported = _imported(imported_directory)
    items: list[ServedItem] = []
    for kind in kinds:
        items.append(ServedItem(kind.sha256, _JSON, canonical_json(dict(kind.document))))
    listed_looks = []
    for look in looks:
        items.append(ServedItem(look.sha256, _JSON, canonical_json(dict(look.document))))
        container = look.document["container"]
        if container is not None:
            items.append(
                ServedItem(container["sha256"], _GLB, _container(look, generated, imported))
            )
        listed_looks.append(
            {
                **look.reference(),
                "label": look.label,
                "body_plan": look.body_plan,
                "look_kind": look.look_kind,
                "container": None if container is None else dict(container),
            }
        )
    held = {(look.look, look.version, look.sha256) for look in looks}
    for kind in kinds:
        for suggested in kind.looks:
            if (suggested["look"], suggested["version"], suggested["sha256"]) not in held:
                raise ThingLibraryRefused(
                    f"kind {kind.kind} version {kind.version} suggests look {suggested['look']} "
                    f"version {suggested['version']}, which the library does not hold at its digest"
                )
    plans = BODY_PLANS.read_bytes()
    plans_sha256 = hashlib.sha256(plans).hexdigest()
    items.append(ServedItem(plans_sha256, _JSON, plans))
    document = {
        "profile": LIBRARY_PROFILE,
        "kinds": [
            {
                **kind.reference(),
                "label": kind.label,
                "class": kind.klass,
                "body_plan": kind.plan,
                "looks": [dict(look) for look in kind.looks],
            }
            for kind in kinds
        ],
        "looks": listed_looks,
        "body_plans": {"sha256": plans_sha256},
    }
    return ThingLibrary(document=document, content=CommittedContent(items))


@functools.cache
def thing_library() -> ThingLibrary:
    """The shipped library, read and checked once per process."""
    return load_thing_library()
