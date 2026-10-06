"""Committed content served by digest: bytes this tree carries, the same for every workspace.

A library of committed content (the style packs, :mod:`exulanica.world.style_pack_library`) reads
its own files once, checks them by its own rules and hands over what it serves as
:class:`ServedItem` values: the SHA-256 of the bytes, the media type they are served as, and the
bytes. :class:`CommittedContent` holds them by digest. It refuses an item whose bytes do not hash
to the digest stated for them, and one digest stated with two media types; the same bytes stated
twice with one media type, as a file two packs share, are one item.

A request names a digest and nothing else, so no request reaches a path, and a digest the index
does not hold is absent. Any later library of committed looks adds its items the same way.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

__all__ = ["DIGEST", "CommittedContent", "CommittedContentRefused", "ServedItem"]

#: A SHA-256 as 64 lowercase hexadecimal characters: the one form an address takes.
DIGEST: Final = re.compile(r"[0-9a-f]{64}")


class CommittedContentRefused(ValueError):
    """Committed bytes that do not hash to their stated digest, or one digest given two types."""


@dataclass(frozen=True, slots=True)
class ServedItem:
    """One served file: the SHA-256 of its bytes, the media type it is served as, and the bytes."""

    sha256: str
    media_type: str
    data: bytes


class CommittedContent:
    """Committed bytes by their SHA-256, each held to its digest once, when the index is made."""

    def __init__(self, items: Iterable[ServedItem]) -> None:
        held: dict[str, ServedItem] = {}
        for item in items:
            if DIGEST.fullmatch(item.sha256) is None:
                raise CommittedContentRefused(f"{item.sha256!r} is not a SHA-256 in lowercase hex")
            if hashlib.sha256(item.data).hexdigest() != item.sha256:
                raise CommittedContentRefused(
                    f"the bytes stated as {item.sha256} hash to another digest"
                )
            earlier = held.get(item.sha256)
            if earlier is not None and earlier.media_type != item.media_type:
                raise CommittedContentRefused(
                    f"{item.sha256} is stated as {earlier.media_type} and as {item.media_type}"
                )
            held[item.sha256] = item
        self._items: Mapping[str, ServedItem] = MappingProxyType(held)

    def get(self, sha256: str) -> ServedItem | None:
        """The item whose bytes ``sha256`` names, or None when this index holds none."""
        return self._items.get(sha256)

    def __contains__(self, sha256: object) -> bool:
        return sha256 in self._items

    def __iter__(self) -> Iterator[ServedItem]:
        return iter(self._items.values())

    def __len__(self) -> int:
        return len(self._items)
