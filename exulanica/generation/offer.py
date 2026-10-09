"""What the Companion offers when a person asks for new pieces of a world's look, and its cost.

The Companion's world-edit drafter may name ``request_pieces``
(``exulanica.selection.action_plan``): new pieces of the world's look, made by open models on a GPU
(contract: generated pieces), for kinds of thing the person names, or, when they name none, for the
world's things the look dresses only with its family's default or the engine's box
(:func:`~exulanica.world.style_packs.role_offer`). The step is one request to
``POST /world/piece-requests``. Nothing is asked of a GPU and nothing is spent until the person
confirms: the step carries the estimate the route itself answers with (minutes on a running and a
starting piece maker, US dollars typically and at most, the provider, and where the figures come
from), so the sheet names the time and the cost before the yes.

The look the pieces are made in is the library pack the world wears: a world wearing its own look of
generated pieces asks in that look's library base, which is the look the pieces are taken into
(contract: generated pieces, section 5.4); a world naming no pack asks in the library's default.
:class:`WorldPieces` is what the actions route hands the Companion's planner, which may not import
this package itself (the backend's layers): the planner names kinds, this answers with the request.
"""

from __future__ import annotations

import functools
import json
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from exulanica.generation.requests import (
    GPU_PROVIDER,
    MAXIMUM_KINDS,
    LookReference,
    PieceAskRefused,
    estimate,
    generation_catalogs,
    plan_requests,
)
from exulanica.world import WorldNotConfigured, WorldStyleRepository
from exulanica.world.models import StyleVersion
from exulanica.world.style_pack_library import StylePackLibrary, style_pack_library
from exulanica.world.style_packs import StylePackContext, load_context, read_manifest, role_offer

__all__ = ["OfferedPieces", "WorldPieces", "look_of", "world_pieces"]


def look_of(style: StyleVersion | None, library: StylePackLibrary) -> LookReference | None:
    """The library pack a world's pieces are made in: the pack it wears, its own look of generated
    pieces' library base, or the library's default when it names none. None for a world with no
    appearance, a creator's own pack, or a base the library no longer holds."""
    if style is None:
        return None
    pack = style.style_pack
    if pack is None:
        default = library.default_pack
        return LookReference(default.pack_id, default.version, default.manifest_sha256)
    if pack.source == "workspace":
        if pack.base is None or not pack.pack_id.startswith("generated."):
            return None
        pack = pack.base
    if not library.holds(pack.pack_id, pack.version, pack.manifest_sha256):
        return None
    return LookReference(pack.pack_id, pack.version, pack.manifest_sha256)


@dataclass(frozen=True, slots=True)
class OfferedPieces:
    """The step's request, or the code that blocks it, and what the sheet names."""

    body: dict[str, Any] | None
    code: str | None
    estimate: dict[str, Any] | None
    titles: dict[str, str]


@dataclass(frozen=True, slots=True)
class WorldPieces:
    """New pieces for one world, in the look it wears: what the planner asks for kinds by key."""

    world_id: str
    look: LookReference | None
    library: StylePackLibrary
    context: StylePackContext

    def available(self) -> bool:
        """Whether the world wears a look pieces can be made in."""
        return self.look is not None

    def offer(
        self,
        kinds: Sequence[tuple[str, int, str]],
        *,
        named: bool,
        idempotency_key: uuid.UUID,
    ) -> OfferedPieces:
        """The request for ``kinds`` (key, version and label each), or why none is asked.

        A kind with no box of its own (a being) never has a piece and is passed over. Named kinds
        are asked as named; with none named, only the kinds the look dresses with a default or
        nothing are asked, since the rest have their own pieces already. Codes:
        ``look_not_served`` (no look pieces can be made in), ``look_without_style_words`` (the
        look has no generation style words yet), ``no_piece_needed`` (nothing left to ask)."""
        look = self.look
        served = None if look is None else self.library.content.get(look.manifest_sha256)
        if look is None or served is None:
            return OfferedPieces(None, "look_not_served", None, {})
        chain = [read_manifest(json.loads(served.data), self.context)]
        asked: list[tuple[tuple[str, int, str], Any]] = []
        for kind in sorted(dict.fromkeys(kinds)):
            try:
                [planned] = plan_requests([(kind[0], kind[1])], look, library=self.library)
            except PieceAskRefused as refused:
                if refused.code == "look_without_style_words":
                    return OfferedPieces(None, refused.code, None, {})
                continue  # a kind with no piece of its own, such as a being
            if not named and role_offer(chain, planned.look_role, self.context) == "leaf":
                continue
            asked.append((kind, planned))
        asked = asked[:MAXIMUM_KINDS]
        if not asked:
            return OfferedPieces(None, "no_piece_needed", None, {})
        compute = generation_catalogs().compute.for_provider(GPU_PROVIDER)
        body = {
            "world_id": self.world_id,
            "look": {
                "pack_id": look.pack_id,
                "version": look.version,
                "manifest_sha256": look.manifest_sha256,
            },
            "kinds": [{"key": key, "version": version} for (key, version, _), _ in asked],
            "idempotency_key": str(idempotency_key),
        }
        return OfferedPieces(
            body,
            None,
            estimate([planned for _, planned in asked], compute).document(),
            {"kinds": ", ".join(label for (_, _, label), _ in asked)},
        )


def world_pieces(connection: Any, workspace_id: uuid.UUID, world_id: str) -> WorldPieces:
    """New pieces of one world's look, as the actions route hands them to the Companion's planner:
    the library pack the world wears (or its own look's base, or the library's default), read once
    for the plan on the route's connection."""
    try:
        style = WorldStyleRepository(connection, workspace_id, world_id=world_id).current()
    except WorldNotConfigured:
        style = None
    library = style_pack_library()
    return WorldPieces(world_id, look_of(style, library), library, _context())


@functools.cache
def _context() -> StylePackContext:
    """The look families and texture sets every pack is read against, read once a process."""
    return load_context(Path(__file__).resolve().parents[2])
