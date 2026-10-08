"""The words a piece request carries for a style pack: the piece style catalog.

A request names its pack's palette and a few style words for the concept picture
(``pack.style``, at most 120 characters). A pack's own description is written for a person and
speaks of light, sky and fog that one piece on a plain background cannot show, and is often longer
than a request allows, so the words come from
``assets/catalogs/generation/piece-styles.v1.json``: one entry per committed pack, plain lower
case words with no numeral (a picture model paints a numeral it is told), each with the reason it
was chosen and whether it was measured. A pack with no entry has no generated pieces.

Plain Python with no numpy: the product reads this module.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Final

from exulanica_pieces.canonical import (
    Refused,
    canonical_bytes,
    exact_keys,
    is_count,
    parse_strict,
    sha256_hex,
)
from exulanica_pieces.recipes import _plain

__all__ = ["STYLES_CATALOG_ID", "STYLES_PATH", "PieceStyles", "load_styles", "read_styles"]

#: Relative to the repository root.
STYLES_PATH: Final = "assets/catalogs/generation/piece-styles.v1.json"
STYLES_CATALOG_ID: Final = "piece-styles"
_CATALOG_KEYS: Final = ("catalog_id", "catalog_version", "entries", "schema_version")
_ENTRY_KEYS: Final = ("licence", "pack_id", "reason", "style")
_LICENCE_KEYS: Final = ("content_source", "licence_source", "origin", "spdx", "verdict")
#: A style pack's id (style-pack-contract.md): lower case dotted words.
_PACK_ID: Final = re.compile(r"[a-z0-9][a-z0-9.-]{0,63}")
#: A request's own limit on its style words (exulanica_pieces.records).
_MAX_STYLE: Final = 120
_REASON_WORDS: Final = 5


@dataclass(frozen=True, slots=True)
class PieceStyles:
    """The read catalog: its version, its digest and each pack's style words by pack id."""

    catalog_version: int
    sha256: str
    words: Mapping[str, str]


def read_styles(raw: bytes) -> PieceStyles:
    """The catalog, strictly: the house envelope, exact keys, each pack once, plain words."""
    where = STYLES_PATH
    document = exact_keys(parse_strict(raw, where), _CATALOG_KEYS, where)
    if document["schema_version"] != 1 or document["catalog_id"] != STYLES_CATALOG_ID:
        raise Refused(f"{where} is schema version 1 of catalog {STYLES_CATALOG_ID!r}")
    if not is_count(document["catalog_version"], 1):
        raise Refused(f"{where}: catalog_version is a whole number from 1")
    entries = document["entries"]
    if not isinstance(entries, list):
        raise Refused(f"{where}: entries is a list")
    words: dict[str, str] = {}
    for index, value in enumerate(entries):
        at = f"{where}: entries[{index}]"
        entry = exact_keys(value, _ENTRY_KEYS, at)
        pack_id = entry["pack_id"]
        if not isinstance(pack_id, str) or _PACK_ID.fullmatch(pack_id) is None:
            raise Refused(f"{at}.pack_id is a style pack's id")
        if pack_id in words:
            raise Refused(f"{at}.pack_id {pack_id} is named a second time")
        reason = entry["reason"]
        if not isinstance(reason, str) or len(reason.split()) < _REASON_WORDS:
            raise Refused(f"{at}.reason says, in a sentence, why these words")
        licence = exact_keys(entry["licence"], _LICENCE_KEYS, f"{at}.licence")
        if licence["origin"] != "original" or licence["verdict"] != "SHIP":
            raise Refused(f"{at}.licence is original content that ships")
        words[pack_id] = _plain(entry["style"], _MAX_STYLE, f"{at}.style")
    return PieceStyles(
        catalog_version=document["catalog_version"],
        sha256=sha256_hex(canonical_bytes(document)),
        words=MappingProxyType(words),
    )


def load_styles(repository: Path) -> PieceStyles:
    """The committed catalog."""
    return read_styles((repository / STYLES_PATH).read_bytes())
