"""A world's own look: a library look with passed generated pieces in place of its own.

When a world's piece requests end made, the pieces that passed are taken into the world's look
(contract: generated pieces). The look they make is a style pack version drawn on the library pack
the requests named (``exulanica.style-pack/v1``): its base is that pack at its version and digest,
and it states only modules, one for each look role a generated piece dresses. Everything else is
the base's (light, shading, edge, palette, surfaces and every other module), so the world looks as
it did apart from the new pieces. The pieces are coloured from the base's palette, which the
requests were drawn from; a module's pieces take their colours from the manifest that states it or
any manifest after it in the chain (the browser's ``resolveStylePack``).

The manifest is a function of the base chain, the applied pieces and the version number alone.
:func:`content_sha256` names the first two, so a caller that finds a version already made from the
same pieces on the same base reuses it rather than numbering another. Taking every piece back gives
no manifest at all: the world then wears the base itself. Every manifest built here is read back
through the style pack reader before it is returned, so nothing this module writes is a pack the
reader refuses.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from exulanica.world.style_packs import (
    COLOUR_ENCODING,
    MAX_VARIANTS,
    PROFILE,
    StylePackContext,
    StylePackRefused,
    canonical_json,
    manifest_sha256,
    read_manifest,
)

__all__ = [
    "MAX_CHAIN",
    "DerivedLook",
    "DerivedLookRefused",
    "GeneratedVariant",
    "build_derived_look",
    "content_sha256",
    "derived_pack_id",
    "piece_path",
]

#: A pack resolves through one to four manifests (style pack contract section 2, and the browser's
#: ``resolveStylePack``), so a derived look's base chain holds at most three.
MAX_CHAIN: Final = 4
#: A derived look's id is its base's with this segment appended.
OWN_SEGMENT: Final = "own"
#: A pack id has two to four segments, so a base of four has no derived id.
_MAX_ID_SEGMENTS: Final = 4
_CONTENT_PROFILE: Final = "exulanica.derived-look-content/v1"
_GLB: Final = "model/gltf-binary"
_TITLE_MAX: Final = 80
_TITLE_SUFFIX: Final = ", with new pieces"


class DerivedLookRefused(ValueError):
    """A derived look that cannot be built, with a code a request's record names."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


@dataclass(frozen=True, slots=True)
class GeneratedVariant:
    """One passed generated piece as a pack variant: its bytes by digest, its size, its receipt."""

    piece_sha256: str
    piece_bytes: int
    #: Width, depth and height in millimetres: the receipt's measured size.
    size_mm: tuple[int, int, int]
    receipt_sha256: str


@dataclass(frozen=True, slots=True)
class DerivedLook:
    """A derived look's manifest as the reader returned it, its canonical bytes and digests."""

    manifest: dict[str, Any]
    canonical: bytes
    sha256: str
    #: :func:`content_sha256` of the chain and pieces it was built from.
    content_sha256: str


def derived_pack_id(base_pack_id: str) -> str:
    """The id of every derived look drawn on ``base_pack_id``."""
    if base_pack_id.count(".") + 1 >= _MAX_ID_SEGMENTS:
        raise DerivedLookRefused(
            "look_id_full", f"{base_pack_id} has four segments, so no id can be drawn on it"
        )
    return f"{base_pack_id}.{OWN_SEGMENT}"


def piece_path(piece_sha256: str) -> str:
    """Where a derived look lists a generated piece: by its digest, so one piece is one file."""
    return f"generated/{piece_sha256}.glb"


def content_sha256(
    chain: Sequence[Mapping[str, Any]], roles: Mapping[str, Sequence[GeneratedVariant]]
) -> str:
    """What a derived look is made of: its base chain and its applied pieces, without a version."""
    document = {
        "profile": _CONTENT_PROFILE,
        "chain": [manifest_sha256(manifest) for manifest in chain],
        "roles": {
            role: [
                {
                    "piece_sha256": variant.piece_sha256,
                    "piece_bytes": variant.piece_bytes,
                    "size_mm": list(variant.size_mm),
                    "receipt_sha256": variant.receipt_sha256,
                }
                for variant in variants
            ]
            for role, variants in roles.items()
            if variants
        },
    }
    return hashlib.sha256(canonical_json(document).encode("ascii")).hexdigest()


def _check_chain(chain: Sequence[Mapping[str, Any]]) -> None:
    if not chain:
        raise DerivedLookRefused("chain_incomplete", "a derived look needs its base")
    if chain[0]["origin"] == "generated":
        raise DerivedLookRefused(
            "base_is_generated", "a derived look is drawn on a library look, never on another"
        )
    for index, manifest in enumerate(chain):
        named = manifest["base"]
        if index + 1 == len(chain):
            if named is not None:
                raise DerivedLookRefused(
                    "chain_incomplete", f"chain[{index}] names a base the chain does not hold"
                )
            continue
        below = chain[index + 1]
        if named is None or (named["pack_id"], named["version"], named["manifest_sha256"]) != (
            below["pack_id"],
            below["version"],
            manifest_sha256(below),
        ):
            raise DerivedLookRefused(
                "chain_broken", f"chain[{index}]'s base is not chain[{index + 1}]"
            )
    if len(chain) + 1 > MAX_CHAIN:
        raise DerivedLookRefused(
            "look_chain_full",
            f"a pack resolves through at most {MAX_CHAIN} manifests; its base chain holds "
            f"{len(chain)}",
        )


def build_derived_look(
    *,
    chain: Sequence[Mapping[str, Any]],
    version: int,
    roles: Mapping[str, Sequence[GeneratedVariant]],
    authors: Sequence[str],
    context: StylePackContext,
) -> DerivedLook | None:
    """The derived look drawn on ``chain[0]`` dressing ``roles`` with their generated pieces.

    ``chain`` is the base and every manifest below it, nearest first, each as the reader returned
    it. ``roles`` maps a look role to its passed pieces in variant order, at most
    :data:`~exulanica.world.style_packs.MAX_VARIANTS`; which pieces those are is the caller's.
    ``authors`` are the models that made them. With no piece left there is no derived look, and
    ``None`` says the world wears the base itself.
    """
    _check_chain(chain)
    applied = {role: variants for role, variants in roles.items() if variants}
    if not applied:
        return None
    base = chain[0]
    files: dict[str, dict[str, Any]] = {}
    modules: dict[str, dict[str, Any]] = {}
    receipts: set[str] = set()
    for role in sorted(applied):
        variants = applied[role]
        if len(variants) > MAX_VARIANTS:
            raise DerivedLookRefused(
                "too_many_variants",
                f"{role} has {len(variants)} pieces; a module holds at most {MAX_VARIANTS}",
            )
        entries = []
        for variant in variants:
            path = piece_path(variant.piece_sha256)
            listed = files.get(path)
            if listed is not None and listed["bytes"] != variant.piece_bytes:
                raise DerivedLookRefused(
                    "piece_size_differs", f"{variant.piece_sha256} is given two sizes in bytes"
                )
            files[path] = {
                "path": path,
                "sha256": variant.piece_sha256,
                "bytes": variant.piece_bytes,
                "media_type": _GLB,
            }
            entries.append(
                {
                    "file": path,
                    "lod1": None,
                    "size_mm": list(variant.size_mm),
                    # A generated opening states no stretch, so a door or window keeps its size.
                    "stretch_mm": [None, None, None],
                }
            )
            receipts.add(variant.receipt_sha256)
        modules[role] = {"variants": entries}
    title = base["title"]
    if len(title) + len(_TITLE_SUFFIX) <= _TITLE_MAX:
        title += _TITLE_SUFFIX
    count = len(applied)
    manifest = {
        "profile": PROFILE,
        "pack_id": derived_pack_id(base["pack_id"]),
        "version": version,
        "title": title,
        "description": (
            f"{base['title']} with generated pieces for {count} "
            f"{'part' if count == 1 else 'parts'} in place of its own."
        ),
        "tags": [],
        "origin": "generated",
        "provenance": {"kind": "generated", "receipts": sorted(receipts)},
        "licence": {"id": "CC0-1.0", "attribution": None},
        "authors": list(authors),
        "preview": None,
        "base": {
            "pack_id": base["pack_id"],
            "version": base["version"],
            "manifest_sha256": manifest_sha256(base),
        },
        "light": None,
        "shading": None,
        "edge": None,
        "palette": {"encoding": COLOUR_ENCODING, "swatches": []},
        "surfaces": {},
        "modules": modules,
        # Paths are ASCII, so code point order is the reader's UTF-16 order.
        "files": [files[path] for path in sorted(files)],
    }
    try:
        read = read_manifest(manifest, context)
    except StylePackRefused as refused:
        raise DerivedLookRefused("refused_by_reader", str(refused)) from refused
    text = canonical_json(read)
    return DerivedLook(
        manifest=read,
        canonical=text.encode("ascii"),
        sha256=manifest_sha256(read),
        content_sha256=content_sha256(chain, applied),
    )
