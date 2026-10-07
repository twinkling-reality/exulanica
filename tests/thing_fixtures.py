"""A shipped thing kind for a test to place, read from the kind library rather than named.

A test that places a thing to show what placing does names no kind of its own: it asks here for a
placeable kind, so a kind retired or given a new version leaves the existence sweep, the route
probes and the undo suite placing whatever the library ships. Tests about one kind (its digest,
its figures) and the delta goldens still name it.
"""

from __future__ import annotations

from typing import Any

from exulanica.things.kinds import ThingKind, shipped_thing_kinds
from exulanica.world.placed_things import ThingKindReference


def placeable_kinds() -> list[ThingKind]:
    """Every shipped kind, in key and version order."""
    return [kind for _key, kind in sorted(shipped_thing_kinds().items())]


def placeable_kind(index: int = 0) -> ThingKind:
    """A shipped kind to place: the ``index``th in key and version order, so a test placing two
    different kinds asks for two indexes."""
    return placeable_kinds()[index]


def kind_body(kind: ThingKind) -> dict[str, Any]:
    """How a route body names ``kind``: its key and version, the digest left to the server."""
    return {"kind": kind.kind, "version": kind.version}


def kind_reference(kind: ThingKind) -> ThingKindReference:
    """How a placement names ``kind``: key, version and digest."""
    return ThingKindReference(kind.kind, kind.version, kind.sha256)
