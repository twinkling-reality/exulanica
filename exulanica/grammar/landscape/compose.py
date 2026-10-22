"""Realize a landscape's placed volumes: their chunks at each level and their walkable tops.

The land is realized by the land's own realizer under its own rules (the world layer already does
that for a site); this module realizes what the land cannot state. In a fixed order, placement by
placement in the document's order:

1. **A seed of its own.** Each placement draws its volume's seed from the landscape's seed and its
   own id under this module's prefix (:func:`placement_seed`), so one volume placed twice weathers
   differently in each place, and nothing is drawn from a digest anyone can read.
2. **Chunks** of its surface at every level the landscape states, coarsest first
   (:func:`~exulanica.grammar.volumes.realize_volume`), in the volume's own frame: the placement's
   origin and turn place them in the world, so a chunk is the same wherever its volume stands. The
   volume is realized by the volume rules the landscape was read under, its top capped by the
   heights given for that placement where some are (a site's graded top), which every chunk and
   top it makes names.
3. **Walkable tops** (:func:`~exulanica.grammar.volumes.volume_tops`), also in the volume's frame.

The result is the drawing's ``volumes`` section, which names every chunk and top by digest, and the
documents those digests name, to be kept and served by digest. Tops are of each volume alone: where
volumes meet, which top is walked is the walking layer's to say.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

from exulanica.grammar.landscape.document import LandscapeDocument
from exulanica.grammar.volumes import (
    TopHeights,
    VolumeChunk,
    VolumeField,
    VolumeSheet,
    input_sha256,
    realize_volume,
    volume_tops,
)

__all__ = [
    "SEED_PREFIX",
    "PlacedVolume",
    "compose_volumes",
    "placement_seed",
    "volume_bodies",
    "volumes_section",
]

#: The prefix a placement's seed is drawn under.
SEED_PREFIX: Final = b"exulanica.landscape-volume/v1"

#: The volumes the last composition realized, by what each realization is a function of (its
#: field's input digest) and the levels realized: a landscape composed again with one volume's
#: given top changed (a site's part edit regrades its top) realizes only that volume. One
#: landscape's worth, replaced by each composition, so it holds no more than a composition does.
_Realized = tuple[tuple[VolumeChunk, ...], tuple[VolumeSheet, ...]]
_realized: dict[tuple[str, tuple[int, ...]], _Realized] = {}


def placement_seed(seed: str, placement_id: str) -> bytes:
    """The seed a placed volume is realized with, from the landscape's seed and its id."""
    return hashlib.sha256(
        SEED_PREFIX + b"\x1f" + seed.encode() + b"\x1f" + placement_id.encode()
    ).digest()


@dataclass(frozen=True)
class PlacedVolume:
    id: str
    volume_sha256: str
    input_sha256: str
    at_mm: tuple[int, int, int]
    yaw_mdeg: int
    chunks: tuple[VolumeChunk, ...]
    tops: tuple[VolumeSheet, ...]

    def section(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "volume_sha256": self.volume_sha256,
            "input_sha256": self.input_sha256,
            "at_mm": list(self.at_mm),
            "yaw_mdeg": self.yaw_mdeg,
            "chunks": [
                {"chunk": list(chunk.chunk), "cell_mm": chunk.cell_mm, "sha256": chunk.sha256}
                for chunk in self.chunks
            ],
            "tops": [{"surface": top.surface, "sha256": top.sha256} for top in self.tops],
        }


def compose_volumes(
    landscape: LandscapeDocument, seed: str, tops: Mapping[str, TopHeights] | None = None
) -> tuple[PlacedVolume, ...]:
    """Every placed volume of the landscape, realized under ``seed``, in the document's order, a
    placement named in ``tops`` capped by the heights given for it. A volume the last composition
    realized from the same inputs at the same levels is that realization."""
    global _realized
    given = tops or {}
    held, kept = _realized, {}
    placed = []
    for placement in landscape.placements:
        field = VolumeField(
            placement.volume,
            placement_seed(seed, placement.id),
            rules=landscape.volume_rules,
            top=given.get(placement.id),
        )
        digest = input_sha256(field)
        key = (digest, tuple(landscape.levels))
        made = held.get(key) or kept.get(key)
        if made is None:
            made = (
                tuple(chunk for cell in landscape.levels for chunk in realize_volume(field, cell)),
                volume_tops(field),
            )
        kept[key] = made
        placed.append(
            PlacedVolume(
                id=placement.id,
                volume_sha256=placement.volume.sha256,
                input_sha256=digest,
                at_mm=placement.at_mm,
                yaw_mdeg=placement.yaw_mdeg,
                chunks=made[0],
                tops=made[1],
            )
        )
    _realized = kept
    return tuple(placed)


def volumes_section(placed: tuple[PlacedVolume, ...]) -> dict[str, Any]:
    """The drawing's ``volumes`` section: each placement and the digests of its chunks and tops."""
    return {"volumes": [volume.section() for volume in placed]}


def volume_bodies(placed: tuple[PlacedVolume, ...]) -> dict[str, dict[str, Any]]:
    """Every chunk and top document the section names, by its digest."""
    bodies: dict[str, dict[str, Any]] = {}
    for volume in placed:
        for chunk in volume.chunks:
            bodies[chunk.sha256] = chunk.document()
        for top in volume.tops:
            bodies[top.sha256] = top.document()
    return bodies
