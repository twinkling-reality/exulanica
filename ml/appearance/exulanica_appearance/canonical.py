"""Canonical JSON and the small checks every appearance record shares.

Every record this package writes is canonical JSON: sorted keys, no spaces, ASCII, integers only.
A record's identity is the sha256 of those bytes. A reader parses strictly (no repeated key, no
fraction, no other spelling of the same document), so two records with the same meaning always
have the same digest, and a record that was edited by hand into another form is refused rather than
silently re-serialised.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any, Final

__all__ = [
    "Refused",
    "canonical_bytes",
    "exact_keys",
    "is_count",
    "is_revision",
    "is_sha256",
    "is_text",
    "parse_canonical",
    "sha256_hex",
]

_SHA256: Final = re.compile(r"[0-9a-f]{64}")
_REVISION: Final = re.compile(r"[0-9a-f]{40}")
_TEXT: Final = re.compile(r"[\x20-\x7e]+")


class Refused(ValueError):
    """A record, input or file is not what its profile or its manifest says it is."""


def canonical_bytes(value: Any) -> bytes:
    """The repository's canonical JSON: sorted keys, no spaces, ASCII, integers only."""

    def check(node: Any, path: str) -> None:
        if isinstance(node, float):
            raise Refused(f"{path} is a fraction; records hold integers in a stated unit")
        if isinstance(node, bool) or node is None or isinstance(node, (int, str)):
            return
        if isinstance(node, Mapping):
            for key, item in node.items():
                if not isinstance(key, str):
                    raise Refused(f"{path} has a key that is not text")
                check(item, f"{path}.{key}")
            return
        if isinstance(node, (list, tuple)):
            for index, item in enumerate(node):
                check(item, f"{path}[{index}]")
            return
        raise Refused(f"{path} is a {type(node).__name__}, which no record holds")

    check(value, "$")
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
        "ascii"
    )


def parse_canonical(raw: bytes, where: str) -> Any:
    """Parse ``raw`` strictly and refuse it unless it is its own canonical form."""

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in items:
            if key in result:
                raise Refused(f"{where} repeats the key {key!r}")
            result[key] = item
        return result

    def refuse_fraction(literal: str) -> Any:
        raise Refused(f"{where} holds the fraction {literal}")

    try:
        document = json.loads(
            raw.decode("ascii"), object_pairs_hook=pairs, parse_float=refuse_fraction
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise Refused(f"{where} is not ASCII JSON") from error
    if canonical_bytes(document) != raw:
        raise Refused(f"{where} is not canonical JSON")
    return document


def sha256_hex(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def is_sha256(value: object) -> bool:
    return isinstance(value, str) and _SHA256.fullmatch(value) is not None


def is_revision(value: object) -> bool:
    return isinstance(value, str) and _REVISION.fullmatch(value) is not None


def is_text(value: object) -> bool:
    """Non-empty printable ASCII."""
    return isinstance(value, str) and _TEXT.fullmatch(value) is not None


def is_count(value: object, minimum: int = 0) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= minimum


def exact_keys(value: object, keys: tuple[str, ...] | frozenset[str], where: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != set(keys):
        raise Refused(f"{where} has exactly {', '.join(sorted(keys))}")
    return value
